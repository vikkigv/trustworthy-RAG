"""Async engine lifecycle.

The engine is created in the app/worker lifespan (not at import time) so its
connection pool binds to a single event loop — creating it at import breaks
under test runners that use a fresh loop per test.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    global _engine, _session_factory
    _engine = create_async_engine(database_url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    assert _session_factory is not None, "init_engine() must be called first"
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    assert _session_factory is not None, "init_engine() must be called first"
    async with _session_factory() as session:
        yield session
