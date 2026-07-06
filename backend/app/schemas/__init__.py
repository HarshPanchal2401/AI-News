"""
AI Pulse – Pydantic Schemas
============================
Request/Response schemas for all API endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ── Shared Base ───────────────────────────────────────────────────────────────

class APIBase(BaseModel):
    """Base for all schemas — enables from_attributes for ORM compatibility."""
    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(APIBase):
    """Generic paginated response wrapper."""
    total: int
    page: int
    limit: int
    pages: int
    items: list[Any]


# ── User Schemas ──────────────────────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str | None = Field(None, max_length=150)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(APIBase):
    id: uuid.UUID
    email: str
    display_name: str | None
    avatar_url: str | None
    is_active: bool
    is_verified: bool
    last_seen_at: datetime | None
    created_at: datetime


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(None, max_length=150)
    avatar_url: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800


class FCMTokenRequest(BaseModel):
    fcm_token: str = Field(..., min_length=10)


# ── Preferences Schemas ───────────────────────────────────────────────────────

VALID_COMPANIES = [
    "OpenAI", "Google", "Anthropic", "Microsoft", "Meta",
    "NVIDIA", "Amazon", "Apple", "Tesla", "DeepMind",
    "Mistral AI", "Hugging Face", "xAI", "Perplexity AI",
]

VALID_CATEGORIES = [
    "LLMs", "AI Agents", "Research", "Robotics", "Healthcare",
    "Finance", "Coding", "Open Source", "Enterprise AI", "Safety",
    "Computer Vision", "NLP", "Multimodal", "Hardware",
]


class PreferencesResponse(APIBase):
    id: uuid.UUID
    user_id: uuid.UUID
    favorite_companies: list[str]
    favorite_categories: list[str]
    favorite_topics: list[str]
    blocked_topics: list[str]
    bookmarked_articles: list[str] = Field(default_factory=list)
    notification_enabled: bool
    notification_hour: int
    updated_at: datetime


class PreferencesUpdateRequest(BaseModel):
    favorite_companies: list[str] | None = None
    favorite_categories: list[str] | None = None
    favorite_topics: list[str] | None = None
    blocked_topics: list[str] | None = None
    bookmarked_articles: list[str] | None = None
    notification_enabled: bool | None = None
    notification_hour: int | None = Field(None, ge=0, le=23)


# ── News Article Schemas ──────────────────────────────────────────────────────

class NewsAnalysisResponse(APIBase):
    summary: str
    executive_summary: str | None = None
    key_takeaways: list[str] = Field(default_factory=list)
    category: str
    subcategory: str | None = None
    event_type: str | None = None
    companies: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    importance_score: float
    why_it_matters: str
    reading_time_minutes: int
    products_mentioned: list[str] = Field(default_factory=list)
    people_mentioned: list[str] = Field(default_factory=list)
    technologies_mentioned: list[str] = Field(default_factory=list)
    programming_languages: list[str] = Field(default_factory=list)
    models_mentioned: list[str] = Field(default_factory=list)
    funding_amount: float | None = None
    funding_currency: str | None = None
    research_paper_url: str | None = None
    arxiv_id: str | None = None
    countries_affected: list[str] = Field(default_factory=list)
    industries_affected: list[str] = Field(default_factory=list)
    market_impact: str | None = None
    business_opportunities: str | None = None
    risks: str | None = None
    sentiment: str | None = None
    urgency: str | None = None
    confidence_score: float | None = None


class NewsSourceResponse(APIBase):
    id: uuid.UUID
    name: str
    display_name: str
    domain: str
    is_official: bool
    reliability_score: float


class NewsArticleResponse(APIBase):
    id: uuid.UUID
    title: str
    url: str
    image_url: str | None
    description: str | None
    author: str | None
    published_at: datetime | None
    source_domain: str
    trust_score: float
    importance_score: float
    final_score: float
    is_official_source: bool
    view_count: int
    bookmark_count: int
    supporting_sources: list[str]
    analysis: NewsAnalysisResponse | None
    created_at: datetime


class NewsArticleListResponse(APIBase):
    id: uuid.UUID
    title: str
    url: str
    image_url: str | None
    description: str | None
    published_at: datetime | None
    source_domain: str
    trust_score: float
    final_score: float
    category: str | None = None
    reading_time_minutes: int | None = None
    companies: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime


class NewsListPaginatedResponse(BaseModel):
    total: int
    page: int
    limit: int
    pages: int
    items: list[NewsArticleListResponse]


# ── Daily Brief Schemas ───────────────────────────────────────────────────────

class DailyBriefResponse(APIBase):
    id: uuid.UUID
    brief_date: date
    total_articles: int
    personalization_score: float
    sent_at: datetime | None
    articles: list[NewsArticleListResponse] = Field(default_factory=list)
    created_at: datetime


class DailyBriefSummary(APIBase):
    id: uuid.UUID
    brief_date: date
    total_articles: int
    sent_at: datetime | None
    created_at: datetime


# ── Bookmark Schemas ──────────────────────────────────────────────────────────

class BookmarkCreateRequest(BaseModel):
    article_id: uuid.UUID
    note: str | None = Field(None, max_length=500)


class BookmarkResponse(APIBase):
    id: uuid.UUID
    article_id: uuid.UUID
    note: str | None
    created_at: datetime
    article: NewsArticleListResponse | None = None


# ── Notification Schemas ──────────────────────────────────────────────────────

class NotificationResponse(APIBase):
    id: uuid.UUID
    title: str
    body: str
    notification_type: str
    data: dict | None
    sent_at: datetime | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime


# ── Category Schemas ──────────────────────────────────────────────────────────

class CategoryResponse(APIBase):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    icon: str | None
    color: str | None
    article_count: int


# ── Search Schemas ────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    q: str = Field(..., min_length=2, max_length=200)
    category: str | None = None
    company: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    sort: str = Field(default="relevance", pattern="^(relevance|date|score)$")
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)


# ── Admin Schemas ─────────────────────────────────────────────────────────────

class AdminStatsResponse(BaseModel):
    total_articles: int
    articles_today: int
    verified_articles: int
    duplicate_articles: int
    ai_processed: int
    total_users: int
    active_users: int
    total_briefs_sent: int
    sources_active: int
    sources_failed: int


class NewsSourceAdminResponse(APIBase):
    id: uuid.UUID
    name: str
    display_name: str
    url: str
    source_type: str
    is_active: bool
    reliability_score: float
    consecutive_failures: int
    last_fetched_at: datetime | None
    total_articles_fetched: int


class NewsSourceUpdateRequest(BaseModel):
    is_active: bool | None = None
    reliability_score: float | None = Field(None, ge=0, le=100)


# ── Health Schemas ────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


class DetailedHealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    cache: str
    scheduler: str
    checks: dict[str, bool]
