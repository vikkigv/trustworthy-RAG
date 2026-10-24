"""POST /query — streaming grounded answers over the tenant's indexed chunks.

SSE protocol (one JSON payload per event):
  retrieved  → {citations: [...]}            evidence is in before generation
  token      → {text: "..."}                 streamed answer tokens
  done       → {query_log_id, answer, citations, confidence}
"""

import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.core.deps import CurrentAuth, DbSession
from api.schemas.query import Citation, QueryRequest
from trust_rag.db.models import Claim as ClaimRow
from trust_rag.db.models import ClaimVerdict as ClaimVerdictEnum
from trust_rag.db.models import QueryLog
from trust_rag.db.session import get_session_factory
from trust_rag.generation.llm import astream_answer, build_context
from trust_rag.observability import flush, start_trace
from trust_rag.retrieval.hybrid import RetrievedChunk, hybrid_search
from trust_rag.settings import get_settings
from trust_rag.verification.verifier import verify_answer

router = APIRouter(prefix="/query", tags=["query"])

SNIPPET_LEN = 200


def _citation(number: int, chunk: RetrievedChunk) -> Citation:
    return Citation(
        number=number,
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        snippet=chunk.content[:SNIPPET_LEN],
        rrf_score=chunk.rrf_score,
        dense_rank=chunk.dense_rank,
        sparse_rank=chunk.sparse_rank,
    )


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("")
async def query(body: QueryRequest, ctx: CurrentAuth, session: DbSession) -> StreamingResponse:
    started = time.monotonic()
    trace = start_trace(
        name="query", input=body.question, user_id=str(ctx.user_id or ctx.tenant_id)
    )
    retrieval_span = trace.span(name="hybrid-retrieval", input=body.question)
    chunks = await hybrid_search(session, ctx.tenant_id, body.question, top_k=body.top_k)
    retrieval_span.end(
        output=[{"chunk_id": str(c.id), "rrf_score": c.rrf_score} for c in chunks]
    )
    citations = [_citation(i + 1, c) for i, c in enumerate(chunks)]

    async def stream() -> AsyncIterator[str]:
        answer_parts: list[str] = []

        if not chunks:
            # Nothing indexed for this tenant — abstain immediately (step 8
            # generalizes this into confidence-based abstention).
            yield _sse("retrieved", {"citations": []})
            yield _sse(
                "done",
                {
                    "query_log_id": None,
                    "answer": "I don't have enough information to answer this.",
                    "citations": [],
                    "confidence": 0.0,
                },
            )
            return

        yield _sse("retrieved", {"citations": [c.model_dump(mode="json") for c in citations]})

        context = build_context(chunks)
        generation_span = trace.generation(
            name="grounded-answer",
            input={"question": body.question, "context": context},
            model=get_settings().generation_model,
        )
        async for token in astream_answer(body.question, context):
            answer_parts.append(token)
            yield _sse("token", {"text": token})

        answer = "".join(answer_parts)
        generation_span.end(output=answer)
        latency_ms = int((time.monotonic() - started) * 1000)

        # Trust layer: verify each claim against the retrieved evidence.
        verification_span = trace.span(name="claim-verification", input=answer)
        verification = await verify_answer(answer, chunks)
        verification_span.end(
            output={"confidence": verification.confidence, "abstain": verification.abstain}
        )
        yield _sse(
            "claims",
            {
                "claims": [
                    {
                        "text": c.text,
                        "verdict": c.verdict,
                        "supporting_chunk_ids": c.supporting_chunk_ids,
                    }
                    for c in verification.claims
                ],
                "abstain": verification.abstain,
                "reason": verification.reason,
            },
        )

        final_answer = (
            "I don't have enough confidence in the retrieved evidence to answer. "
            f"({verification.reason})" if verification.abstain else answer
        )

        log = QueryLog(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            question=body.question,
            answer=final_answer,
            confidence=verification.confidence,
            latency_ms=latency_ms,
            retrieved_chunk_ids=[
                {"chunk_id": str(c.id), "rrf_score": c.rrf_score} for c in chunks
            ],
        )
        # The request-scoped session is closed once streaming starts, so the
        # writes below use their own short-lived session.
        async with get_session_factory()() as log_session:
            log_session.add(log)
            await log_session.flush()
            log_session.add_all(
                ClaimRow(
                    query_log_id=log.id,
                    text=c.text,
                    verdict=ClaimVerdictEnum(c.verdict),
                    supporting_chunk_ids=c.supporting_chunk_ids,
                )
                for c in verification.claims
            )
            await log_session.commit()

        trace.update(
            output=final_answer,
            metadata={"confidence": verification.confidence, "abstain": verification.abstain},
        )
        flush()
        yield _sse(
            "done",
            {
                "query_log_id": str(log.id),
                "answer": final_answer,
                "citations": [c.model_dump(mode="json") for c in citations],
                "confidence": verification.confidence,
                "abstain": verification.abstain,
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
