"""Temporal RAG tests — version chains and as_of retrieval (mocked embeddings)."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from tests.test_auth import _get_token, _unique
from trust_rag.db.models import Chunk, Document
from trust_rag.ingestion.pipeline import run_ingestion
from trust_rag.retrieval import hybrid_search


def _fake_vec(seed: float, dim: int = 1024) -> list[float]:
    return [seed] + [0.0] * (dim - 1)


def _mock_embeddings(seed_by_content: dict[str, float] | float = 1.0):
    """All chunks get the same direction unless mapped by content prefix."""
    async def fake(texts):
        if isinstance(seed_by_content, dict):
            seeds = [
                next((s for prefix, s in seed_by_content.items() if prefix in t), 1.0)
                for t in texts
            ]
        else:
            seeds = [seed_by_content] * len(texts)
        return [[s] + [0.0] * 1023 for s in seeds]
    return fake


@pytest.fixture()
def token(client) -> str:
    creds = _unique()
    assert client.post("/auth/register", json=creds).status_code == 201
    return _get_token(client, creds)


def _upload(client, token: str, filename: str, content: str) -> str:
    resp = client.post(
        "/documents",
        files={"file": (filename, content.encode(), "text/markdown")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _ingest(session_factory, doc_id: str, seeds=None) -> None:
    with (
        patch(
            "trust_rag.ingestion.pipeline.embed_texts",
            new=_mock_embeddings(seeds if seeds is not None else 1.0),
        ),
        patch(
            "trust_rag.ingestion.pipeline.get_session_factory",
            return_value=session_factory,
        ),
    ):
        await run_ingestion(uuid.UUID(doc_id))


async def _version_chain(client, token, session_factory) -> dict[str, str]:
    """Upload v1, index it, upload v2 (same filename), index it."""
    v1 = _upload(
        client, token, "handbook.md",
        "# Handbook v1\n\nVacation: Employees carry over five (5) vacation days.",
    )
    await _ingest(session_factory, v1, seeds={"Vacation": 1.0})

    mid = datetime.now(UTC)  # v1 current, v2 not yet ingested

    v2 = _upload(
        client, token, "handbook.md",
        "# Handbook v2\n\nVacation: Unused vacation days do not carry over.",
    )
    await _ingest(session_factory, v2, seeds={"Vacation": 2.0})
    return {"v1": v1, "v2": v2, "mid": mid}


class TestVersionChains:
    async def test_v2_supersedes_v1(self, client, token, session_factory) -> None:
        docs = await _version_chain(client, token, session_factory)

        async with session_factory() as session:
            new_doc = (
                await session.execute(select(Document).where(Document.id == uuid.UUID(docs["v2"])))
            ).scalar_one()
            assert new_doc.supersedes_id == uuid.UUID(docs["v1"])

            v1_chunks = (
                await session.execute(
                    select(Chunk).where(Chunk.document_id == uuid.UUID(docs["v1"]))
                )
            ).scalars().all()
            v2_chunks = (
                await session.execute(
                    select(Chunk).where(Chunk.document_id == uuid.UUID(docs["v2"])))
            ).scalars().all()
            assert all(c.valid_to is not None for c in v1_chunks)  # closed
            assert all(c.valid_to is None for c in v2_chunks)  # current

    async def test_different_filename_is_not_a_version(
        self, client, token, session_factory
    ) -> None:
        a = _upload(client, token, "a.md", "policy A content unique alpha")
        await _ingest(session_factory, a)
        b = _upload(client, token, "b.md", "policy B content unique beta")
        await _ingest(session_factory, b)

        async with session_factory() as session:
            doc_b = (
                await session.execute(select(Document).where(Document.id == uuid.UUID(b)))
            ).scalar_one()
            assert doc_b.supersedes_id is None


class TestAsOfRetrieval:
    async def test_current_mode_sees_only_v2(
        self, client, token, session_factory
    ) -> None:
        docs = await _version_chain(client, token, session_factory)

        async with session_factory() as session:
            with patch(
                "trust_rag.retrieval.hybrid.embed_texts",
                new=_mock_embeddings(2.0),  # points at v2's direction
            ):
                results = await hybrid_search(session, uuid.UUID(_tenant_of(client, token)), "vacation")
        assert results
        assert all(str(r.document_id) == docs["v2"] for r in results)

    async def test_as_of_before_cutover_sees_v1(
        self, client, token, session_factory
    ) -> None:
        docs = await _version_chain(client, token, session_factory)

        # Between v1 and v2 ingestion: only v1 was valid then.
        async with session_factory() as session:
            with patch(
                "trust_rag.retrieval.hybrid.embed_texts",
                new=_mock_embeddings(1.0),  # points at v1's direction
            ):
                results = await hybrid_search(
                    session, uuid.UUID(_tenant_of(client, token)), "vacation", as_of=docs["mid"]
                )
        assert results
        assert all(str(r.document_id) == docs["v1"] for r in results)
        assert all(not r.is_current for r in results)

    async def test_as_of_after_cutover_sees_v2(
        self, client, token, session_factory
    ) -> None:
        docs = await _version_chain(client, token, session_factory)

        after = datetime.now(UTC) + timedelta(hours=1)
        async with session_factory() as session:
            with patch(
                "trust_rag.retrieval.hybrid.embed_texts",
                new=_mock_embeddings(2.0),
            ):
                results = await hybrid_search(
                    session, uuid.UUID(_tenant_of(client, token)), "vacation", as_of=after
                )
        assert results
        assert all(str(r.document_id) == docs["v2"] for r in results)


def _tenant_of(client, token: str) -> str:
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return me["tenant_id"]
