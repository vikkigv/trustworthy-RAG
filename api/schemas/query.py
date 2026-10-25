import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """One prior turn sent by the client for follow-up rewriting."""
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(default="", max_length=2000)


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)
    # Temporal mode: answer as of this instant (ISO 8601 date/datetime).
    as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}([T ].*)?$")
    # Recent conversation (oldest first) so follow-ups like "what about X?"
    # can be rewritten into standalone questions before retrieval.
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)


class Citation(BaseModel):
    number: int  # the [n] marker in the answer
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    snippet: str  # first ~200 chars of the chunk
    rrf_score: float
    dense_rank: int | None
    sparse_rank: int | None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    is_current: bool = True
