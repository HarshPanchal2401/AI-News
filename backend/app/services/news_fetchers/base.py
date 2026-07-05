"""
AI Pulse – Base News Fetcher
==============================
Abstract base class for all news source fetchers.
Provides retry logic, rate limiting, and a standard RawArticle dataclass.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RawArticle:
    """
    Normalized raw article from any news source.
    Before deduplication, verification, or AI processing.
    """

    # Required fields
    title: str
    url: str
    source_name: str
    source_domain: str

    # Optional content
    description: str | None = None
    content_snippet: str | None = None
    image_url: str | None = None
    author: str | None = None
    published_at: datetime | None = None

    # Source metadata
    is_official: bool = False
    official_company: str | None = None
    source_type: str = "rss"  # rss | api | scrape

    # Pre-computed fields (populated by normalizer)
    normalized_url: str = ""
    normalized_title: str = ""
    title_fingerprint: str = ""
    content_fingerprint: str = ""

    def __post_init__(self) -> None:
        """Auto-generate a basic fingerprint from URL if not set."""
        if not self.normalized_url:
            self.normalized_url = self.url.strip().lower()

    @property
    def url_hash(self) -> str:
        """SHA-256 of the normalized URL."""
        return hashlib.sha256(self.normalized_url.encode()).hexdigest()

    def is_valid(self) -> bool:
        """Basic validation — must have title and URL."""
        return bool(self.title and self.title.strip() and self.url and self.url.strip())


class BaseFetcher(ABC):
    """
    Abstract base class for all news fetchers.

    Subclasses must implement `fetch()` which returns a list of RawArticles.
    This base class handles:
    - Logging with source context
    - Error isolation (exceptions don't propagate to the orchestrator)
    - Basic result validation
    """

    # Class-level metadata — override in subclasses
    SOURCE_NAME: ClassVar[str] = "unknown"
    SOURCE_DOMAIN: ClassVar[str] = "unknown"
    SOURCE_TYPE: ClassVar[str] = "rss"
    IS_OFFICIAL: ClassVar[bool] = False
    OFFICIAL_COMPANY: ClassVar[str | None] = None

    def __init__(self) -> None:
        self.logger = get_logger(f"fetcher.{self.SOURCE_NAME}")

    @abstractmethod
    async def fetch(self) -> list[RawArticle]:
        """
        Fetch articles from the news source.

        Returns:
            List of RawArticle instances.
        """
        ...

    async def safe_fetch(self) -> list[RawArticle]:
        """
        Fetch articles with error isolation.
        Exceptions are caught and logged — never propagates to orchestrator.

        Returns:
            List of valid RawArticle instances (empty list on failure).
        """
        try:
            self.logger.info("fetcher_started", source=self.SOURCE_NAME)
            articles = await self.fetch()
            valid = [a for a in articles if a.is_valid()]

            self.logger.info(
                "fetcher_completed",
                source=self.SOURCE_NAME,
                total_fetched=len(articles),
                valid=len(valid),
                dropped=len(articles) - len(valid),
            )
            return valid

        except Exception as exc:
            self.logger.error(
                "fetcher_failed",
                source=self.SOURCE_NAME,
                error=str(exc),
                exc_info=True,
            )
            return []

    def _make_article(self, **kwargs) -> RawArticle:
        """
        Convenience factory that pre-fills source metadata.
        Subclasses call this instead of constructing RawArticle directly.
        """
        return RawArticle(
            source_name=self.SOURCE_NAME,
            source_domain=self.SOURCE_DOMAIN,
            source_type=self.SOURCE_TYPE,
            is_official=self.IS_OFFICIAL,
            official_company=self.OFFICIAL_COMPANY,
            **kwargs,
        )
