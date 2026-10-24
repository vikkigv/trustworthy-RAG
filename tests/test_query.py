"""/query endpoint tests — LLM and embeddings both mocked, no network."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from tests.test_auth import _get_token, _unique
from trust_rag.db.models import Chunk, QueryLog


def _fake_vec(seed: float, dim: int = 1024) -> list[float]:
    return [seed] + [0.0] * (dim - 1)


STREAMED_ANSWER = ["Carry-over ", "is five ", "days [1]."]


async def _aiter(items):
    for item in items:
        yield item


@pytest.fixture()
def token(client) -> str:
    creds = _unique()
    assert client.post("/auth/register", json=creds).status_code == 201
    return _get_token(client, creds)


async def _index_one_chunk(session_factory, client, token: str, content: str) -> None:
    """Upload + manually index a single chunk with a controlled vector."""
    resp = client.post(
        "/documents",
        files={"file": ("kb.md", content.encode(), "text/markdown")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    doc_id, tenant_id = resp.json()["id"], resp.json()["tenant_id"]
    async with session_factory() as session:
        session.add(
            Chunk(
                document_id=uuid.UUID(doc_id),
                tenant_id=uuid.UUID(tenant_id),
                chunk_index=0,
                content=content,
                embedding=_fake_vec(1.0),
                tsv=func.to_tsvector("english", content),
            )
        )
        await session.commit()


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(l.removeprefix("event: ") for l in lines if l.startswith("event: "))
        data = next(l.removeprefix("data: ") for l in lines if l.startswith("data: "))
        events.append((event, json.loads(data)))
    return events


def _mock_pipeline(answer_tokens: list[str]):
    return (
        patch(
            "trust_rag.retrieval.hybrid.embed_texts",
            new=AsyncMock(return_value=[_fake_vec(1.0)]),
        ),
        # astream_answer must return an async generator, not a coroutine —
        # so a plain function, not AsyncMock.
        patch(
            "api.routers.query.astream_answer",
            new=lambda q, c, **kw: _aiter(answer_tokens),
        ),
    )


class TestQueryEndpoint:
    async def test_stream_lifecycle_and_logging(
        self, client, token: str, session_factory
    ) -> None:
        content = "Employees carry over five vacation days to the next year."
        await _index_one_chunk(session_factory, client, token, content)

        embed_patch, llm_patch = _mock_pipeline(STREAMED_ANSWER)
        with embed_patch, llm_patch:
            resp = client.post(
                "/query",
                json={"question": "how many vacation days carry over?"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert kinds[0] == "retrieved" and kinds[-1] == "done"
        assert kinds[1:-1] == ["token"] * len(STREAMED_ANSWER)

        retrieved = events[0][1]
        assert len(retrieved["citations"]) == 1
        assert retrieved["citations"][0]["snippet"].startswith("Employees carry over")

        done = events[-1][1]
        assert done["answer"] == "".join(STREAMED_ANSWER)
        assert done["query_log_id"]

        # QueryLog persisted with retrieval evidence.
        async with session_factory() as session:
            log = (
                await session.execute(
                    select(QueryLog).where(
                        QueryLog.question == "how many vacation days carry over?"
                    )
                )
            ).scalar_one()
            assert log.answer == "".join(STREAMED_ANSWER)
            assert log.retrieved_chunk_ids[0]["chunk_id"]

    async def test_no_context_abstains(self, client, session_factory) -> None:
        # Tenant with no indexed chunks.
        creds = _unique()
        assert client.post("/auth/register", json=creds).status_code == 201
        empty_token = _get_token(client, creds)

        embed_patch, _ = _mock_pipeline([])
        with embed_patch:
            resp = client.post(
                "/query",
                json={"question": "anything at all?"},
                headers={"Authorization": f"Bearer {empty_token}"},
            )
        events = _parse_sse(resp.text)
        assert [e for e, _ in events] == ["retrieved", "done"]
        assert events[0][1]["citations"] == []
        assert "don't have enough information" in events[-1][1]["answer"]

    async def test_query_requires_auth(self, client) -> None:
        assert client.post("/query", json={"question": "hello?"}).status_code == 401
