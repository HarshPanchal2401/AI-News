"""
AI Pulse – Verification Engine
================================
Assigns trust scores and verifies article authenticity.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.services.news_fetchers.base import RawArticle
from app.utils.date_utils import hours_since

logger = get_logger(__name__)

# ── Trusted Source Domains ─────────────────────────────────────────────────────

TIER_1_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.co.uk", "nytimes.com",
    "wsj.com", "theguardian.com", "ft.com",
}

OFFICIAL_COMPANY_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "blog.research.google",
    "ai.meta.com", "blogs.microsoft.com", "blogs.nvidia.com",
    "huggingface.co", "mistral.ai", "x.ai", "perplexity.ai",
}

TRUSTED_TECH_DOMAINS = {
    "techcrunch.com", "venturebeat.com", "technologyreview.com",
    "wired.com", "theverge.com", "arstechnica.com", "zdnet.com",
    "arxiv.org",
}


@dataclass
class TrustResult:
    """Result of trust scoring for a single article."""
    trust_score: float
    is_verified: bool
    notes: str


def compute_trust_score(article: RawArticle, corroboration_count: int = 1) -> TrustResult:
    """
    Compute a trust score (0–100) for a raw article.

    Rules:
    - Official company blog → 95–100
    - Tier-1 media → 80–89
    - Trusted tech media → 65–74
    - Corroborated by 3+ sources → +15 bonus
    - Corroborated by 2 sources → +8 bonus
    - Published within 6h → +10 bonus
    - Older than 48h → -20 penalty
    - Single unknown source → score < 40 → reject

    Args:
        article: The raw article to score.
        corroboration_count: How many independent trusted sources cover this story.

    Returns:
        TrustResult with score and verification status.
    """
    score = 0.0
    notes_parts: list[str] = []

    domain = article.source_domain.lower()

    # ── Base score by source type ─────────────────────────────────────────────
    if article.is_official or domain in OFFICIAL_COMPANY_DOMAINS:
        score = 95.0
        notes_parts.append("official company source")
    elif domain in TIER_1_DOMAINS:
        score = 80.0
        notes_parts.append("tier-1 media")
    elif domain in TRUSTED_TECH_DOMAINS:
        score = 65.0
        notes_parts.append("trusted tech media")
    else:
        score = 35.0
        notes_parts.append("unknown/low-trust source")

    # ── Corroboration bonus ────────────────────────────────────────────────────
    if corroboration_count >= 3:
        score += 15.0
        notes_parts.append(f"corroborated by {corroboration_count} sources (+15)")
    elif corroboration_count == 2:
        score += 8.0
        notes_parts.append(f"corroborated by 2 sources (+8)")

    # ── Freshness bonus/penalty ────────────────────────────────────────────────
    if article.published_at:
        age_hours = hours_since(article.published_at)
        if age_hours <= 6:
            score += 10.0
            notes_parts.append("very fresh (<6h, +10)")
        elif age_hours > 48:
            score -= 20.0
            notes_parts.append(f"old ({age_hours:.0f}h, -20)")

    # Cap at 100
    score = min(100.0, max(0.0, score))

    is_verified = score >= 40.0

    return TrustResult(
        trust_score=round(score, 1),
        is_verified=is_verified,
        notes="; ".join(notes_parts),
    )


class CrossReferencer:
    """
    Groups raw articles by story and counts independent source coverage.
    Uses title similarity to group related stories.
    """

    def group_by_story(
        self, articles: list[RawArticle]
    ) -> dict[str, list[RawArticle]]:
        """
        Group articles that likely cover the same story.

        Uses simple keyword overlap as a grouping heuristic.
        Returns a dict mapping canonical title → list of covering articles.
        """
        from app.utils.text_utils import normalize_title

        groups: dict[str, list[RawArticle]] = {}
        assigned: set[int] = set()

        for i, article in enumerate(articles):
            if i in assigned:
                continue

            norm_i = normalize_title(article.title)
            words_i = set(norm_i.split())
            if not words_i:
                continue

            group_key = article.url
            groups[group_key] = [article]
            assigned.add(i)

            for j, other in enumerate(articles):
                if j in assigned or j == i:
                    continue

                norm_j = normalize_title(other.title)
                words_j = set(norm_j.split())

                if not words_j:
                    continue

                # Jaccard similarity >= 0.35 → same story
                intersection = len(words_i & words_j)
                union = len(words_i | words_j)
                jaccard = intersection / union if union else 0.0

                if jaccard >= 0.35:
                    groups[group_key].append(other)
                    assigned.add(j)

        return groups

    def count_trusted_sources(self, articles: list[RawArticle]) -> int:
        """
        Count how many distinct trusted domains cover a story.
        """
        trusted_domains = TIER_1_DOMAINS | OFFICIAL_COMPANY_DOMAINS | TRUSTED_TECH_DOMAINS
        domains = {a.source_domain.lower() for a in articles}
        return len(domains & trusted_domains)


class VerificationEngine:
    """
    Orchestrates trust scoring and cross-referencing for all fetched articles.

    Usage:
        engine = VerificationEngine()
        scored = engine.verify_batch(raw_articles)
    """

    def __init__(self) -> None:
        self.cross_ref = CrossReferencer()

    def verify_batch(
        self, articles: list[RawArticle]
    ) -> list[tuple[RawArticle, TrustResult]]:
        """
        Verify a batch of raw articles.

        Groups articles by story, computes corroboration counts,
        then assigns individual trust scores.

        Args:
            articles: List of raw articles from all fetchers.

        Returns:
            List of (article, TrustResult) tuples.
        """
        # Group by story for cross-referencing
        story_groups = self.cross_ref.group_by_story(articles)

        # Build a map: article URL → corroboration count
        corroboration_map: dict[str, int] = {}
        for group_articles in story_groups.values():
            count = self.cross_ref.count_trusted_sources(group_articles)
            for a in group_articles:
                corroboration_map[a.url] = max(count, 1)

        results: list[tuple[RawArticle, TrustResult]] = []

        for article in articles:
            corr_count = corroboration_map.get(article.url, 1)
            trust_result = compute_trust_score(article, corr_count)

            if not trust_result.is_verified:
                logger.debug(
                    "article_rejected",
                    title=article.title[:60],
                    trust_score=trust_result.trust_score,
                    notes=trust_result.notes,
                )

            results.append((article, trust_result))

        verified_count = sum(1 for _, r in results if r.is_verified)
        logger.info(
            "verification_complete",
            total=len(results),
            verified=verified_count,
            rejected=len(results) - verified_count,
        )

        return results
