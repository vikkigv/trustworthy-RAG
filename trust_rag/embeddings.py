"""Embedding client — one seam for the whole system.

All embedding calls (ingestion, semantic cache, query-time) go through
`embed_texts`, so swapping models or mocking in tests happens in one place.
"""

from litellm import aembedding

from trust_rag.settings import get_settings

BATCH_SIZE = 100  # keep request payloads sane
EMBEDDING_DIM = 2000  # must match chunks.embedding; pgvector HNSW caps at 2000


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        response = await aembedding(
            model=settings.embedding_model, input=batch, dimensions=EMBEDDING_DIM
        )
        vectors.extend(item["embedding"] for item in response.data)
    return vectors
