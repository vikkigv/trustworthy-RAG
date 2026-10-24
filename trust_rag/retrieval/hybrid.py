"""Hybrid retrieval: dense (pgvector cosine) + sparse (tsvector BM25) fused via RRF.

Tenant isolation is enforced inside the SQL — both CTEs filter on tenant_id
before any ranking happens, so a chunk from another tenant can never surface.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trust_rag.embeddings import EMBEDDING_DIM, embed_texts

RRF_K = 60  # standard reciprocal-rank constant
FUSE_DEPTH = 50  # candidates taken from each leg before fusion

_SEARCH_SQL = text(
    """
    WITH dense AS (
        SELECT id,
               ROW_NUMBER() OVER (ORDER BY embedding <=> (:qvec)::vector) AS rank
        FROM chunks
        WHERE tenant_id = :tenant_id AND embedding IS NOT NULL
        ORDER BY embedding <=> (:qvec)::vector
        LIMIT :fuse_depth
    ),
    sparse AS (
        SELECT id,
               ROW_NUMBER() OVER (
                   ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('english', :qtext)) DESC
               ) AS rank
        FROM chunks
        WHERE tenant_id = :tenant_id
          AND tsv @@ websearch_to_tsquery('english', :qtext)
        ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('english', :qtext)) DESC
        LIMIT :fuse_depth
    )
    SELECT c.id,
           c.document_id,
           c.chunk_index,
           c.content,
           COALESCE(1.0 / (:rrf_k + d.rank), 0) + COALESCE(1.0 / (:rrf_k + s.rank), 0) AS rrf_score,
           d.rank AS dense_rank,
           s.rank AS sparse_rank
    FROM chunks c
    JOIN dense d ON d.id = c.id
    FULL OUTER JOIN sparse s ON s.id = c.id
    ORDER BY rrf_score DESC
    LIMIT :top_k
    """
)


@dataclass(frozen=True)
class RetrievedChunk:
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    content: str
    rrf_score: float
    dense_rank: int | None
    sparse_rank: int | None

    @property
    def from_both_legs(self) -> bool:
        """Chunks found by both dense and sparse search are strong evidence."""
        return self.dense_rank is not None and self.sparse_rank is not None


async def hybrid_search(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    query_text: str,
    top_k: int = 10,
) -> list[RetrievedChunk]:
    """Embed the query (once) and fuse dense + sparse results via RRF."""
    vectors = await embed_texts([query_text])
    if len(vectors[0]) != EMBEDDING_DIM:
        raise RuntimeError(
            f"Query embedding dim {len(vectors[0])} != column dim {EMBEDDING_DIM}"
        )
    qvec = "[" + ",".join(f"{x:.6f}" for x in vectors[0]) + "]"

    result = await session.execute(
        _SEARCH_SQL,
        {
            "qvec": qvec,
            "qtext": query_text,
            "tenant_id": tenant_id,
            "fuse_depth": FUSE_DEPTH,
            "rrf_k": RRF_K,
            "top_k": top_k,
        },
    )
    return [
        RetrievedChunk(
            id=row.id,
            document_id=row.document_id,
            chunk_index=row.chunk_index,
            content=row.content,
            rrf_score=float(row.rrf_score or 0.0),  # Decimal -> float for JSONB
            dense_rank=row.dense_rank,
            sparse_rank=row.sparse_rank,
        )
        for row in result
    ]
