"""
AI Pulse – Duplicate Detection Engine
========================================
5-layer duplicate detection pipeline:
1. Exact URL match
2. Normalized title hash
3. Content fingerprint
4. Semantic embedding similarity (Gemini)
5. Entity fingerprint (Company + Product + Event)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.news_article import NewsArticle
from app.services.news_fetchers.base import RawArticle
from app.utils.text_utils import (
    content_fingerprint,
    entity_fingerprint,
    normalize_title,
    normalize_url,
    title_fingerprint,
)

logger = get_logger(__name__)


@dataclass
class DuplicateResult:
    """Result of duplicate detection for a single article."""
    is_duplicate: bool
    canonical_id: str | None = None
    detection_layer: str | None = None  # Which layer caught the duplicate
    similarity_score: float = 0.0


async def get_gemini_embedding(text: str) -> list[float] | None:
    """
    Generate a text embedding using Gemini's embedding model.
    Returns None on failure.
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        result = genai.embed_content(
            model=settings.gemini_embedding_model,
            content=text,
            task_type="SEMANTIC_SIMILARITY",
        )
        return result["embedding"]
    except Exception as exc:
        logger.warning("embedding_generation_failed", error=str(exc))
        return None


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class DuplicateDetectionEngine:
    """
    5-layer duplicate detection engine.

    Checks each incoming article against the database using progressively
    more expensive detection methods.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def check(self, article: RawArticle) -> DuplicateResult:
        """
        Run all 5 detection layers in order.
        Returns immediately when a duplicate is found.
        """
        norm_url = normalize_url(article.url)
        norm_title = normalize_title(article.title)
        t_fp = title_fingerprint(article.title)
        c_fp = content_fingerprint(article.title, article.content_snippet or "")

        # ── Layer 1: Exact normalized URL match ───────────────────────────────
        result = await self._check_url(norm_url)
        if result.is_duplicate:
            return result

        # ── Layer 2: Normalized title hash ────────────────────────────────────
        result = await self._check_title_fingerprint(t_fp)
        if result.is_duplicate:
            return result

        # ── Layer 3: Content fingerprint ──────────────────────────────────────
        result = await self._check_content_fingerprint(c_fp)
        if result.is_duplicate:
            return result

        # ── Layer 4: Semantic similarity (most expensive — last resort) ───────
        result = await self._check_semantic_similarity(article.title)
        if result.is_duplicate:
            return result

        # ── Layer 5: Entity fingerprint ───────────────────────────────────────
        # (No-op here — entity fp is populated after AI processing)
        # Entity-based deduplication runs as a post-processing step.

        return DuplicateResult(is_duplicate=False)

    async def _check_url(self, normalized_url: str) -> DuplicateResult:
        """Layer 1: Exact URL match."""
        stmt = select(NewsArticle).where(
            NewsArticle.normalized_url == normalized_url,
            NewsArticle.is_duplicate == False,  # noqa: E712
        ).limit(1)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return DuplicateResult(
                is_duplicate=True,
                canonical_id=str(existing.id),
                detection_layer="url",
                similarity_score=1.0,
            )
        return DuplicateResult(is_duplicate=False)

    async def _check_title_fingerprint(self, fingerprint: str) -> DuplicateResult:
        """Layer 2: Normalized title hash."""
        stmt = select(NewsArticle).where(
            NewsArticle.title_fingerprint == fingerprint,
            NewsArticle.is_duplicate == False,  # noqa: E712
        ).limit(1)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return DuplicateResult(
                is_duplicate=True,
                canonical_id=str(existing.id),
                detection_layer="title_hash",
                similarity_score=1.0,
            )
        return DuplicateResult(is_duplicate=False)

    async def _check_content_fingerprint(self, fingerprint: str) -> DuplicateResult:
        """Layer 3: Content fingerprint."""
        stmt = select(NewsArticle).where(
            NewsArticle.content_fingerprint == fingerprint,
            NewsArticle.is_duplicate == False,  # noqa: E712
        ).limit(1)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return DuplicateResult(
                is_duplicate=True,
                canonical_id=str(existing.id),
                detection_layer="content_hash",
                similarity_score=1.0,
            )
        return DuplicateResult(is_duplicate=False)

    async def _check_semantic_similarity(self, title: str) -> DuplicateResult:
        """
        Layer 4: Semantic embedding similarity.
        Compares Gemini embedding of the new title against recent articles.
        """
        from app.utils.date_utils import hours_ago

        new_embedding = await get_gemini_embedding(title)
        if not new_embedding:
            return DuplicateResult(is_duplicate=False)

        # Fetch recent articles with embeddings (last 48h)
        cutoff = hours_ago(48)
        stmt = (
            select(NewsArticle)
            .where(
                NewsArticle.embedding_json.is_not(None),
                NewsArticle.is_duplicate == False,  # noqa: E712
                NewsArticle.created_at >= cutoff,
            )
            .limit(200)
        )
        result = await self.db.execute(stmt)
        recent_articles = result.scalars().all()

        threshold = settings.semantic_similarity_threshold
        best_match: NewsArticle | None = None
        best_score = 0.0

        for article in recent_articles:
            try:
                existing_embedding = json.loads(article.embedding_json)
                score = cosine_similarity(new_embedding, existing_embedding)
                if score > best_score:
                    best_score = score
                    best_match = article
            except (json.JSONDecodeError, ValueError):
                continue

        if best_match and best_score >= threshold:
            return DuplicateResult(
                is_duplicate=True,
                canonical_id=str(best_match.id),
                detection_layer="semantic_similarity",
                similarity_score=best_score,
            )

        return DuplicateResult(is_duplicate=False)

    async def check_entity_fingerprint(
        self, companies: list[str], product: str, event_type: str
    ) -> DuplicateResult:
        """
        Layer 5: Entity fingerprint (post-AI-processing check).
        Called after companies/product are extracted by Gemini.
        """
        fp = entity_fingerprint(companies, product, event_type)
        if not fp:
            return DuplicateResult(is_duplicate=False)

        stmt = select(NewsArticle).where(
            NewsArticle.entity_fingerprint == fp,
            NewsArticle.is_duplicate == False,  # noqa: E712
        ).limit(1)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return DuplicateResult(
                is_duplicate=True,
                canonical_id=str(existing.id),
                detection_layer="entity_fingerprint",
                similarity_score=1.0,
            )
        return DuplicateResult(is_duplicate=False)
