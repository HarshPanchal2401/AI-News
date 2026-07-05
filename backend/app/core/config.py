"""
AI Pulse – Application Configuration
=====================================
Centralized settings using Pydantic BaseSettings.
All values come from environment variables / .env file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Provides type-safe, validated configuration for the entire application.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────────────────
    app_env: Literal["development", "production", "testing"] = "development"
    app_name: str = "AI Pulse"
    app_version: str = "1.0.0"
    log_level: str = "info"
    secret_key: str = Field(..., min_length=32)

    # ── Supabase ───────────────────────────────────────────────────────────────
    supabase_url: str = Field(...)
    supabase_anon_key: str = Field(...)
    supabase_service_key: str = Field(...)
    supabase_jwt_secret: str = Field(...)
    database_url: str = Field(...)

    # ── Gemini AI ──────────────────────────────────────────────────────────────
    gemini_api_key: str = Field(...)
    gemini_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "models/text-embedding-004"
    gemini_max_rpm: int = 15

    # ── Firebase ───────────────────────────────────────────────────────────────
    firebase_credentials_json: str | None = None
    firebase_credentials_path: str | None = None

    # ── Upstash Redis ──────────────────────────────────────────────────────────
    upstash_redis_rest_url: str = Field(...)
    upstash_redis_rest_token: str = Field(...)

    # ── Scheduler ──────────────────────────────────────────────────────────────
    scheduler_timezone: str = "UTC"
    daily_brief_hour: int = Field(default=10, ge=0, le=23)
    daily_brief_minute: int = Field(default=0, ge=0, le=59)
    cleanup_days_old: int = Field(default=30, ge=1)

    # ── Rate Limiting ──────────────────────────────────────────────────────────
    rate_limit_per_minute_authenticated: int = 100
    rate_limit_per_minute_anonymous: int = 20

    # ── CORS ───────────────────────────────────────────────────────────────────
    cors_origins: list[str] | str = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # ── Pagination ─────────────────────────────────────────────────────────────
    default_page_size: int = Field(default=20, ge=1, le=100)
    max_page_size: int = Field(default=100, ge=1, le=500)

    # ── News Fetching ──────────────────────────────────────────────────────────
    fetch_timeout_seconds: int = 30
    fetch_max_retries: int = 3
    fetch_retry_delay_seconds: float = 2.0
    max_articles_per_source: int = 50
    min_trust_score: float = 40.0
    min_final_score: float = 30.0
    min_brief_articles: int = 10

    # ── Duplicate Detection ────────────────────────────────────────────────────
    semantic_similarity_threshold: float = Field(default=0.92, ge=0.0, le=1.0)

    # ── Cache TTLs (seconds) ───────────────────────────────────────────────────
    cache_ttl_news_latest: int = 300
    cache_ttl_news_detail: int = 1800
    cache_ttl_categories: int = 3600
    cache_ttl_brief: int = 43200

    # ── Derived Properties ─────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_testing(self) -> bool:
        return self.app_env == "testing"

    @property
    def api_prefix(self) -> str:
        return "/api/v1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached singleton of application settings.
    Using lru_cache ensures settings are loaded only once.
    """
    return Settings()


# Convenience alias — import this throughout the app
settings = get_settings()
