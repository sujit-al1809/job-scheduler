"""Auth business logic: registration (with org bootstrap) and authentication."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import hash_password, verify_password
from app.models import OrgMember, Organization, User
from app.models.enums import OrgRole


async def register_user(session: AsyncSession, email: str, password: str) -> User:
    """Create a user plus a personal organization and an owner membership.

    All three rows are created in one unit of work so a user always lands with an
    org they own.
    """
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError(
            "A user with this email already exists.", code="EMAIL_TAKEN"
        )

    user = User(email=email, password_hash=hash_password(password))
    session.add(user)
    await session.flush()  # assign user.id

    org = Organization(name=f"{email}'s org")
    session.add(org)
    await session.flush()  # assign org.id

    session.add(OrgMember(user_id=user.id, org_id=org.id, role=OrgRole.owner))
    await session.flush()
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid email or password.", code="INVALID_CREDENTIALS")
    return user
