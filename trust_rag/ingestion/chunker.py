"""Chunking: split extracted text into retrieval-sized, overlapping chunks.

Strategy: paragraph-aware greedy packing. Chunks are assembled from whole
paragraphs up to ~CHUNK_SIZE chars (≈250 tokens) — keeping paragraph boundaries
intact preserves semantic units, which measurably beats naive fixed slicing.
"""

import re
from dataclasses import dataclass

CHUNK_SIZE = 1000  # characters, ≈ 250 tokens
CHUNK_OVERLAP = 150  # characters of trailing context carried into the next chunk
MIN_CHUNK_SIZE = 50  # tail smaller than this merges into the previous chunk

_PARA_SPLIT = re.compile(r"\n{2,}")
_WHITESPACE = re.compile(r"[ \t]+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


@dataclass(frozen=True)
class Chunk:
    index: int
    content: str


def chunk_text(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    paragraphs = [p for p in (_normalize(x) for x in _PARA_SPLIT.split(text)) if p]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        # A single paragraph longer than chunk_size gets hard-split with overlap.
        while len(para) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:chunk_size])
            para = para[chunk_size - overlap :]
        if not current:
            current = para
        elif len(current) + len(para) + 1 <= chunk_size:
            current = f"{current} {para}"
        else:
            chunks.append(current)
            candidate = f"{current[-overlap:]} {para}" if overlap else para
            # Overlap tail + paragraph may overshoot; cap at chunk_size.
            current = candidate[:chunk_size] if len(candidate) > chunk_size else candidate
    if current:
        chunks.append(current)

    # Merge a too-small tail into its predecessor.
    if len(chunks) >= 2 and len(chunks[-1]) < MIN_CHUNK_SIZE:
        chunks[-2] = f"{chunks[-2]} {chunks[-1]}".strip()
        chunks.pop()

    return [Chunk(index=i, content=c) for i, c in enumerate(chunks)]
