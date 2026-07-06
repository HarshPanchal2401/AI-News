"""
AI News Intelligence Engine – Semantic Search Service
=======================================================
Supports semantic search over NewsEvents using Gemini embeddings.

Examples of supported queries:
  - "Latest OpenAI news"
  - "Funding this week"
  - "Claude news"
  - "AI Agent updates"
  - "GPU announcements"
  - "Research on multimodal models"
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.news_event import NewsEvent
from app.services.ai.gemini_client import get_gemini_client

logger = get_logger(__name__)

EMBEDDING_SIMILARITY_THRESHOLD = 0.78
MAX_SEMANTIC_CANDIDATES = 300
DEFAULT_SEARCH_WINDOW_DAYS = 7


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class SearchService:
    """
    Hybrid search service combining semantic (embedding) and keyword search.

    Pipeline:
      1. Generate query embedding via Gemini
      2. Fetch recent events with embeddings
      3. Score by cosine similarity
      4. Merge with keyword matches (for exact entity names)
      5. Re-rank by combined score (similarity + priority)
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.client = get_gemini_client()

    async def search(
        self,
        query: str,
        limit: int = 20,
        days: int = DEFAULT_SEARCH_WINDOW_DAYS,
        category: str | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Perform hybrid semantic + keyword search over NewsEvents.

        Args:
            query: Natural language or keyword search query.
            limit: Maximum number of results to return.
            days: How many days back to search.
            category: Filter by event category.
            event_type: Filter by event type.

        Returns:
            List of event dicts with similarity scores.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Run both search strategies in parallel
        semantic_task = self._semantic_search(query, cutoff, MAX_SEMANTIC_CANDIDATES)
        keyword_task = self._keyword_search(query, cutoff, 50)

        import asyncio
        semantic_results, keyword_results = await asyncio.gather(
            semantic_task, keyword_task, return_exceptions=True
        )

        # Merge and deduplicate
        seen_ids: set[str] = set()
        merged: list[dict] = []

        # Semantic results (with similarity score)
        if not isinstance(semantic_results, Exception):
            for item in semantic_results:
                eid = item["id"]
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    merged.append(item)

        # Keyword results (with keyword boost)
        if not isinstance(keyword_results, Exception):
            for event in keyword_results:
                eid = str(event.id)
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    merged.append({
                        **self._event_to_result(event),
                        "similarity_score": 0.7,  # Default for keyword match
                        "match_type": "keyword",
                    })

        # Apply filters
        if category:
            merged = [r for r in merged if r.get("category") == category]
        if event_type:
            merged = [r for r in merged if r.get("event_type") == event_type]

        # Re-rank: combined score = similarity * 0.6 + priority / 100 * 0.4
        for item in merged:
            sim = item.get("similarity_score", 0.5)
            priority = item.get("priority_score", 50) / 100.0
            item["combined_score"] = sim * 0.6 + priority * 0.4

        merged.sort(key=lambda x: x["combined_score"], reverse=True)

        logger.info(
            "search_complete",
            query=query[:60],
            total_candidates=len(merged),
            returned=min(limit, len(merged)),
        )

        return merged[:limit]

    async def _semantic_search(
        self, query: str, cutoff: datetime, limit: int
    ) -> list[dict]:
        """Generate query embedding and find similar events."""
        query_embedding = await self.client.generate_embedding(query)
        if not query_embedding:
            return []

        # Fetch events with embeddings
        stmt = (
            select(NewsEvent)
            .where(
                NewsEvent.published_at >= cutoff,
                NewsEvent.embedding_json.is_not(None),
            )
            .order_by(NewsEvent.priority_score.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        events = result.scalars().all()

        scored: list[dict] = []
        for event in events:
            try:
                event_embedding = json.loads(event.embedding_json)
                sim = cosine_similarity(query_embedding, event_embedding)
                if sim >= EMBEDDING_SIMILARITY_THRESHOLD:
                    scored.append({
                        **self._event_to_result(event),
                        "similarity_score": round(sim, 4),
                        "match_type": "semantic",
                    })
            except (json.JSONDecodeError, ValueError):
                continue

        scored.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored

    async def _keyword_search(
        self, query: str, cutoff: datetime, limit: int
    ) -> list[NewsEvent]:
        """Keyword-based fallback search in headline + tags + companies."""
        query_lower = query.lower()
        terms = [t for t in query_lower.split() if len(t) > 2]

        if not terms:
            return []

        # Use PostgreSQL ilike for case-insensitive search
        from sqlalchemy import cast, String
        conditions = []
        for term in terms[:5]:  # Limit terms to avoid complexity
            conditions.append(
                NewsEvent.headline.ilike(f"%{term}%")
            )

        stmt = (
            select(NewsEvent)
            .where(
                NewsEvent.published_at >= cutoff,
                or_(*conditions),
            )
            .order_by(NewsEvent.priority_score.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _event_to_result(event: NewsEvent) -> dict[str, Any]:
        """Convert a NewsEvent to a search result dict."""
        return {
            "id": str(event.id),
            "headline": event.headline,
            "summary": event.summary,
            "category": event.category,
            "event_type": event.event_type,
            "priority_score": round(event.priority_score, 1),
            "freshness_score": round(event.freshness_score, 1),
            "companies": event.companies[:5] if event.companies else [],
            "tags": event.tags[:5] if event.tags else [],
            "source_count": event.source_count,
            "published_at": event.published_at.isoformat() if event.published_at else None,
            "primary_source_url": event.primary_source_url,
            "is_breaking": event.is_breaking,
            "sentiment": event.sentiment,
        }
