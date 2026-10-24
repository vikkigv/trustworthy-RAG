"""Pipeline integration tests — embeddings mocked (no network, no API key)."""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.test_auth import _get_token, _unique
from trust_rag.db.models import Chunk, Document, DocumentStatus
from trust_rag.ingestion.parsers import UnsupportedDocumentType
from trust_rag.ingestion.pipeline import run_ingestion
from trust_rag.settings import get_settings
from trust_rag.storage import get_storage


def _fake_embedding(text: str) -> list[float]:
    """Deterministic vector matching the column's 1536 dimensions."""
    base = [float(len(text) % 7), 1.0, 0.5]
    return base + [0.0] * (1024 - len(base))


@pytest.fixture()
def token(client) -> str:
    creds = _unique()
    resp = client.post("/auth/register", json=creds)
    assert resp.status_code == 201, resp.text
    return _get_token(client, creds)


@pytest.fixture()
async def session_factory() -> async_sessionmaker:
    """Session factory bound to the test's event loop.

    The app lifespan engine belongs to the TestClient's loop and asyncpg
    connections can't cross loops, so async tests use their own engine.
    """
    engine = create_async_engine(get_settings().database_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@asynccontextmanager
async def pipeline_sessions(factory: async_sessionmaker) -> async_sessionmaker:
    """Patch a loop-local factory into the pipeline under test."""
    with patch("trust_rag.ingestion.pipeline.get_session_factory", return_value=factory):
        yield factory


def _mock_embeddings() -> AsyncMock:
    return AsyncMock(side_effect=lambda texts: [_fake_embedding(t) for t in texts])


def _upload(client, token: str) -> str:
    resp = client.post(
        "/documents",
        files={
            "file": (
                "handbook.md",
                b"# Handbook\n\nVacation policy: carry over five days.\n\n"
                b"Sick leave requires a doctor's note after three days.\n\n" * 30,
                "text/markdown",
            )
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestPipeline:
    async def test_ingestion_creates_indexed_chunks(
        self, client, token: str, session_factory
    ) -> None:
        doc_id = _upload(client, token)
        async with pipeline_sessions(session_factory):
            with patch("trust_rag.ingestion.pipeline.embed_texts", new=_mock_embeddings()):
                written = await run_ingestion(uuid.UUID(doc_id))
        assert written > 0

        async with session_factory() as session:
            doc = (
                await session.execute(select(Document).where(Document.id == uuid.UUID(doc_id)))
            ).scalar_one()
            assert doc.status == DocumentStatus.PENDING  # worker flips to INDEXED

            chunks = (
                await session.execute(
                    select(Chunk)
                    .where(Chunk.document_id == uuid.UUID(doc_id))
                    .order_by(Chunk.chunk_index)
                )
            ).scalars().all()
            assert len(chunks) == written
            first = chunks[0]
            assert first.embedding is not None and len(first.embedding) == 1024
            assert first.tsv is not None  # BM25 column populated
            assert first.tenant_id == doc.tenant_id  # denormalized for SQL-level isolation

    async def test_reingestion_is_idempotent(
        self, client, token: str, session_factory
    ) -> None:
        doc_id = _upload(client, token)
        async with pipeline_sessions(session_factory):
            with patch("trust_rag.ingestion.pipeline.embed_texts", new=_mock_embeddings()):
                first = await run_ingestion(uuid.UUID(doc_id))
                second = await run_ingestion(uuid.UUID(doc_id))
        assert first == second  # same chunk count, not doubled

        async with session_factory() as session:
            total = (
                await session.execute(
                    select(func.count())
                    .select_from(Chunk)
                    .where(Chunk.document_id == uuid.UUID(doc_id))
                )
            ).scalar_one()
            assert total == second

    async def test_bad_mime_raises(self, client, token: str, session_factory) -> None:
        async with session_factory() as session:
            tenant_id = (
                await session.execute(select(Document.tenant_id).limit(1))
            ).scalar_one()
            doc = Document(
                tenant_id=tenant_id,
                filename="x.bin",
                mime_type="application/x-unknown",
                checksum=uuid.uuid4().hex,
            )
            session.add(doc)
            await session.commit()
            await get_storage().save(tenant_id, doc.id, b"binary junk")
            bad_id = doc.id

        async with pipeline_sessions(session_factory):
            with pytest.raises(UnsupportedDocumentType):
                await run_ingestion(bad_id)


def test_worker_module_imports() -> None:
    """Smoke: worker-side import errors must fail CI (regression guard)."""
    from trust_rag import worker

    assert "ingest_document" in [f.__name__ for f in worker.WorkerSettings.functions]
