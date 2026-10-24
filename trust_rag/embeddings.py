"""Embedding client — one seam for the whole system.

Backend: Ollama's OpenAI-compatible endpoint (default model: bge-m3, 1024-dim).
All embedding calls (ingestion, semantic cache, query-time) go through
`embed_texts`, so swapping backends happens in exactly one place.
"""

from litellm import aembedding

from trust_rag.settings import get_settings

BATCH_SIZE = 32
EMBEDDING_DIM = 1024  # bge-m3 output size; must match chunks.embedding column
OLLAMA_DUMMY_KEY = "ollama"  # Ollama ignores the key; litellm requires one


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        response = await aembedding(
            model=f"openai/{settings.embedding_model}",
            input=batch,
            api_base=settings.embedding_api_base,
            api_key=OLLAMA_DUMMY_KEY,
        )
        vectors.extend(item["embedding"] for item in response.data)
    return vectors
