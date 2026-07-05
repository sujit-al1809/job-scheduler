"""Auth routes: register, login, and the current-user probe."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_session
from app.core.security import create_access_token
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserResponse,
)
from app.services.auth import authenticate, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_for(user: User) -> str:
    return create_access_token(subject=str(user.id))


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterResponse,
    summary="Register a new user (bootstraps a personal org + owner membership)",
)
async def register(
    body: RegisterRequest, session: AsyncSession = Depends(get_session)
) -> RegisterResponse:
    user = await register_user(session, body.email, body.password)
    return RegisterResponse(
        user=UserResponse.model_validate(user), access_token=_token_for(user)
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange credentials for a JWT access token",
)
async def login(
    body: LoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    user = await authenticate(session, body.email, body.password)
    return TokenResponse(access_token=_token_for(user))


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Return the authenticated user",
)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)
