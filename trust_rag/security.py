"""Security primitives: password hashing, API keys, JWTs.

No FastAPI imports here — these are pure functions used by both the API and
the worker, and unit-testable in isolation.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

API_KEY_PREFIX = "trg_"
JWT_ISSUER = "trust_rag"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(hours=12)


# --- Passwords (bcrypt directly; passlib is unmaintained and breaks on bcrypt 4.x) ---


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


# --- API keys ---


@dataclass(frozen=True)
class GeneratedApiKey:
    raw: str
    key_hash: str
    key_prefix: str


def generate_api_key() -> GeneratedApiKey:
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return GeneratedApiKey(raw=raw, key_hash=hash_api_key(raw), key_prefix=raw[:10])


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# --- JWTs ---


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    expires_at: datetime


def create_access_token(
    user_id: uuid.UUID, tenant_id: uuid.UUID, secret: str, ttl: timedelta = ACCESS_TOKEN_TTL
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "iss": JWT_ISSUER,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, secret: str) -> TokenClaims:
    """Raises jwt.InvalidTokenError (or a subclass) on any failure."""
    payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM], issuer=JWT_ISSUER)
    return TokenClaims(
        user_id=uuid.UUID(payload["sub"]),
        tenant_id=uuid.UUID(payload["tenant_id"]),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )
