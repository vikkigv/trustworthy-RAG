"""Ingestion pipeline: parse → chunk → embed → index.

Idempotent: re-running on the same document replaces its chunks (delete-then-
insert), so a failed run can simply be retried by enqueuing the job again.
"""

from uuid import UUID

from sqlalchemy import delete, func, select, update

from trust_rag.db.models import Chunk, Document
from trust_rag.db.session import get_session_factory
from trust_rag.embeddings import embed_texts
from trust_rag.ingestion.chunker import chunk_text
from trust_rag.ingestion.parsers import parse
from trust_rag.storage import get_storage


async def run_ingestion(document_id: UUID) -> int:
    """Index one document; returns the number of chunks written."""
    sessions = get_session_factory()
    async with sessions() as session:
        document = (
            await session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one()

        data = await get_storage().open(f"{document.tenant_id}/{document.id}")
        text = parse(data, document.mime_type)
        chunks = chunk_text(text)

        vectors = await embed_texts([c.content for c in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"Embedder returned {len(vectors)} vectors for {len(chunks)} chunks"
            )

        # Idempotent re-index: drop any chunks from a previous attempt.
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id))

        now = func.now()
        rows = [
            {
                "document_id": document.id,
                "tenant_id": document.tenant_id,
                "chunk_index": chunk.index,
                "content": chunk.content,
                "embedding": vector,
                "tsv": func.to_tsvector("english", chunk.content),
                "valid_from": now,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        session.add_all([Chunk(**row) for row in rows])

        # Temporal versioning: if this document supersedes an older version,
        # close the predecessor's chunks at the same instant ours open —
        # "as of" queries before the cutover see the old text, after see ours.
        if document.supersedes_id is not None:
            await session.execute(
                update(Chunk)
                .where(
                    Chunk.document_id == document.supersedes_id,
                    Chunk.valid_to.is_(None),
                )
                .values(valid_to=now)
            )

        await session.commit()
        return len(rows)
