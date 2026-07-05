"""
AI Pulse – Auth Dependencies
==============================
FastAPI dependencies for JWT authentication and user resolution.
"""

from __future__ import annotations

import uuid

from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthException
from app.core.security import decode_token
from app.database.connection import get_db
from app.models.user import User

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Resolves the current user by decoding the JWT access token and
    fetching the matching user record from the database.
    """
    if not credentials or not credentials.credentials:
        raise AuthException("Missing or invalid authorization credentials.")

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise AuthException("Invalid authorization token payload.")
        user_id = uuid.UUID(user_id_str)
    except Exception as e:
        raise AuthException(f"Token verification failed: {str(e)}")

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()

    if not user:
        raise AuthException("Authenticated user not found or inactive.")

    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require the current user to be an admin (is_admin = True)."""
    if not getattr(current_user, "is_admin", False):
        raise AuthException("Admin privileges required.")
    return current_user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """
    Returns the user if a valid authentication token is provided,
    otherwise returns None without raising an error.
    """
    if not credentials or not credentials.credentials:
        return None

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        user_id_str = payload.get("sub")
        if not user_id_str:
            return None
        user_id = uuid.UUID(user_id_str)
        
        result = await db.execute(
            select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
        )
        return result.scalar_one_or_none()
    except Exception:
        return None
