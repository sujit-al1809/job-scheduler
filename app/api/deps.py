"""Shared FastAPI dependencies (auth, db session)."""
from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import UnauthorizedError
from app.core.security import decode_access_token
from app.models import User

# auto_error=False so a missing token flows through our envelope, not FastAPI's.
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Authentication required.", code="NOT_AUTHENTICATED")

    payload = decode_access_token(credentials.credentials)
    subject = payload.get("sub")
    if subject is None:
        raise UnauthorizedError("Malformed token.", code="INVALID_TOKEN")

    user = await session.get(User, int(subject))
    if user is None:
        raise UnauthorizedError("User no longer exists.", code="INVALID_TOKEN")
    return user
