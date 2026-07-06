"""
AI News Intelligence Engine – Daily Digest Generator
======================================================
Automatically generates the full AI industry digest for a given date.
Produces structured JSON covering:
  - Top 10 AI News Events
  - Top Funding Events
  - Top Research Papers
  - Top Product Launches
  - Top Open Source Releases
  - Top GitHub Repositories
  - Top AI Tools
  - Top AI Companies
  - Trending Technologies
  - AI Market Summary
  - Business Opportunities
  - Risks
  - Predictions (AI-generated)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.news_event import NewsEvent
from app.models.trend import Trend
from app.services.trending_engine import TrendingEngine

logger = get_logger(__name__)


def _event_to_dict(event: NewsEvent) -> dict[str, Any]:
    """Convert a NewsEvent to a lightweight dictionary for the digest."""
    return {
        "id": str(event.id),
        "headline": event.headline,
        "summary": event.summary,
        "category": event.category,
        "event_type": event.event_type,
        "priority_score": round(event.priority_score, 1),
        "companies": event.companies[:5] if event.companies else [],
        "tags": event.tags[:5] if event.tags else [],
        "source_count": event.source_count,
        "source_domains": event.source_domains[:5] if event.source_domains else [],
        "published_at": event.published_at.isoformat() if event.published_at else None,
        "primary_source_url": event.primary_source_url,
        "funding_amount": event.funding_amount,
        "funding_currency": event.funding_currency,
        "arxiv_id": event.arxiv_id,
        "sentiment": event.sentiment,
        "market_impact": event.market_impact,
        "business_opportunities": event.business_opportunities,
    }


class DailyDigestGenerator:
    """
    Generates the full AI industry daily digest.

    Usage:
        generator = DailyDigestGenerator(db)
        digest = await generator.generate(target_date=date.today())
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.trending = TrendingEngine(db)

    async def generate(self, target_date: date | None = None) -> dict[str, Any]:
        """
        Generate the full daily AI industry digest.

        Args:
            target_date: Date to generate digest for (defaults to today UTC).

        Returns:
            Structured digest dictionary.
        """
        if target_date is None:
            target_date = datetime.now(timezone.utc).date()

        # Define the time window (last 24 hours from end of target date)
        period_end = datetime(
            target_date.year, target_date.month, target_date.day,
            23, 59, 59, tzinfo=timezone.utc
        )
        period_start = period_end - timedelta(hours=24)

        logger.info(
            "digest_generation_started",
            date=str(target_date),
            period_start=period_start.isoformat(),
        )

        # Fetch all events for the day
        all_events = await self._fetch_events_for_period(period_start, period_end)

        if not all_events:
            logger.warning("no_events_for_digest", date=str(target_date))

        # Generate each section
        top_10 = self._get_top_news(all_events, 10)
        funding = self._get_funding_events(all_events)
        research = self._get_research_events(all_events)
        product_launches = self._get_product_launches(all_events)
        open_source = self._get_open_source(all_events)
        github_repos = self._get_github_events(all_events)
        ai_tools = self._get_ai_tools(all_events)
        top_companies = self._get_top_companies(all_events)
        trending_tech = await self._get_trending_technologies()

        # AI-generated insights (using Gemini)
        market_summary = await self._generate_market_summary(top_10[:5])
        business_opps = self._extract_business_opportunities(all_events)
        risks = self._extract_risks(all_events)
        predictions = await self._generate_predictions(top_10[:3])

        digest = {
            "date": str(target_date),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_events": len(all_events),
            "breaking_count": sum(1 for e in all_events if e.is_breaking),
            "top_10_news": [_event_to_dict(e) for e in top_10],
            "top_funding": [_event_to_dict(e) for e in funding],
            "top_research_papers": [_event_to_dict(e) for e in research],
            "top_product_launches": [_event_to_dict(e) for e in product_launches],
            "top_open_source": [_event_to_dict(e) for e in open_source],
            "top_github_repos": [_event_to_dict(e) for e in github_repos],
            "top_ai_tools": [_event_to_dict(e) for e in ai_tools],
            "top_companies": top_companies,
            "trending_technologies": trending_tech,
            "market_summary": market_summary,
            "business_opportunities": business_opps,
            "risks": risks,
            "predictions": predictions,
        }

        logger.info(
            "digest_generation_complete",
            date=str(target_date),
            sections=len(digest),
            total_events=len(all_events),
        )

        return digest

    # ── Data Fetching ──────────────────────────────────────────────────────────

    async def _fetch_events_for_period(
        self, start: datetime, end: datetime
    ) -> list[NewsEvent]:
        """Fetch all events published in the given period, sorted by priority."""
        stmt = (
            select(NewsEvent)
            .where(
                and_(
                    NewsEvent.published_at >= start,
                    NewsEvent.published_at <= end,
                )
            )
            .order_by(NewsEvent.priority_score.desc())
            .limit(200)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ── Section Generators ─────────────────────────────────────────────────────

    def _get_top_news(self, events: list[NewsEvent], n: int) -> list[NewsEvent]:
        """Top N events by priority score."""
        return sorted(events, key=lambda e: e.priority_score, reverse=True)[:n]

    def _get_funding_events(self, events: list[NewsEvent]) -> list[NewsEvent]:
        """Events related to AI funding rounds."""
        funding_events = [
            e for e in events
            if e.event_type == "funding" or (e.funding_amount and e.funding_amount > 0)
        ]
        return sorted(
            funding_events,
            key=lambda e: (e.funding_amount or 0),
            reverse=True,
        )[:5]

    def _get_research_events(self, events: list[NewsEvent]) -> list[NewsEvent]:
        """Events related to research papers."""
        research = [
            e for e in events
            if e.event_type in ("research_paper", "benchmark")
            or e.arxiv_id is not None
        ]
        return sorted(research, key=lambda e: e.priority_score, reverse=True)[:5]

    def _get_product_launches(self, events: list[NewsEvent]) -> list[NewsEvent]:
        """Events related to product/model launches."""
        launches = [
            e for e in events
            if e.event_type in ("product_launch", "model_release", "api_release")
        ]
        return sorted(launches, key=lambda e: e.priority_score, reverse=True)[:5]

    def _get_open_source(self, events: list[NewsEvent]) -> list[NewsEvent]:
        """Open source release events."""
        oss = [
            e for e in events
            if e.event_type == "open_source_release"
        ]
        return sorted(oss, key=lambda e: e.priority_score, reverse=True)[:5]

    def _get_github_events(self, events: list[NewsEvent]) -> list[NewsEvent]:
        """GitHub-sourced events (releases, trending repos)."""
        gh = [
            e for e in events
            if any("github.com" in d for d in (e.source_domains or []))
        ]
        return sorted(gh, key=lambda e: e.priority_score, reverse=True)[:5]

    def _get_ai_tools(self, events: list[NewsEvent]) -> list[NewsEvent]:
        """Developer tools and frameworks."""
        tools = [
            e for e in events
            if e.event_type in ("developer_tool", "framework", "coding_ai")
        ]
        return sorted(tools, key=lambda e: e.priority_score, reverse=True)[:5]

    def _get_top_companies(self, events: list[NewsEvent]) -> list[dict]:
        """Aggregate company mentions and return ranked list."""
        from collections import Counter
        company_counter: Counter[str] = Counter()
        company_events: dict[str, list] = {}

        for event in events:
            for company in event.companies or []:
                if company:
                    company_counter[company] += 1
                    company_events.setdefault(company, [])
                    company_events[company].append({
                        "headline": event.headline[:100],
                        "priority": event.priority_score,
                    })

        result = []
        for company, count in company_counter.most_common(10):
            result.append({
                "company": company,
                "mention_count": count,
                "top_events": sorted(
                    company_events.get(company, []),
                    key=lambda x: x["priority"],
                    reverse=True,
                )[:3],
            })
        return result

    async def _get_trending_technologies(self) -> list[dict]:
        """Get trending technologies from the Trend table."""
        trends = await self.trending.get_top_trends(
            trend_type="technology",
            window_hours=24,
            limit=10,
        )
        return [
            {
                "name": t.name,
                "trend_score": t.trend_score,
                "mention_count": t.mention_count,
                "velocity": t.velocity,
                "is_emerging": t.is_emerging,
            }
            for t in trends
        ]

    def _extract_business_opportunities(
        self, events: list[NewsEvent]
    ) -> list[str]:
        """Extract business opportunity snippets from events."""
        opps = []
        for event in events:
            if event.business_opportunities and len(event.business_opportunities) > 20:
                opps.append(event.business_opportunities[:300])
            if len(opps) >= 5:
                break
        return opps

    def _extract_risks(self, events: list[NewsEvent]) -> list[str]:
        """Extract risk snippets from events."""
        risks = []
        for event in events:
            if event.risks and len(event.risks) > 20:
                risks.append(event.risks[:300])
            if len(risks) >= 5:
                break
        return risks

    async def _generate_market_summary(
        self, top_events: list[NewsEvent]
    ) -> str:
        """Generate a Gemini-written market summary based on top events."""
        if not top_events:
            return "No significant AI news events detected for this period."

        headlines = "\n".join(
            f"- {e.headline} (Priority: {e.priority_score:.0f})"
            for e in top_events
        )

        prompt = f"""You are an AI industry analyst writing a daily market summary.
Based on these top AI news events from today, write a 3-4 sentence executive summary of the AI industry landscape:

{headlines}

Write a clear, professional market summary. Focus on major trends, implications, and the overall direction of AI development today."""

        try:
            from app.services.ai.gemini_client import get_gemini_client
            client = get_gemini_client()
            response = await client.generate_text(prompt)
            return response[:800]
        except Exception as exc:
            logger.warning("market_summary_generation_failed", error=str(exc))
            # Fallback: concatenate summaries
            summaries = [e.summary for e in top_events if e.summary]
            return " ".join(summaries[:3])[:600] if summaries else "AI market activity continues."

    async def _generate_predictions(
        self, top_events: list[NewsEvent]
    ) -> list[str]:
        """Generate short-term predictions based on current events."""
        if not top_events:
            return []

        headlines = "\n".join(f"- {e.headline}" for e in top_events)

        prompt = f"""Based on today's top AI news:
{headlines}

Generate 3 specific, short-term predictions (1-4 weeks) for the AI industry. Each prediction should be a single sentence, starting with "Expect" or a company/technology name. Be specific and insightful."""

        try:
            from app.services.ai.gemini_client import get_gemini_client
            client = get_gemini_client()
            response = await client.generate_text(prompt)
            # Parse predictions (one per line, filter empty)
            predictions = [
                line.strip().lstrip("0123456789.-) ")
                for line in response.split("\n")
                if len(line.strip()) > 20
            ]
            return predictions[:3]
        except Exception as exc:
            logger.warning("predictions_generation_failed", error=str(exc))
            return []
