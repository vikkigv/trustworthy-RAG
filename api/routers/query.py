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
from trust_rag.db.models import QueryLog
from trust_rag.db.session import get_session_factory
from trust_rag.generation.llm import astream_answer, build_context
from trust_rag.retrieval.hybrid import RetrievedChunk, hybrid_search

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
    chunks = await hybrid_search(session, ctx.tenant_id, body.question, top_k=body.top_k)
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
        async for token in astream_answer(body.question, context):
            answer_parts.append(token)
            yield _sse("token", {"text": token})

        answer = "".join(answer_parts)
        latency_ms = int((time.monotonic() - started) * 1000)

        log = QueryLog(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            question=body.question,
            answer=answer,
            confidence=0.0,  # real scoring lands in v1 step 8 (verification)
            latency_ms=latency_ms,
            retrieved_chunk_ids=[
                {"chunk_id": str(c.id), "rrf_score": c.rrf_score} for c in chunks
            ],
        )
        # The request-scoped session is closed once streaming starts, so the
        # log write uses its own short-lived session.
        async with get_session_factory()() as log_session:
            log_session.add(log)
            await log_session.commit()

        yield _sse(
            "done",
            {
                "query_log_id": str(log.id),
                "answer": answer,
                "citations": [c.model_dump(mode="json") for c in citations],
                "confidence": 0.0,
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
