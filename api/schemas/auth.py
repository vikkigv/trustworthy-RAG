import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: EmailStr
    created_at: datetime


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned once at creation — the only time the raw key is visible."""

    raw_key: str


class MeResponse(BaseModel):
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None  # None when authenticated via API key
    email: str | None
