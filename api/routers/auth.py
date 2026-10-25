from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.core.deps import CurrentAuth, DbSession, UserAuth
from api.schemas.auth import (
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyResponse,
    MeResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from trust_rag.db.models import ApiKey, Tenant, User
from trust_rag.security import create_access_token, generate_api_key, hash_password, verify_password
from trust_rag.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: DbSession) -> User:
    """Create a new tenant with its first (owner) user."""
    tenant = Tenant(name=body.tenant_name)
    user = User(
        tenant=tenant,
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    session.add_all([tenant, user])
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant name or email already registered",
        ) from None
    await session.refresh(user)
    return user


@router.post("/token", response_model=TokenResponse)
async def token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: DbSession,
) -> TokenResponse:
    result = await session.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(
        form.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    access_token = create_access_token(user.id, user.tenant_id, get_settings().secret_key)
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=MeResponse)
async def me(ctx: CurrentAuth) -> MeResponse:
    return MeResponse(tenant_id=ctx.tenant_id, user_id=ctx.user_id, email=ctx.email)


@router.post(
    "/api-keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED
)
async def create_api_key(body: ApiKeyCreateRequest, ctx: UserAuth, session: DbSession) -> ApiKeyCreatedResponse:
    """Create an API key for the caller's tenant. The raw key is shown once."""
    generated = generate_api_key()
    key = ApiKey(
        tenant_id=ctx.tenant_id,
        name=body.name,
        key_hash=generated.key_hash,
        key_prefix=generated.key_prefix,
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return ApiKeyCreatedResponse(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        created_at=key.created_at,
        raw_key=generated.raw,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(ctx: UserAuth, session: DbSession) -> list[ApiKey]:
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.tenant_id == ctx.tenant_id, ApiKey.is_active)
        .order_by(ApiKey.created_at)
    )
    return list(result.scalars())


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: UUID, ctx: UserAuth, session: DbSession) -> None:
    """Revoke (soft-delete) one of the tenant's API keys."""
    key = await session.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.tenant_id == ctx.tenant_id,
            ApiKey.is_active,
        )
    )
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key not found")
    key.is_active = False
    await session.commit()
