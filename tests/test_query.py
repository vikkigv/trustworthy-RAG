"""/query endpoint tests — LLM and embeddings both mocked, no network."""

import json
import uuid
from unittest.mock import AsyncMock, patch


def _q(text: str) -> str:
    """Unique question per run — the test DB persists across runs."""
    return f"{text} ({uuid.uuid4().hex[:6]})"

import pytest
from sqlalchemy import func, select

from tests.test_auth import _get_token, _unique
from trust_rag.db.models import Chunk, QueryLog


def _fake_vec(seed: float, dim: int = 1024) -> list[float]:
    return [seed] + [0.0] * (dim - 1)


STREAMED_ANSWER = ["Carry-over ", "is five ", "days [1]."]
QUESTION = _q("how many vacation days carry over?")


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


def _verified_result():
    from trust_rag.verification.verifier import (
        VERIFIED,
        ClaimVerdict,
        VerificationResult,
    )
    return VerificationResult(
        claims=[ClaimVerdict("Carry-over is five days.", VERIFIED, ["x"])],
        confidence=0.9,
        abstain=False,
        reason=None,
    )


def _mock_pipeline(answer_tokens: list[str], verification=None):

    verification = verification or _verified_result()
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
        patch(
            "api.routers.query.verify_answer",
            new=AsyncMock(return_value=verification),
        ),
    )


class TestQueryEndpoint:
    async def test_stream_lifecycle_and_logging(
        self, client, token: str, session_factory
    ) -> None:
        content = "Employees carry over five vacation days to the next year."
        await _index_one_chunk(session_factory, client, token, content)

        embed_patch, llm_patch, verify_patch = _mock_pipeline(STREAMED_ANSWER)
        with embed_patch, llm_patch, verify_patch:
            resp = client.post(
                "/query",
                json={"question": QUESTION},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        kinds = [e for e, _ in events]
        assert kinds[0] == "retrieved" and kinds[-1] == "done"
        assert kinds[1:-2] == ["token"] * len(STREAMED_ANSWER)
        assert kinds[-2] == "claims"

        retrieved = events[0][1]
        assert len(retrieved["citations"]) == 1
        assert retrieved["citations"][0]["snippet"].startswith("Employees carry over")

        claims_event = events[-2][1]
        assert events[-2][0] == "claims"
        assert claims_event["claims"][0]["verdict"] == "verified"
        assert claims_event["abstain"] is False

        done = events[-1][1]
        assert done["answer"] == "".join(STREAMED_ANSWER)
        assert done["query_log_id"]
        assert done["confidence"] == 0.9
        assert done["abstain"] is False

        # QueryLog persisted with retrieval evidence.
        async with session_factory() as session:
            log = (
                await session.execute(
                    select(QueryLog).where(QueryLog.question == QUESTION)
                )
            ).scalar_one()
            assert log.answer == "".join(STREAMED_ANSWER)
            assert log.retrieved_chunk_ids[0]["chunk_id"]

    async def test_no_context_abstains(self, client, session_factory) -> None:
        # Tenant with no indexed chunks.
        creds = _unique()
        assert client.post("/auth/register", json=creds).status_code == 201
        empty_token = _get_token(client, creds)

        embed_patch, _, verify_patch = _mock_pipeline([])
        with embed_patch, verify_patch:
            resp = client.post(
                "/query",
                json={"question": _q("anything at all")},
                headers={"Authorization": f"Bearer {empty_token}"},
            )
        events = _parse_sse(resp.text)
        assert [e for e, _ in events] == ["retrieved", "done"]
        assert events[0][1]["citations"] == []
        assert "don't have enough information" in events[-1][1]["answer"]

    async def test_low_confidence_abstains(self, client, token, session_factory) -> None:
        from trust_rag.verification.verifier import (
            UNSUPPORTED,
            ClaimVerdict,
            VerificationResult,
        )
        await _index_one_chunk(
            session_factory, client, token, "Unrelated content about parking spots."
        )
        weak = VerificationResult(
            claims=[ClaimVerdict("Five days carry over.", UNSUPPORTED, [])],
            confidence=0.1,
            abstain=True,
            reason="1 of 1 claims are not supported by the retrieved documents.",
        )
        question = _q("how many vacation days carry over")
        embed_patch, llm_patch, verify_patch = _mock_pipeline(["Five days carry over. [1]"], weak)
        with embed_patch, llm_patch, verify_patch:
            resp = client.post(
                "/query", json={"question": question},
                headers={"Authorization": f"Bearer {token}"},
            )
        events = _parse_sse(resp.text)
        claims_event = events[-2][1]
        assert claims_event["abstain"] is True
        assert claims_event["claims"][0]["verdict"] == "unsupported"

        done = events[-1][1]
        assert done["abstain"] is True
        assert done["confidence"] == 0.1
        assert "don't have enough confidence" in done["answer"]

        async with session_factory() as session:
            log = (await session.execute(
                select(QueryLog).where(QueryLog.question == question))).scalar_one()
            assert log.confidence == 0.1
            assert "don't have enough confidence" in log.answer

    async def test_query_requires_auth(self, client) -> None:
        assert client.post("/query", json={"question": "hello?"}).status_code == 401
