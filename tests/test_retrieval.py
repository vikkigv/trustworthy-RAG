"""Hybrid retrieval tests — deterministic vectors, embed_texts mocked."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func

from tests.test_auth import _get_token, _unique
from trust_rag.db.models import Chunk, Document, DocumentStatus
from trust_rag.retrieval import hybrid_search


def _vec(seed: float, dim: int = 1024) -> list[float]:
    """Distinct unit-ish vectors; seed controls direction."""
    return [seed] + [0.0] * (dim - 1)


@pytest.fixture()
def tenant_docs(client) -> list[dict[str, str]]:
    """Two tenants, each with one uploaded (unprocessed) document."""
    docs = []
    for i in range(2):
        creds = _unique()
        assert client.post("/auth/register", json=creds).status_code == 201
        token = _get_token(client, creds)
        resp = client.post(
            "/documents",
            files={
                "file": (
                    f"doc{i}.md",
                    f"filler about topic{i} unrelated filler text. ".encode() * 20,
                    "text/markdown",
                )
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.text
        docs.append({"document_id": resp.json()["id"], "tenant_id": resp.json()["tenant_id"]})
    return docs


async def _seed_chunks(session_factory, doc: dict[str, str], contents: list[str], seed: float) -> None:
    """Insert chunks directly with controlled vectors (bypasses the pipeline)."""
    async with session_factory() as session:
        for i, content in enumerate(contents):
            session.add(
                Chunk(
                    document_id=uuid.UUID(doc["document_id"]),
                    tenant_id=uuid.UUID(doc["tenant_id"]),
                    chunk_index=i,
                    content=content,
                    embedding=_vec(seed),
                    tsv=func.to_tsvector("english", content),
                )
            )
        await session.execute(
            Document.__table__.update()
            .where(Document.id == uuid.UUID(doc["document_id"]))
            .values(status=DocumentStatus.INDEXED)
        )
        await session.commit()


def _mock_query_embedding(seed: float):
    return patch(
        "trust_rag.retrieval.hybrid.embed_texts",
        new=AsyncMock(return_value=[_vec(seed)]),
    )


class TestHybridSearch:
    async def test_dense_leg_finds_semantic_match(self, client, tenant_docs, session_factory) -> None:
        doc, other = tenant_docs
        await _seed_chunks(session_factory, doc, ["alpha content"], seed=1.0)
        await _seed_chunks(session_factory, other, ["beta content"], seed=2.0)

        async with session_factory() as session:
            with _mock_query_embedding(1.0):  # same direction as tenant-1 chunk
                results = await hybrid_search(
                    session, uuid.UUID(doc["tenant_id"]), "find alpha", top_k=5
                )
        assert len(results) == 1
        assert "alpha content" in results[0].content
        assert results[0].dense_rank == 1
        # "find alpha" doesn't match the filler tsquery — sparse leg missed it
        assert results[0].sparse_rank is None

    async def test_sparse_leg_finds_keyword_match(self, client, tenant_docs, session_factory) -> None:
        doc, _ = tenant_docs
        await _seed_chunks(
            session_factory, doc, ["The sabbatical policy allows unpaid leave up to 12 months."], seed=3.0
        )
        async with session_factory() as session:
            with _mock_query_embedding(9.0):  # query vector points nowhere near
                results = await hybrid_search(
                    session, uuid.UUID(doc["tenant_id"]), "sabbatical policy", top_k=5
                )
        assert len(results) == 1
        assert results[0].sparse_rank == 1

    async def test_both_legs_hit_ranks_highest(self, client, tenant_docs, session_factory) -> None:
        doc, _ = tenant_docs
        await _seed_chunks(
            session_factory, doc,
            [
                "The sabbatical policy allows unpaid leave up to 12 months.",  # both legs
                "Unrelated filler about gardening tools and compost.",  # dense-ish only
            ],
            seed=5.0,
        )
        async with session_factory() as session:
            with _mock_query_embedding(5.0):  # same direction as both chunks
                results = await hybrid_search(
                    session, uuid.UUID(doc["tenant_id"]), "sabbatical policy", top_k=5
                )
        assert len(results) == 2
        assert results[0].from_both_legs
        assert "sabbatical" in results[0].content

    async def test_tenant_isolation_in_sql(self, client, tenant_docs, session_factory) -> None:
        doc_a, doc_b = tenant_docs
        await _seed_chunks(session_factory, doc_a, ["shared keyword xylophone"], seed=1.0)
        await _seed_chunks(session_factory, doc_b, ["shared keyword xylophone"], seed=1.0)

        async with session_factory() as session:
            with _mock_query_embedding(1.0):
                results_a = await hybrid_search(
                    session, uuid.UUID(doc_a["tenant_id"]), "xylophone", top_k=10
                )
                results_b = await hybrid_search(
                    session, uuid.UUID(doc_b["tenant_id"]), "xylophone", top_k=10
                )
        # Each tenant sees exactly one chunk — their own.
        assert len(results_a) == 1 and len(results_b) == 1
        assert results_a[0].id != results_b[0].id

    async def test_empty_index_returns_nothing(self, client, tenant_docs, session_factory) -> None:
        doc, _ = tenant_docs  # uploaded but never chunked
        async with session_factory() as session:
            with _mock_query_embedding(1.0):
                results = await hybrid_search(
                    session, uuid.UUID(doc["tenant_id"]), "anything", top_k=5
                )
        assert results == []
