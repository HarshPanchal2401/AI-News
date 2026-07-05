"""
AI Pulse – Security Utilities
===============================
JWT creation, verification, and Supabase token validation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import InvalidTokenError, TokenExpiredError
from app.core.logging import get_logger

logger = get_logger(__name__)

import bcrypt

# Token type constants
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"

# Default token lifetimes
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


# ── Password Utilities ────────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    pwd_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    pwd_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(pwd_bytes, hashed_bytes)


# ── JWT Utilities ─────────────────────────────────────────────────────────────

def create_access_token(
    subject: str,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject: The token subject (user_id).
        extra_claims: Additional claims to include in the token.
        expires_delta: Custom expiry duration.

    Returns:
        Encoded JWT string.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": ACCESS_TOKEN_TYPE,
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_refresh_token(subject: str) -> str:
    """Create a signed JWT refresh token with a longer lifetime."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": REFRESH_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str, expected_type: str = ACCESS_TOKEN_TYPE) -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Args:
        token: The encoded JWT string.
        expected_type: Expected token type ('access' or 'refresh').

    Returns:
        The decoded token payload.

    Raises:
        TokenExpiredError: If the token has expired.
        InvalidTokenError: If the token is malformed or invalid.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except JWTError as exc:
        logger.warning("JWT decode failed", error=str(exc))
        raise InvalidTokenError()

    token_type = payload.get("type")
    if token_type != expected_type:
        raise InvalidTokenError(
            f"Expected token type '{expected_type}', got '{token_type}'."
        )

    return payload


def decode_supabase_token(token: str) -> dict[str, Any]:
    """
    Decode a Supabase-issued JWT token using the project's JWT secret.

    Args:
        token: Supabase JWT string from the Authorization header.

    Returns:
        Decoded payload with user information.

    Raises:
        InvalidTokenError: If token is invalid.
        TokenExpiredError: If token has expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except JWTError as exc:
        logger.warning("Supabase JWT decode failed", error=str(exc))
        raise InvalidTokenError()


def extract_user_id_from_token(token: str) -> str:
    """
    Extract the user ID (subject) from a JWT token.

    Args:
        token: JWT token string.

    Returns:
        User ID string.

    Raises:
        InvalidTokenError: If 'sub' claim is missing.
    """
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise InvalidTokenError("Token missing 'sub' claim.")
    return str(user_id)
