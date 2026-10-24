from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers import auth, health
from trust_rag.db.session import dispose_engine, init_engine
from trust_rag.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_engine(get_settings().database_url)
    yield
    await dispose_engine()


app = FastAPI(
    title="TrustRAG",
    description="Trustworthy RAG platform: verified claims, abstention, evals, temporal queries.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(auth.router)
