"""Evaluation harness.

Runs the golden dataset end-to-end against a freshly created eval tenant:
ingest corpus → for each question: retrieve → generate → verify → score.

Metrics (computed from our own trust layer — no external LLM judge needed):
  retrieval_hit_rate   answerable questions where the expected doc was retrieved
  answer_success_rate  answerable questions answered correctly and not abstained
  abstention_accuracy  unanswerable questions where the system abstained
  mean_confidence      average verifier confidence over answerable questions
Results persist to eval_runs/eval_scores for the v2 dashboard.
"""

import asyncio
import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from trust_rag.db.models import Document, DocumentStatus, EvalRun, EvalScore
from trust_rag.db.session import get_session_factory
from trust_rag.generation.llm import astream_answer, build_context
from trust_rag.ingestion.pipeline import run_ingestion
from trust_rag.retrieval.hybrid import hybrid_search
from trust_rag.settings import get_settings
from trust_rag.storage import init_storage
from trust_rag.verification.verifier import verify_answer

CORPUS_DIR = Path(__file__).parents[2] / "evals" / "corpus"
DEFAULT_DATASET = Path(__file__).parents[2] / "evals" / "golden_dataset.jsonl"
TOP_K = 6


@dataclass
class GoldenItem:
    id: str
    category: str
    question: str
    expected_keywords: list[str]
    expected_doc: str | None


@dataclass
class ItemResult:
    item: GoldenItem
    retrieved_docs: list[str]
    answer: str
    confidence: float
    abstain: bool

    @property
    def retrieval_hit(self) -> bool:
        return self.item.expected_doc in self.retrieved_docs

    REFUSAL_PHRASE = "don't have enough information"

    @property
    def refused(self) -> bool:
        """Honest refusal — by the verifier OR by the generator itself."""
        return self.abstain or self.REFUSAL_PHRASE in self.answer.lower()

    @property
    def answer_correct(self) -> bool:
        if self.abstain:
            return False
        low = self.answer.lower()
        return any(k.lower() in low for k in self.item.expected_keywords)


def load_dataset(path: Path = DEFAULT_DATASET) -> list[GoldenItem]:
    items = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        items.append(
            GoldenItem(
                id=d["id"],
                category=d["category"],
                question=d["question"],
                expected_keywords=d.get("expected_keywords", []),
                expected_doc=d.get("expected_doc"),
            )
        )
    return items


def compute_metrics(results: list[ItemResult]) -> dict[str, float]:
    answerable = [r for r in results if r.item.category == "answerable"]
    unanswerable = [r for r in results if r.item.category == "unanswerable"]

    def rate(sub: list[ItemResult], prop: str) -> float:
        if not sub:
            return 0.0
        vals = [getattr(r, prop) for r in sub]
        return round(sum(vals) / len(vals), 4)

    return {
        "retrieval_hit_rate": rate(answerable, "retrieval_hit"),
        "answer_success_rate": rate(answerable, "answer_correct"),
        "abstention_accuracy": rate(unanswerable, "refused"),
        "mean_confidence": round(
            sum(r.confidence for r in answerable) / len(answerable), 4
        ) if answerable else 0.0,
        "n_answerable": float(len(answerable)),
        "n_unanswerable": float(len(unanswerable)),
    }


async def _seed_eval_tenant() -> uuid.UUID:
    """Fresh tenant + ingested corpus, so evals never touch real tenants."""
    from trust_rag.db.models import Tenant
    from trust_rag.storage import get_storage

    sessions = get_session_factory()
    init_storage(get_settings().data_dir)
    async with sessions() as session:
        tenant = Tenant(name=f"eval-{uuid.uuid4().hex[:8]}")
        session.add(tenant)
        await session.flush()
        doc_ids: list[uuid.UUID] = []

        for corpus_file in sorted(CORPUS_DIR.glob("*.md")):
            doc = Document(
                tenant_id=tenant.id,
                filename=corpus_file.name,
                mime_type="text/markdown",
                checksum=uuid.uuid4().hex,  # unique per eval run
                status=DocumentStatus.PENDING,
            )
            session.add(doc)
            await session.flush()
            await get_storage().save(tenant.id, doc.id, corpus_file.read_bytes())
            doc_ids.append(doc.id)
        await session.commit()
        tenant_id = tenant.id

    for doc_id in doc_ids:
        await run_ingestion(doc_id)
    return tenant_id


async def run_eval(dataset_path: Path = DEFAULT_DATASET) -> dict[str, float]:
    items = load_dataset(dataset_path)
    tenant_id = await _seed_eval_tenant()
    sessions = get_session_factory()

    results: list[ItemResult] = []
    async with sessions() as session:
        for item in items:
            chunks = await hybrid_search(session, tenant_id, item.question, top_k=TOP_K)
            retrieved_docs = []
            context = build_context(chunks)
            answer_parts = []
            async for token in astream_answer(item.question, context):
                answer_parts.append(token)
            answer = "".join(answer_parts)
            verification = await verify_answer(answer, chunks) if chunks else None

            # Map retrieved chunk ids back to filenames.
            doc_names = {
                str(d.id): d.filename
                for d in (
                    await session.execute(
                        select(Document).where(Document.tenant_id == tenant_id)
                    )
                ).scalars()
            }
            retrieved_docs = [doc_names.get(str(c.document_id)) or "?" for c in chunks]

            results.append(
                ItemResult(
                    item=item,
                    retrieved_docs=retrieved_docs,
                    answer=answer,
                    confidence=verification.confidence if verification else 0.0,
                    abstain=(verification.abstain if verification else True),
                )
            )
            mark = "OK " if (results[-1].answer_correct or (item.category == "unanswerable" and results[-1].abstain)) else "!! "
            print(
                f"  {mark}{item.id} [{item.category}] conf={results[-1].confidence:.2f} "
                f"abstain={results[-1].abstain} :: {answer[:60]}"
            )

    metrics = compute_metrics(results)
    await _persist(metrics)
    return metrics


async def _persist(metrics: dict[str, float]) -> None:
    try:
        git_sha = (
            await asyncio.to_thread(
                subprocess.run,
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, check=True,
            )
        ).stdout.strip()
    except subprocess.CalledProcessError:
        git_sha = "unknown"

    sessions = get_session_factory()
    async with sessions() as session:
        run = EvalRun(
            git_sha=git_sha,
            config={
                "generation_model": get_settings().generation_model,
                "verification_model": get_settings().verification_model,
                "embedding_model": get_settings().embedding_model,
                "top_k": TOP_K,
                "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
        session.add(run)
        await session.flush()
        for metric, value in metrics.items():
            session.add(EvalScore(eval_run_id=run.id, metric=metric, value=value))
        await session.commit()
