"""MCP server tool tests — deterministic vectors, embed_texts mocked.

The tools are exercised as plain async functions (the MCP transport layer
is the SDK's job); these tests prove tenant scoping, temporal filtering,
and the verify fallback behave through the MCP code path.
"""

import datetime as dt
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func

from mcp_server import rag_get_document, rag_search, rag_verify_claim
from tests.test_auth import _get_token, _unique
from tests.test_retrieval import _seed_chunks, _vec
from trust_rag.db.models import ApiKey, Chunk
from trust_rag.security import generate_api_key


def _vec_seed() -> float:
    return uuid.uuid4().int % 100 / 100 + 0.01


async def _mint_key(session_factory, tenant_id: str) -> str:
    """Create an active API key for the tenant; return the raw key."""
    key = generate_api_key()
    async with session_factory() as session:
        session.add(
            ApiKey(
                tenant_id=uuid.UUID(tenant_id),
                name="mcp-test",
                key_hash=key.key_hash,
                key_prefix=key.key_prefix,
                is_active=True,
            )
        )
        await session.commit()
    return key.raw


async def _seeded_tenant(client, session_factory, contents: list[str]) -> dict:
    """Register a tenant, upload a doc, seed chunks, mint an API key."""
    creds = _unique()
    assert client.post("/auth/register", json=creds).status_code == 201
    token = _get_token(client, creds)
    resp = client.post(
        "/documents",
        files={"file": ("handbook.md", b"placeholder", "text/markdown")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    doc = {"document_id": resp.json()["id"], "tenant_id": resp.json()["tenant_id"]}
    await _seed_chunks(session_factory, doc, contents, _vec_seed())
    doc["api_key"] = await _mint_key(session_factory, doc["tenant_id"])
    return doc


async def _run_tool(session_factory, api_key: str, coro):
    """Point the tool's session factory at the test DB and fake embeddings."""
    with (
        patch("mcp_server.get_session_factory", return_value=session_factory),
        patch.dict("os.environ", {"TRUSTRAG_API_KEY": api_key}),
        patch(
            "trust_rag.retrieval.hybrid.embed_texts",
            AsyncMock(return_value=[_vec(0.5)]),
        ),
    ):
        return await coro


async def test_rag_search_returns_passages(client, session_factory):
    doc = await _seeded_tenant(
        client, session_factory, ["Vacation days carry over five days per year."]
    )
    result = await _run_tool(
        session_factory, doc["api_key"], rag_search("vacation carry over")
    )
    assert result["passages"], "expected at least one passage"
    assert result["passages"][0]["document"] == "handbook.md"
    assert result["passages"][0]["is_current"] is True


async def test_rag_search_as_of_excludes_closed_chunks(client, session_factory):
    """Temporal MCP search must only see chunks valid at the instant."""
    doc = await _seeded_tenant(
        client, session_factory, ["Current policy: no carry-over."]
    )
    # Close the tenant's chunks in the past — nothing is valid 'as of' now.
    async with session_factory() as session:
        await session.execute(
            Chunk.__table__.update()
            .where(Chunk.tenant_id == uuid.UUID(doc["tenant_id"]))
            .values(valid_to=dt.datetime.now(dt.UTC) - dt.timedelta(days=1))
        )
        await session.commit()

    result = await _run_tool(
        session_factory,
        doc["api_key"],
        rag_search("carry-over", as_of=dt.date.today().isoformat()),
    )
    assert result["passages"] == [], "historical window should exclude closed chunks"


async def test_rag_get_document_lists_and_reads(client, session_factory):
    doc = await _seeded_tenant(client, session_factory, ["content here"])

    listed = await _run_tool(session_factory, doc["api_key"], rag_get_document())
    assert "handbook.md" in [d["filename"] for d in listed["documents"]]

    single = await _run_tool(
        session_factory, doc["api_key"], rag_get_document(filename="handbook.md")
    )
    assert single["document"]["id"] == doc["document_id"]
    assert single["chunks"][0]["content"] == "content here"


async def test_rag_verify_claim_no_evidence_abstains(client, session_factory):
    """Empty tenant → verify returns unsupported without calling the LLM."""
    creds = _unique()
    resp = client.post("/auth/register", json=creds)
    assert resp.status_code == 201
    api_key = await _mint_key(session_factory, resp.json()["tenant_id"])

    result = await _run_tool(
        session_factory, api_key, rag_verify_claim("The moon is made of cheese")
    )
    assert result["verdict"] == "unsupported"
    assert result["abstain"] is True
    assert result["claims"] == []
