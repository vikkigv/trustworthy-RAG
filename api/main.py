from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from api.routers import auth, documents, health
from trust_rag.db.session import dispose_engine, init_engine
from trust_rag.settings import get_settings
from trust_rag.storage import init_storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_engine(settings.database_url)
    init_storage(settings.data_dir)
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
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
