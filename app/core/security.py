"""Password hashing and JWT encode/decode."""
from __future__ import annotations

import datetime as dt
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.errors import UnauthorizedError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(
    subject: str, extra_claims: dict[str, Any] | None = None
) -> str:
    now = dt.datetime.now(tz=dt.timezone.utc)
    expire = now + dt.timedelta(minutes=settings.access_token_ttl_min)
    claims: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token.", code="INVALID_TOKEN") from exc
