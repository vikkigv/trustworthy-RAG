"""Ingestion pipeline: parse → chunk → embed → index (implemented in v1 step 5)."""

from uuid import UUID


async def run_ingestion(document_id: UUID) -> None:
    raise NotImplementedError("ingestion pipeline lands in v1 step 5")
