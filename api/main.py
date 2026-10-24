import asyncio
import logging
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import FastAPI
from sqlalchemy import text

from api.routers import auth, documents, health, query
from trust_rag.db.session import dispose_engine, get_session_factory, init_engine
from trust_rag.settings import get_settings
from trust_rag.storage import init_storage

logger = logging.getLogger(__name__)

STARTUP_RETRIES = 10
STARTUP_RETRY_DELAY = 3  # seconds — services race on cold starts (Docker restarts, ECS)


async def _wait_for_postgres() -> None:
    for attempt in range(1, STARTUP_RETRIES + 1):
        try:
            async with get_session_factory()() as session:
                await session.execute(text("SELECT 1"))
            return
        except Exception:
            logger.info("Postgres not ready (attempt %d/%d)", attempt, STARTUP_RETRIES)
            if attempt == STARTUP_RETRIES:
                raise
            await asyncio.sleep(STARTUP_RETRY_DELAY)


async def _create_arq_pool(redis_settings: RedisSettings) -> ArqRedis:
    for attempt in range(1, STARTUP_RETRIES + 1):
        try:
            return await create_pool(redis_settings)
        except Exception:
            logger.info("Redis not ready (attempt %d/%d)", attempt, STARTUP_RETRIES)
            if attempt == STARTUP_RETRIES:
                raise
            await asyncio.sleep(STARTUP_RETRY_DELAY)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_engine(settings.database_url)
    init_storage(settings.data_dir)
    await _wait_for_postgres()
    app.state.arq = await _create_arq_pool(RedisSettings.from_dsn(settings.redis_url))
    yield
    await app.state.arq.aclose()
    await dispose_engine()


app = FastAPI(
    title="TrustRAG",
    description="Trustworthy RAG platform: verified claims, abstention, evals, temporal queries.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(query.router)
