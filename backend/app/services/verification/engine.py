"""
AI News Intelligence Engine – Verification Engine
===================================================
Validates articles before acceptance into the pipeline:
  1. AI Relevance Detection — reject non-AI content
  2. Content Quality Check — reject insufficient content
  3. Publication Time Verification — reject future-dated or too-old articles
  4. Source Trust Scoring — assign 0–100 trust score
  5. Cross-Source Verification — corroboration bonus
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.services.news_fetchers.base import RawArticle
from app.services.freshness_engine import should_accept_article
from app.utils.date_utils import hours_since

logger = get_logger(__name__)

# ── AI Relevance Keywords ──────────────────────────────────────────────────────
# Articles must contain at least one of these to be accepted

AI_RELEVANCE_KEYWORDS = {
    # Core AI terms
    "artificial intelligence", "machine learning", "deep learning",
    "neural network", "large language model", "llm", "generative ai",
    "foundation model", "transformer", "diffusion model",
    # Models
    "gpt", "claude", "gemini", "llama", "mistral", "grok", "stable diffusion",
    "dall-e", "sora", "whisper", "copilot",
    # Companies (AI-specific)
    "openai", "anthropic", "deepmind", "google ai", "meta ai", "hugging face",
    "mistral", "perplexity", "xai", "stability ai", "cohere",
    # AI concepts
    "ai agent", "rag", "retrieval augmented", "fine-tuning", "fine tuning",
    "embedding", "vector database", "multimodal", "reasoning model",
    "ai safety", "ai alignment", "hallucination", "benchmark",
    "natural language processing", "nlp", "computer vision",
    # Infrastructure
    "gpu cluster", "tpu", "ai chip", "inference", "nvidia h100",
    # Applications
    "ai assistant", "chatbot", "ai model", "language model", "ai research",
    "reinforcement learning", "rlhf", "ai startup", "ai funding",
}

# Minimum keyword count in title + description to be AI-relevant
MIN_AI_KEYWORD_COUNT = 1

# ── Trusted Source Domains ─────────────────────────────────────────────────────

TIER_1_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.co.uk", "nytimes.com",
    "wsj.com", "theguardian.com", "ft.com", "bloomberg.com",
}

OFFICIAL_COMPANY_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "blog.research.google",
    "ai.meta.com", "blogs.microsoft.com", "blogs.nvidia.com",
    "huggingface.co", "mistral.ai", "x.ai", "perplexity.ai",
    "stability.ai", "cohere.com",
}

TRUSTED_TECH_DOMAINS = {
    "techcrunch.com", "venturebeat.com", "technologyreview.com",
    "wired.com", "theverge.com", "arstechnica.com", "zdnet.com",
    "arxiv.org", "paperswithcode.com", "github.com",
    "news.ycombinator.com", "producthunt.com",
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
    Orchestrates full validation pipeline for incoming articles:
      1. AI Relevance Detection (keyword filter)
      2. Content Quality Check (minimum length)
      3. Freshness Validation (reject too old / future-dated)
      4. Trust Scoring
      5. Cross-Source Verification (corroboration bonus)
    """

    def __init__(self) -> None:
        self.cross_ref = CrossReferencer()

    def is_ai_relevant(self, article: RawArticle) -> bool:
        """
        Check if an article is AI-related using keyword matching.

        Checks title + description against AI_RELEVANCE_KEYWORDS.
        Official company sources (is_official=True) always pass.
        """
        # Official company sources are always AI-relevant by definition
        if article.is_official:
            return True

        # Check source domain
        domain = article.source_domain.lower()
        if domain in OFFICIAL_COMPANY_DOMAINS:
            return True

        # Keyword scan: title + description
        text = f"{article.title} {article.description or ''}".lower()

        for keyword in AI_RELEVANCE_KEYWORDS:
            if keyword in text:
                return True

        return False

    def has_sufficient_content(self, article: RawArticle) -> bool:
        """Check that the article has enough content to be meaningful."""
        if len(article.title.strip()) < 15:
            return False
        return True

    def validate_article(self, article: RawArticle) -> tuple[bool, str]:
        """
        Run all pre-processing validations on an article.

        Returns:
            (is_valid, rejection_reason)
        """
        # 1. AI relevance check
        if not self.is_ai_relevant(article):
            return False, "not_ai_relevant"

        # 2. Content quality
        if not self.has_sufficient_content(article):
            return False, "insufficient_content"

        # 3. Freshness validation
        accept, reason = should_accept_article(article)
        if not accept:
            return False, reason

        return True, "accepted"

    def verify_batch(
        self, articles: list[RawArticle]
    ) -> list[tuple[RawArticle, TrustResult]]:
        """
        Full verification pipeline for a batch of raw articles.

        Steps:
          1. Pre-filter: AI relevance + content + freshness
          2. Group by story for cross-referencing
          3. Assign trust scores with corroboration bonuses

        Args:
            articles: List of raw articles from all fetchers.

        Returns:
            List of (article, TrustResult) tuples for ACCEPTED articles only.
        """
        # Step 1: Pre-filter
        valid_articles: list[RawArticle] = []
        rejected = 0

        for article in articles:
            is_valid, reason = self.validate_article(article)
            if is_valid:
                valid_articles.append(article)
            else:
                rejected += 1
                logger.debug(
                    "article_pre_rejected",
                    title=article.title[:60],
                    reason=reason,
                )

        logger.info(
            "pre_filter_complete",
            total=len(articles),
            valid=len(valid_articles),
            rejected=rejected,
        )

        if not valid_articles:
            return []

        # Step 2: Group by story for cross-referencing
        story_groups = self.cross_ref.group_by_story(valid_articles)

        # Build corroboration map
        corroboration_map: dict[str, int] = {}
        for group_articles in story_groups.values():
            count = self.cross_ref.count_trusted_sources(group_articles)
            for a in group_articles:
                corroboration_map[a.url] = max(count, 1)

        # Step 3: Assign trust scores
        results: list[tuple[RawArticle, TrustResult]] = []

        for article in valid_articles:
            corr_count = corroboration_map.get(article.url, 1)
            trust_result = compute_trust_score(article, corr_count)

            if not trust_result.is_verified:
                logger.debug(
                    "article_trust_rejected",
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

