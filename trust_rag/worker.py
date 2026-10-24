"""Arq worker — runs the ingestion pipeline jobs (parse → chunk → embed → index)."""

from typing import ClassVar

from arq.connections import RedisSettings

from trust_rag.settings import get_settings


async def startup(ctx: dict) -> None:
    pass


async def shutdown(ctx: dict) -> None:
    pass


async def ingest_document(ctx: dict, document_id: str) -> None:
    """v1 stub: parse → chunk → embed → index into pgvector + tsvector."""
    raise NotImplementedError("ingestion pipeline lands in v1 step 3")


class WorkerSettings:
    functions: ClassVar = [ingest_document]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
