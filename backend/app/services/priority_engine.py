"""
AI News Intelligence Engine – Priority Engine
===============================================
Computes a composite Priority Score (0–100) for each NewsEvent.

Priority tiers:
  95–100  🚨  Breaking
  80–94   🔥  Very Important
  60–79   📌  Important
  40–59   📰  Medium
  0–39    📄  Low
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Priority Tier Thresholds ──────────────────────────────────────────────────
TIER_BREAKING = 95.0
TIER_VERY_IMPORTANT = 80.0
TIER_IMPORTANT = 60.0
TIER_MEDIUM = 40.0

# ── Scoring Weights ────────────────────────────────────────────────────────────
WEIGHTS = {
    "freshness":       0.20,  # How recently published
    "source_trust":    0.20,  # Trust level of covering sources
    "source_count":    0.10,  # Number of independent sources
    "industry_impact": 0.15,  # Industry-wide significance
    "research_sig":    0.10,  # Research paper significance
    "product_launch":  0.10,  # Whether it's a new product/model
    "funding":         0.05,  # Funding amount
    "gov_regulation":  0.05,  # Government / policy event
    "social_signal":   0.05,  # Community engagement
}

# ── Source Trust Tiers ─────────────────────────────────────────────────────────
OFFICIAL_DOMAINS = {
    "openai.com", "anthropic.com", "deepmind.google", "blog.research.google",
    "ai.meta.com", "blogs.microsoft.com", "blogs.nvidia.com",
    "huggingface.co", "mistral.ai", "x.ai", "perplexity.ai",
    "stability.ai", "cohere.com",
}

TIER1_DOMAINS = {
    "reuters.com", "bloomberg.com", "technologyreview.com",
    "techcrunch.com", "venturebeat.com", "arxiv.org", "paperswithcode.com",
}

TIER2_DOMAINS = {
    "wired.com", "theverge.com", "arstechnica.com", "zdnet.com",
    "github.com", "news.ycombinator.com",
}

# ── Event Type Impact Bonuses ──────────────────────────────────────────────────
EVENT_TYPE_BONUSES: dict[str, float] = {
    "model_release":        25.0,  # New AI model release
    "product_launch":       20.0,  # Major product launch
    "funding":              15.0,  # Significant funding round
    "acquisition":          20.0,  # Acquisition/merger
    "research_paper":       10.0,  # Novel research
    "benchmark":            12.0,  # New SOTA benchmark
    "open_source_release":  15.0,  # Major OSS release
    "security_incident":    18.0,  # AI safety/security
    "government_regulation":20.0,  # Regulatory action
    "startup_launch":       8.0,   # New AI startup
    "api_release":          10.0,  # New API
    "infrastructure":       8.0,   # Infrastructure/compute
    "gpu":                  12.0,  # GPU/hardware
    "ai_agent":             15.0,  # AI agent systems
    "robotics":             12.0,  # AI robotics
    "developer_tool":       10.0,  # Developer tooling
    "framework":            10.0,  # ML framework
    "coding_ai":            12.0,  # AI for coding
    "healthcare_ai":        10.0,  # Healthcare AI
    "finance_ai":           8.0,   # Finance AI
    "education_ai":         6.0,   # Education AI
}

# ── High-Impact Company Bonus ──────────────────────────────────────────────────
HIGH_IMPACT_COMPANIES = {
    "OpenAI", "Anthropic", "Google", "Google DeepMind", "Microsoft",
    "Meta", "NVIDIA", "Apple", "Amazon", "Tesla", "xAI",
}


@dataclass
class PriorityResult:
    """Result of the Priority Engine calculation."""
    priority_score: float                        # 0–100
    freshness_score: float                       # 0–100 component
    trust_score: float                           # 0–100 component
    impact_score: float                          # 0–100 component
    tier: str                                    # breaking/very_important/important/medium/low
    is_breaking: bool
    factors: dict[str, float] = field(default_factory=dict)


def compute_freshness_score(published_at: datetime | None) -> float:
    """
    Compute freshness score (0–100) based on publication age.

    Decay curve:
      0h  → 100.0
      2h  → 95.0
      6h  → 80.0
      12h → 60.0
      24h → 40.0
      48h → 20.0
      72h → 10.0
      7d+ → 2.0
    """
    if published_at is None:
        return 30.0

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    age_hours = max(0.0, (now - published_at).total_seconds() / 3600)

    if age_hours < 2:
        return 100.0
    elif age_hours < 6:
        return 100.0 - (age_hours - 2) * 3.75  # 100 → 85
    elif age_hours < 12:
        return 85.0 - (age_hours - 6) * 4.17   # 85 → 60
    elif age_hours < 24:
        return 60.0 - (age_hours - 12) * 1.67  # 60 → 40
    elif age_hours < 48:
        return 40.0 - (age_hours - 24) * 0.83  # 40 → 20
    elif age_hours < 168:  # 7 days
        return max(5.0, 20.0 - (age_hours - 48) * 0.125)
    else:
        return 2.0


def compute_source_trust_score(source_domains: list[str]) -> float:
    """
    Compute aggregate trust score from all covering source domains.
    Returns 0–100.
    """
    if not source_domains:
        return 20.0

    domain_set = {d.lower() for d in source_domains}
    has_official = bool(domain_set & OFFICIAL_DOMAINS)
    has_tier1 = bool(domain_set & TIER1_DOMAINS)
    has_tier2 = bool(domain_set & TIER2_DOMAINS)

    if has_official:
        base = 90.0
    elif has_tier1:
        base = 70.0
    elif has_tier2:
        base = 55.0
    else:
        base = 30.0

    # Multi-source bonus (more sources = higher trust)
    source_bonus = min(10.0, len(domain_set) * 2.0)

    return min(100.0, base + source_bonus)


def compute_source_count_score(source_count: int) -> float:
    """
    Score based on number of independent sources covering the event.
    1 source → 20, 2 → 40, 3 → 60, 5+ → 90, 10+ → 100
    """
    if source_count <= 0:
        return 10.0
    # Logarithmic scale: diminishing returns beyond 5 sources
    return min(100.0, 20.0 * (1 + math.log(source_count, 2)))


def compute_funding_score(funding_amount_usd_millions: float | None) -> float:
    """
    Score funding events by amount (USD millions).
    $10M → 20, $50M → 50, $100M → 70, $500M → 90, $1B+ → 100
    """
    if not funding_amount_usd_millions or funding_amount_usd_millions <= 0:
        return 0.0
    amount = funding_amount_usd_millions
    if amount >= 1000:
        return 100.0
    elif amount >= 500:
        return 90.0
    elif amount >= 100:
        return 70.0
    elif amount >= 50:
        return 50.0
    elif amount >= 10:
        return 30.0
    else:
        return 15.0


class PriorityEngine:
    """
    Computes the composite Priority Score for a news event.

    Usage:
        engine = PriorityEngine()
        result = engine.compute(
            published_at=event.published_at,
            source_domains=event.source_domains,
            source_count=event.source_count,
            event_type=event.event_type,
            companies=event.companies,
            funding_amount=event.funding_amount,
            sentiment=event.sentiment,
        )
    """

    def compute(
        self,
        published_at: datetime | None,
        source_domains: list[str],
        source_count: int,
        event_type: str | None = None,
        companies: list[str] | None = None,
        funding_amount: float | None = None,
        sentiment: str = "neutral",
        is_research: bool = False,
        is_government: bool = False,
        social_score: float = 0.0,
    ) -> PriorityResult:
        """
        Compute the priority score for an event.

        Args:
            published_at: Publication timestamp of the earliest source.
            source_domains: List of domains covering this event.
            source_count: Number of independent sources.
            event_type: Classified event type (model_release, funding, etc.).
            companies: List of companies mentioned.
            funding_amount: Funding amount in USD millions.
            sentiment: Article sentiment (positive/negative/neutral).
            is_research: Whether this is a research paper event.
            is_government: Whether this involves government/regulation.
            social_score: External social engagement score (0–100).

        Returns:
            PriorityResult with full breakdown.
        """
        companies = companies or []

        # ── Component Scores ─────────────────────────────────────────────────
        freshness = compute_freshness_score(published_at)
        trust = compute_source_trust_score(source_domains)
        src_count_score = compute_source_count_score(source_count)

        # Industry impact: base from event type + company importance
        event_bonus = EVENT_TYPE_BONUSES.get(event_type or "", 0.0) if event_type else 0.0
        company_bonus = min(20.0, sum(
            10.0 if c in HIGH_IMPACT_COMPANIES else 3.0
            for c in companies
        ))
        industry_impact = min(100.0, 30.0 + event_bonus + company_bonus)

        # Research significance
        research_sig = 70.0 if is_research else 0.0
        if event_type == "research_paper":
            research_sig = 70.0
        elif event_type == "benchmark":
            research_sig = 60.0

        # Product launch score
        product_launch_score = 80.0 if event_type in (
            "model_release", "product_launch", "open_source_release", "api_release"
        ) else 0.0

        # Funding score
        funding_score = compute_funding_score(funding_amount)
        if event_type == "funding" and funding_amount:
            funding_score = max(funding_score, 40.0)

        # Government/regulation score
        gov_score = 80.0 if (is_government or event_type == "government_regulation") else 0.0

        # Social signal
        social = min(100.0, social_score)

        # ── Weighted Sum ─────────────────────────────────────────────────────
        raw = (
            freshness        * WEIGHTS["freshness"]
            + trust          * WEIGHTS["source_trust"]
            + src_count_score * WEIGHTS["source_count"]
            + industry_impact * WEIGHTS["industry_impact"]
            + research_sig   * WEIGHTS["research_sig"]
            + product_launch_score * WEIGHTS["product_launch"]
            + funding_score  * WEIGHTS["funding"]
            + gov_score      * WEIGHTS["gov_regulation"]
            + social         * WEIGHTS["social_signal"]
        )

        # Clamp to [0, 100]
        priority = round(min(100.0, max(0.0, raw)), 2)

        # ── Determine Tier ────────────────────────────────────────────────────
        if priority >= TIER_BREAKING:
            tier = "breaking"
            is_breaking = True
        elif priority >= TIER_VERY_IMPORTANT:
            tier = "very_important"
            is_breaking = False
        elif priority >= TIER_IMPORTANT:
            tier = "important"
            is_breaking = False
        elif priority >= TIER_MEDIUM:
            tier = "medium"
            is_breaking = False
        else:
            tier = "low"
            is_breaking = False

        # Breaking also requires freshness (< 4 hours old)
        if is_breaking:
            age_h = (datetime.now(timezone.utc) - (published_at or datetime.now(timezone.utc))).total_seconds() / 3600
            if age_h > 4:
                is_breaking = False
                tier = "very_important" if priority >= TIER_VERY_IMPORTANT else tier

        factors = {
            "freshness": freshness,
            "source_trust": trust,
            "source_count": src_count_score,
            "industry_impact": industry_impact,
            "research_sig": research_sig,
            "product_launch": product_launch_score,
            "funding": funding_score,
            "gov_regulation": gov_score,
            "social_signal": social,
        }

        logger.debug(
            "priority_computed",
            score=priority,
            tier=tier,
            event_type=event_type,
            freshness=round(freshness, 1),
            trust=round(trust, 1),
        )

        return PriorityResult(
            priority_score=priority,
            freshness_score=freshness,
            trust_score=trust,
            impact_score=industry_impact,
            tier=tier,
            is_breaking=is_breaking,
            factors=factors,
        )

    def get_tier_label(self, score: float) -> str:
        """Return a human-readable tier label for a priority score."""
        if score >= TIER_BREAKING:
            return "🚨 Breaking"
        elif score >= TIER_VERY_IMPORTANT:
            return "🔥 Very Important"
        elif score >= TIER_IMPORTANT:
            return "📌 Important"
        elif score >= TIER_MEDIUM:
            return "📰 Medium"
        else:
            return "📄 Low"

    def get_notification_emoji(self, event_type: str | None, companies: list[str]) -> str:
        """Return notification emoji based on event type."""
        emoji_map = {
            "model_release":        "🤖",
            "product_launch":       "🚀",
            "funding":              "💰",
            "acquisition":          "🤝",
            "research_paper":       "📄",
            "benchmark":            "📊",
            "open_source_release":  "🔓",
            "security_incident":    "⚠️",
            "government_regulation":"⚖️",
            "gpu":                  "📈",
            "ai_agent":             "🧠",
            "robotics":             "🤖",
            "coding_ai":            "💻",
        }
        return emoji_map.get(event_type or "", "📰")
