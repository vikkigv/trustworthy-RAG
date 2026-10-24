import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    mime_type: str
    checksum: str
    status: str
    supersedes_id: uuid.UUID | None
    created_at: datetime


class DocumentDetailResponse(DocumentResponse):
    chunk_count: int
    last_ingestion_error: str | None
