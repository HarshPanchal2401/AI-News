"""
AI Pulse – Generic RSS/Atom Fetcher
=====================================
Parses RSS and Atom feeds using feedparser.
Used as a base for sources: Google AI, DeepMind, Anthropic, Hugging Face,
MIT Technology Review, TechCrunch AI, VentureBeat AI, Reuters, Mistral AI.
"""

from __future__ import annotations

from typing import ClassVar

import feedparser

from app.core.config import settings
from app.services.news_fetchers.base import BaseFetcher, RawArticle
from app.utils.date_utils import parse_datetime
from app.utils.text_utils import clean_html, extract_domain


class RSSFetcher(BaseFetcher):
    """
    Generic RSS/Atom feed fetcher.

    Can be used standalone or subclassed for source-specific behavior.
    """

    SOURCE_TYPE: ClassVar[str] = "rss"

    def __init__(self, feed_url: str, source_name: str, source_domain: str,
                 is_official: bool = False, official_company: str | None = None) -> None:
        super().__init__()
        self.feed_url = feed_url
        self.SOURCE_NAME = source_name
        self.SOURCE_DOMAIN = source_domain
        self.IS_OFFICIAL = is_official
        self.OFFICIAL_COMPANY = official_company

    async def fetch(self) -> list[RawArticle]:
        """Parse the RSS feed and return normalized articles."""
        import asyncio

        # feedparser is synchronous — run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(
            None, lambda: feedparser.parse(self.feed_url)
        )

        if feed.bozo and not feed.entries:
            self.logger.warning(
                "rss_parse_error",
                source=self.SOURCE_NAME,
                url=self.feed_url,
                error=str(feed.bozo_exception) if feed.bozo_exception else "unknown",
            )
            return []

        articles: list[RawArticle] = []
        max_articles = settings.max_articles_per_source

        for entry in feed.entries[:max_articles]:
            title = getattr(entry, "title", "").strip()
            url = getattr(entry, "link", "").strip()

            if not title or not url:
                continue

            # Extract description
            description = ""
            if hasattr(entry, "summary"):
                description = clean_html(entry.summary)
            elif hasattr(entry, "description"):
                description = clean_html(entry.description)

            # Extract content
            content_snippet = ""
            if hasattr(entry, "content") and entry.content:
                content_snippet = clean_html(entry.content[0].get("value", ""))[:500]

            # Extract image
            image_url = None
            if hasattr(entry, "media_content") and entry.media_content:
                image_url = entry.media_content[0].get("url")
            elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get("url")

            # Extract author
            author = getattr(entry, "author", None)

            # Parse publication date
            published_at = None
            if hasattr(entry, "published"):
                published_at = parse_datetime(entry.published)
            elif hasattr(entry, "updated"):
                published_at = parse_datetime(entry.updated)

            article = self._make_article(
                title=title,
                url=url,
                description=description[:1000] if description else None,
                content_snippet=content_snippet or None,
                image_url=image_url,
                author=author,
                published_at=published_at,
            )
            articles.append(article)

        return articles


# ── Pre-configured RSS Fetchers ────────────────────────────────────────────────

class GoogleAIFetcher(RSSFetcher):
    SOURCE_NAME = "google_ai_blog"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://blog.research.google/feeds/posts/default",
            source_name="google_ai_blog",
            source_domain="blog.research.google",
            is_official=True,
            official_company="Google",
        )


class DeepMindFetcher(RSSFetcher):
    SOURCE_NAME = "deepmind_blog"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://deepmind.google/blog/rss.xml",
            source_name="deepmind_blog",
            source_domain="deepmind.google",
            is_official=True,
            official_company="Google DeepMind",
        )


class AnthropicFetcher(RSSFetcher):
    SOURCE_NAME = "anthropic_news"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://www.anthropic.com/rss.xml",
            source_name="anthropic_news",
            source_domain="anthropic.com",
            is_official=True,
            official_company="Anthropic",
        )


class HuggingFaceFetcher(RSSFetcher):
    SOURCE_NAME = "huggingface_blog"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://huggingface.co/blog/feed.xml",
            source_name="huggingface_blog",
            source_domain="huggingface.co",
            is_official=True,
            official_company="Hugging Face",
        )


class MistralFetcher(RSSFetcher):
    SOURCE_NAME = "mistral_news"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://mistral.ai/news/rss",
            source_name="mistral_news",
            source_domain="mistral.ai",
            is_official=True,
            official_company="Mistral AI",
        )


class MicrosoftAIFetcher(RSSFetcher):
    SOURCE_NAME = "microsoft_ai_blog"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://blogs.microsoft.com/ai/feed/",
            source_name="microsoft_ai_blog",
            source_domain="blogs.microsoft.com",
            is_official=True,
            official_company="Microsoft",
        )


class MetaAIFetcher(RSSFetcher):
    SOURCE_NAME = "meta_ai_blog"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://ai.meta.com/blog/rss/",
            source_name="meta_ai_blog",
            source_domain="ai.meta.com",
            is_official=True,
            official_company="Meta",
        )


class NVIDIAFetcher(RSSFetcher):
    SOURCE_NAME = "nvidia_ai_blog"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://blogs.nvidia.com/blog/category/artificial-intelligence/feed/",
            source_name="nvidia_ai_blog",
            source_domain="blogs.nvidia.com",
            is_official=True,
            official_company="NVIDIA",
        )


class TechCrunchAIFetcher(RSSFetcher):
    SOURCE_NAME = "techcrunch_ai"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://techcrunch.com/category/artificial-intelligence/feed/",
            source_name="techcrunch_ai",
            source_domain="techcrunch.com",
        )


class VentureBeatAIFetcher(RSSFetcher):
    SOURCE_NAME = "venturebeat_ai"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://venturebeat.com/category/ai/feed/",
            source_name="venturebeat_ai",
            source_domain="venturebeat.com",
        )


class MITTechReviewFetcher(RSSFetcher):
    SOURCE_NAME = "mit_tech_review"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://www.technologyreview.com/feed/",
            source_name="mit_tech_review",
            source_domain="technologyreview.com",
        )


class ReutersAIFetcher(RSSFetcher):
    SOURCE_NAME = "reuters_technology"

    def __init__(self) -> None:
        super().__init__(
            feed_url="https://feeds.reuters.com/reuters/technologyNews",
            source_name="reuters_technology",
            source_domain="reuters.com",
        )
