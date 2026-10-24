"""Embedding client — one seam for the whole system.

Backend: self-hosted BGE-M3 via sentence-transformers (Z.ai and most chat-first
providers don't offer embeddings). The model loads lazily, once per process,
and encoding runs in a worker thread so the event loop isn't blocked.

All embedding calls (ingestion, semantic cache, query-time) go through
`embed_texts`, so swapping backends happens in exactly one place.
"""

import asyncio
import threading
from typing import Any

from trust_rag.settings import get_settings

EMBEDDING_DIM = 1024  # BGE-M3 output size; must match chunks.embedding column

_model: Any = None  # SentenceTransformer | None
_model_lock = threading.Lock()


def _get_model() -> Any:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(get_settings().local_embedding_model)
    return _model


def _encode_sync(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    vectors = model.encode(
        texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True
    )
    return [v.tolist() for v in vectors]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return await asyncio.get_running_loop().run_in_executor(None, _encode_sync, texts)
