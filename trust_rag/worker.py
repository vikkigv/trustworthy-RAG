"""Arq worker — runs the ingestion pipeline jobs (parse → chunk → embed → index)."""

from typing import ClassVar
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import update

from trust_rag.db.models import Document, DocumentStatus, IngestionJob, IngestionJobStatus
from trust_rag.db.session import SessionFactory, dispose_engine, init_engine
from trust_rag.settings import get_settings


async def startup(ctx: dict) -> None:
    settings = get_settings()
    init_engine(settings.database_url)
    ctx["settings"] = settings


async def shutdown(ctx: dict) -> None:
    await dispose_engine()


async def ingest_document(ctx: dict, document_id: str) -> None:
    """Mark the job running, delegate to the pipeline (step 5), record the outcome."""
    doc_uuid = UUID(document_id)
    async with SessionFactory() as session:
        job = (
            await session.execute(
                update(IngestionJob)
                .where(
                    IngestionJob.document_id == doc_uuid,
                    IngestionJob.status == IngestionJobStatus.QUEUED,
                )
                .values(status=IngestionJobStatus.RUNNING, attempts=IngestionJob.attempts + 1)
                .returning(IngestionJob.id)
            )
        ).scalar_one_or_none()
        if job is None:
            return  # already picked up by another worker / deleted

        await session.execute(
            update(Document)
            .where(Document.id == doc_uuid)
            .values(status=DocumentStatus.PROCESSING)
        )
        await session.commit()

    try:
        from trust_rag.ingestion.pipeline import run_ingestion  # step 5 implements this

        await run_ingestion(doc_uuid)
    except NotImplementedError:
        async with SessionFactory() as session:
            await session.execute(
                update(Document)
                .where(Document.id == doc_uuid)
                .values(status=DocumentStatus.PENDING)
            )
            await session.commit()
    except Exception as exc:
        async with SessionFactory() as session:
            await session.execute(
                update(IngestionJob)
                .where(IngestionJob.id == job)
                .values(status=IngestionJobStatus.FAILED, error=str(exc))
            )
            await session.execute(
                update(Document)
                .where(Document.id == doc_uuid)
                .values(status=DocumentStatus.FAILED)
            )
            await session.commit()
        raise
    else:
        async with SessionFactory() as session:
            await session.execute(
                update(IngestionJob)
                .where(IngestionJob.id == job)
                .values(status=IngestionJobStatus.SUCCEEDED)
            )
            await session.execute(
                update(Document)
                .where(Document.id == doc_uuid)
                .values(status=DocumentStatus.INDEXED)
            )
            await session.commit()


class WorkerSettings:
    functions: ClassVar = [ingest_document]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 600  # large PDFs are slow; 10 min ceiling
