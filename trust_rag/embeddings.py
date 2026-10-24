"""Embedding client — one seam for the whole system.

All embedding calls (ingestion, semantic cache, query-time) go through
`embed_texts`, so swapping models or mocking in tests happens in one place.
"""

from litellm import aembedding

from trust_rag.settings import get_settings

BATCH_SIZE = 100  # OpenAI embedding API limit is 2048 inputs; 100 keeps payloads sane


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        response = await aembedding(model=settings.embedding_model, input=batch)
        vectors.extend(item["embedding"] for item in response.data)
    return vectors
