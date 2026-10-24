"""Test bootstrap: point the app at a throwaway database and migrate it.

Tests are integration tests — they need the dockerized Postgres from
docker-compose.yml. They are skipped automatically if it isn't reachable.
"""

import asyncio
import os
import tempfile

import asyncpg
import pytest

TEST_DB = "trust_rag_test"

# Must happen before any trust_rag import reads settings.
os.environ["POSTGRES_DB"] = TEST_DB
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="trust_rag_test_data_")


def _postgres_reachable() -> bool:
    try:

        async def check() -> bool:
            conn = await asyncpg.connect(
                host=os.environ.get("POSTGRES_HOST", "localhost"),
                port=int(os.environ.get("POSTGRES_PORT", "5432")),
                user=os.environ.get("POSTGRES_USER", "trust_rag"),
                password=os.environ.get("POSTGRES_PASSWORD", "trust_rag_dev"),
                database="postgres",
                timeout=2,
            )
            await conn.close()
            return True

        return asyncio.run(check())
    except OSError:
        return False


def _ensure_test_db() -> None:
    async def create() -> None:
        conn = await asyncpg.connect(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            user=os.environ.get("POSTGRES_USER", "trust_rag"),
            password=os.environ.get("POSTGRES_PASSWORD", "trust_rag_dev"),
            database="postgres",
        )
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
        await conn.close()

    asyncio.run(create())


def _redis_reachable() -> bool:
    try:

        async def check() -> bool:
            import redis.asyncio as aioredis

            r = aioredis.Redis(
                host=os.environ.get("REDIS_HOST", "localhost"),
                port=int(os.environ.get("REDIS_PORT", "6379")),
                socket_connect_timeout=2,
            )
            await r.ping()
            await r.aclose()
            return True

        return asyncio.run(check())
    except OSError:
        return False


if _postgres_reachable() and _redis_reachable():
    _ensure_test_db()
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    HAS_DB = True
else:
    HAS_DB = False


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    if not HAS_DB:
        skip = pytest.mark.skip(reason="Postgres/Redis not reachable")
        for item in items:
            if "/tests/" in str(item.fspath):
                item.add_marker(skip)


@pytest.fixture()
def client():
    """TestClient entered as a context manager so the app lifespan runs
    (engine created and disposed per test — safe across event loops)."""
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
async def session_factory():
    """Session factory bound to the *test's* event loop.

    The app lifespan engine belongs to the TestClient's loop and asyncpg
    connections can't cross loops, so async tests use their own engine.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from trust_rag.settings import get_settings

    engine = create_async_engine(get_settings().database_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
