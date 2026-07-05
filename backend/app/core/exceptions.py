"""
AI Pulse – Custom Exception Hierarchy
=======================================
Centralized exception definitions with HTTP status codes.
All application exceptions derive from AppException.
"""

from __future__ import annotations

from typing import Any


class AppException(Exception):
    """
    Base exception for all AI Pulse application errors.
    Carries an HTTP status code and a user-facing message.
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "An internal error occurred.",
        detail: Any = None,
        *,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail
        if error_code:
            self.error_code = error_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.error_code,
            "message": self.message,
            "detail": self.detail,
        }


# ── 400 Bad Request ────────────────────────────────────────────────────────────
class ValidationError(AppException):
    status_code = 400
    error_code = "VALIDATION_ERROR"

    def __init__(self, message: str = "Validation failed.", detail: Any = None) -> None:
        super().__init__(message, detail)


class BadRequestError(AppException):
    status_code = 400
    error_code = "BAD_REQUEST"


# ── 401 Unauthorized ───────────────────────────────────────────────────────────
class AuthException(AppException):
    status_code = 401
    error_code = "UNAUTHORIZED"

    def __init__(self, message: str = "Authentication required.") -> None:
        super().__init__(message)


class InvalidTokenError(AuthException):
    error_code = "INVALID_TOKEN"

    def __init__(self, message: str = "Invalid or expired token.") -> None:
        super().__init__(message)


class TokenExpiredError(AuthException):
    error_code = "TOKEN_EXPIRED"

    def __init__(self, message: str = "Token has expired.") -> None:
        super().__init__(message)


# ── 403 Forbidden ──────────────────────────────────────────────────────────────
class ForbiddenError(AppException):
    status_code = 403
    error_code = "FORBIDDEN"

    def __init__(self, message: str = "Access denied.") -> None:
        super().__init__(message)


# ── 404 Not Found ──────────────────────────────────────────────────────────────
class NotFoundError(AppException):
    status_code = 404
    error_code = "NOT_FOUND"

    def __init__(self, resource: str = "Resource", resource_id: Any = None) -> None:
        detail = f"ID: {resource_id}" if resource_id else None
        super().__init__(f"{resource} not found.", detail)


# ── 409 Conflict ───────────────────────────────────────────────────────────────
class DuplicateError(AppException):
    status_code = 409
    error_code = "DUPLICATE_RESOURCE"

    def __init__(self, message: str = "Resource already exists.") -> None:
        super().__init__(message)


# ── 422 Unprocessable ──────────────────────────────────────────────────────────
class UnprocessableError(AppException):
    status_code = 422
    error_code = "UNPROCESSABLE_ENTITY"


# ── 429 Too Many Requests ─────────────────────────────────────────────────────
class RateLimitError(AppException):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(self, message: str = "Rate limit exceeded. Please slow down.") -> None:
        super().__init__(message)


# ── 502/503 External Service Errors ───────────────────────────────────────────
class ExternalServiceError(AppException):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"

    def __init__(self, service: str, message: str | None = None) -> None:
        super().__init__(message or f"External service '{service}' is unavailable.")
        self.service = service


class AIProcessingError(ExternalServiceError):
    error_code = "AI_PROCESSING_ERROR"

    def __init__(self, message: str = "AI processing failed.") -> None:
        super().__init__("Gemini", message)


class NotificationError(ExternalServiceError):
    error_code = "NOTIFICATION_ERROR"

    def __init__(self, message: str = "Failed to send notification.") -> None:
        super().__init__("Firebase FCM", message)


class CacheError(ExternalServiceError):
    error_code = "CACHE_ERROR"

    def __init__(self, message: str = "Cache operation failed.") -> None:
        super().__init__("Upstash Redis", message)


# ── Domain-Specific Errors ────────────────────────────────────────────────────
class VerificationError(AppException):
    status_code = 422
    error_code = "VERIFICATION_FAILED"

    def __init__(self, message: str = "Article failed verification checks.") -> None:
        super().__init__(message)


class FetchError(AppException):
    status_code = 502
    error_code = "FETCH_ERROR"

    def __init__(self, source: str, message: str | None = None) -> None:
        super().__init__(message or f"Failed to fetch news from '{source}'.")
        self.source = source


class SchedulerError(AppException):
    status_code = 500
    error_code = "SCHEDULER_ERROR"
