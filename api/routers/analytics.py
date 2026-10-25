"""Read-only analytics endpoints for the dashboard.

All tenant-scoped: eval runs are global (they run against an eval tenant),
query logs and claim stats are the caller's own data only.
"""


from fastapi import APIRouter, Query
from sqlalchemy import func, select

from api.core.deps import CurrentAuth, DbSession
from trust_rag.db.models import Claim, ClaimVerdict, EvalRun, EvalScore, QueryLog

router = APIRouter(tags=["analytics"])

ABSTAIN_THRESHOLD = 0.5  # mirrors trust_rag.verification.verifier


@router.get("/evals/runs")
async def eval_runs(ctx: CurrentAuth, session: DbSession) -> list[dict]:
    """Eval history, newest first — one entry per run with its metric scores."""
    runs = (
        await session.execute(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(50))
    ).scalars()
    result = []
    for run in runs:
        scores = (
            await session.execute(select(EvalScore).where(EvalScore.eval_run_id == run.id))
        ).scalars()
        result.append(
            {
                "id": str(run.id),
                "git_sha": run.git_sha,
                "created_at": run.created_at.isoformat(),
                "config": run.config,
                "scores": {s.metric: s.value for s in scores},
            }
        )
    return result


@router.get("/queries")
async def recent_queries(
    ctx: CurrentAuth, session: DbSession, limit: int = Query(default=50, ge=1, le=200)
) -> list[dict]:
    rows = (
        await session.execute(
            select(QueryLog)
            .where(QueryLog.tenant_id == ctx.tenant_id)
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    return [
        {
            "id": str(q.id),
            "question": q.question,
            "answer": q.answer[:300],
            "confidence": float(q.confidence),
            "abstained": q.confidence < ABSTAIN_THRESHOLD,
            "latency_ms": q.latency_ms,
            "created_at": q.created_at.isoformat(),
        }
        for q in rows
    ]


@router.get("/queries/claim-stats")
async def claim_stats(ctx: CurrentAuth, session: DbSession) -> dict:
    """Verdict distribution across the tenant's query history."""
    counts = (
        await session.execute(
            select(Claim.verdict, func.count())
            .join(QueryLog, QueryLog.id == Claim.query_log_id)
            .where(QueryLog.tenant_id == ctx.tenant_id)
            .group_by(Claim.verdict)
        )
    ).all()
    by_verdict = {getattr(v, "value", str(v)): n for v, n in counts}
    return {
        "verified": by_verdict.get(ClaimVerdict.VERIFIED.value, 0),
        "unsupported": by_verdict.get(ClaimVerdict.UNSUPPORTED.value, 0),
        "contradicted": by_verdict.get(ClaimVerdict.CONTRADICTED.value, 0),
    }
