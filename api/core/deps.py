"""Auth dependencies: resolve the caller to an AuthContext (tenant-scoped).

Two supported credentials, checked in order:
  1. `Authorization: Bearer <jwt>`      — interactive users
  2. `X-API-Key: trg_...`               — programmatic access

Every protected endpoint takes `AuthContext` via Depends(require_auth) and all
downstream queries MUST filter on ctx.tenant_id — this is the tenant-isolation
chokepoint of the whole API.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trust_rag.db.models import ApiKey
from trust_rag.db.session import get_session
from trust_rag.security import decode_access_token, hash_api_key
from trust_rag.settings import get_settings

_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_session)]

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


@dataclass(frozen=True)
class AuthContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    email: str | None


async def require_auth(
    bearer_token: Annotated[str | None, Depends(_oauth2)] = None,
    api_key: Annotated[str | None, Depends(_api_key_header)] = None,
    session: DbSession = None,  # type: ignore[assignment]  (DbSession is a Depends)
) -> AuthContext:
    if bearer_token is None and api_key is None:
        raise _CREDENTIALS_ERROR

    if bearer_token is not None:
        return _auth_from_jwt(bearer_token)
    assert api_key is not None
    return await _auth_from_api_key(session, api_key)


def _auth_from_jwt(token: str) -> AuthContext:
    try:
        claims = decode_access_token(token, get_settings().secret_key)
    except pyjwt.InvalidTokenError:
        raise _CREDENTIALS_ERROR from None
    return AuthContext(tenant_id=claims.tenant_id, user_id=claims.user_id, email=None)


async def _auth_from_api_key(session: AsyncSession, raw_key: str) -> AuthContext:
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw_key), ApiKey.is_active)
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise _CREDENTIALS_ERROR
    return AuthContext(tenant_id=key.tenant_id, user_id=None, email=None)


async def require_user_auth(ctx: Annotated[AuthContext, Depends(require_auth)]) -> AuthContext:
    """Stricter variant: JWT (interactive user) only, not API keys."""
    if ctx.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires user (JWT) authentication",
        )
    return ctx


CurrentAuth = Annotated[AuthContext, Depends(require_auth)]
UserAuth = Annotated[AuthContext, Depends(require_user_auth)]
