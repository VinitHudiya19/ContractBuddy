"""
Password hashing (bcrypt) and JWT creation/verification.

Access tokens last 15 minutes and carry a random `jti`. Logout puts that `jti`
in Redis until the token would have expired anyway, which is how logout works
on an otherwise stateless token.

Refresh tokens are just random strings. Only their SHA-256 hash is stored, and
each one is replaced on use, so a stolen refresh token works at most once.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import InvalidTokenError

# bcrypt with an explicit, strong cost factor (spec asks for 12+).
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(plain: str) -> str:
    # bcrypt only considers the first 72 bytes; guard longer inputs explicitly.
    return pwd_context.hash(plain[:72])


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain[:72], hashed)
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Access tokens (JWT)
# --------------------------------------------------------------------------- #
def create_access_token(
    *, user_id: str, expires_minutes: int | None = None
) -> tuple[str, str, datetime]:
    """
    Returns (token, jti, expires_at). The `jti` lets us blacklist on logout.
    """
    now = datetime.now(UTC)
    expire = now + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    jti = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti, expire


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + validate an access token. Raises InvalidTokenError on any issue."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise InvalidTokenError() from exc

    if payload.get("type") != "access":
        raise InvalidTokenError("Wrong token type.")
    if "sub" not in payload or "jti" not in payload:
        raise InvalidTokenError("Malformed token.")
    return payload


# --------------------------------------------------------------------------- #
# Refresh tokens (opaque, hashed at rest)
# --------------------------------------------------------------------------- #
def generate_refresh_token() -> str:
    """A high-entropy opaque token. The raw value is returned to the client once."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    """Hash used for storage and lookup. The raw token is never stored."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
