import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)
    # Temporal mode: answer as of this instant (ISO 8601 date/datetime).
    as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}([T ].*)?$")


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
