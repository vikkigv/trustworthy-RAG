"""Observability seam — Langfuse tracing with a null-object fallback.

Every pipeline stage in the query path reports through these helpers. When
tracing is disabled (default), the null objects make the calls no-ops, so
business code never branches on observability.
"""

import logging
from typing import Any

from trust_rag.settings import get_settings

logger = logging.getLogger(__name__)

_client: Any = None  # Langfuse | None


class NullSpan:
    def end(self, output: Any = None) -> None:
        pass


class NullTrace:
    def span(self, name: str, input: Any = None) -> NullSpan:
        return NullSpan()

    def generation(self, name: str, input: Any = None, model: str | None = None) -> NullSpan:
        return NullSpan()

    def update(self, output: Any = None, metadata: Any = None) -> None:
        pass


def start_trace(name: str, input: Any = None, user_id: str | None = None) -> Any:
    """Begin a trace. Returns a Langfuse Trace or a no-op NullTrace."""
    global _client
    settings = get_settings()
    if not settings.langfuse_enabled:
        return NullTrace()
    if _client is None:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    try:
        return _client.trace(name=name, input=input, user_id=user_id)
    except Exception:  # noqa: BLE001 — tracing must never break the query path
        logger.warning("Langfuse tracing failed to start; continuing untraced")
        return NullTrace()


def flush() -> None:
    if _client is not None:
        try:
            _client.flush()
        except Exception:  # noqa: BLE001 — best-effort flush
            logger.warning("Langfuse flush failed")
