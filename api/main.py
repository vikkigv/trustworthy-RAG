from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="TrustRAG",
    description="Trustworthy RAG platform: verified claims, abstention, evals, temporal queries.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
