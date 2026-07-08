"""
AI Pulse – Auth API Router
============================
Registration, login, token refresh, logout endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthException, DuplicateError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.database.connection import get_db
from app.models.user import User, UserPreferences
from app.schemas import (
    FCMTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.utils.date_utils import utcnow

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(
    payload: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Create a new user account.
    Returns the created user profile.
    """
    # Check if email is already taken
    existing = await db.execute(
        select(User).where(User.email == payload.email.lower())
    )
    if existing.scalar_one_or_none():
        raise DuplicateError("An account with this email already exists.")

    # Create user
    user = User(
        supabase_id=str(__import__("uuid").uuid4()),  # Placeholder; real apps use Supabase Auth
        email=payload.email.lower(),
        display_name=payload.display_name,
        hashed_password=hash_password(payload.password),
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.flush()

    # Create cold-start preferences from stated signup interests. A future LLM
    # enrichment job can expand these further; the feed engine already expands
    # common AI stack terms semantically before telemetry exists.
    seeded_topics = []
    if payload.job_title:
        seeded_topics.append(payload.job_title)
    seeded_topics.extend(payload.tech_stack or [])
    seeded_topics.extend(payload.onboarding_topics or [])
    prefs = UserPreferences(
        user_id=user.id,
        favorite_topics=list(dict.fromkeys(t for t in seeded_topics if t)),
    )
    db.add(prefs)
    await db.commit()
    await db.refresh(user)

    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and get JWT tokens",
)
async def login(
    payload: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate with email and password.
    Returns access and refresh JWT tokens.

    Note: In production, this delegates to Supabase Auth.
    The returned tokens are Supabase session tokens.
    """
    result = await db.execute(
        select(User).where(
            User.email == payload.email.lower(),
            User.is_active == True,  # noqa: E712
        )
    )
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise AuthException("Invalid email or password.")

    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))

    # Update last seen
    user.last_seen_at = utcnow()
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh an expired access token",
)
async def refresh_token(
    refresh_token: str,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a refresh token for a new access token."""
    payload = decode_token(refresh_token, expected_type="refresh")
    user_id = payload.get("sub")

    if not user_id:
        raise AuthException("Invalid refresh token.")

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()

    if not user:
        raise AuthException("User not found or inactive.")

    new_access = create_access_token(subject=str(user.id))
    new_refresh = create_refresh_token(subject=str(user.id))

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
    )
