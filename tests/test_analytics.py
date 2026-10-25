"""Analytics endpoint tests — real DB, data seeded directly."""

import uuid

from tests.test_auth import _get_token, _unique
from trust_rag.db.models import Claim, ClaimVerdict, QueryLog


async def _seed_query_log(session_factory, tenant_id: str, confidence: float) -> str:
    async with session_factory() as session:
        log = QueryLog(
            tenant_id=uuid.UUID(tenant_id),
            question=f"q-{uuid.uuid4().hex[:6]}",
            answer="some answer",
            confidence=confidence,
            latency_ms=123,
        )
        session.add(log)
        await session.flush()
        session.add(
            Claim(
                query_log_id=log.id,
                text="a claim",
                verdict=(
                    ClaimVerdict.VERIFIED if confidence >= 0.5 else ClaimVerdict.UNSUPPORTED
                ),
                supporting_chunk_ids=[],
            )
        )
        await session.commit()
        return str(log.id)


class TestAnalytics:
    async def test_queries_tenant_scoped(self, client, session_factory) -> None:
        creds_a, creds_b = _unique(), _unique()
        for creds in (creds_a, creds_b):
            assert client.post("/auth/register", json=creds).status_code == 201
        token_a = _get_token(client, creds_a)
        token_b = _get_token(client, creds_b)

        # tenant A's id via /auth/me
        me_a = client.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"}).json()
        await _seed_query_log(session_factory, me_a["tenant_id"], 0.9)

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}
        queries_a = client.get("/queries", headers=headers_a).json()
        queries_b = client.get("/queries", headers=headers_b).json()
        assert len(queries_a) == 1 and len(queries_b) == 0
        assert queries_a[0]["confidence"] == 0.9
        assert queries_a[0]["abstained"] is False

        stats_a = client.get("/queries/claim-stats", headers=headers_a).json()
        assert stats_a == {"verified": 1, "unsupported": 0, "contradicted": 0}

    async def test_eval_runs_listed(self, client, session_factory) -> None:
        creds = _unique()
        assert client.post("/auth/register", json=creds).status_code == 201
        token = _get_token(client, creds)

        from trust_rag.db.models import EvalRun, EvalScore

        async with session_factory() as session:
            run = EvalRun(git_sha="test123", config={"top_k": 6})
            session.add(run)
            await session.flush()
            session.add(EvalScore(eval_run_id=run.id, metric="answer_success_rate", value=1.0))
            await session.commit()

        runs = client.get(
            "/evals/runs", headers={"Authorization": f"Bearer {token}"}
        ).json()
        assert any(
            r["git_sha"] == "test123" and r["scores"].get("answer_success_rate") == 1.0
            for r in runs
        )

    async def test_requires_auth(self, client) -> None:
        assert client.get("/queries").status_code == 401
        assert client.get("/evals/runs").status_code == 401
