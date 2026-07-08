"""
AI Pulse - Mentor Suggestion Engine
===================================
Generates grounded, varied career/action suggestions from a daily brief.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from app.models.news_article import NewsArticle
from app.models.user import User, UserPreferences

MENTOR_MIN_RELEVANCE = 55.0

EVERGREEN_BACKLOG = [
    {
        "topic": "AI agents",
        "tool": "Model Context Protocol",
        "action": "Build a tiny tool-calling workflow and write down where context breaks.",
    },
    {
        "topic": "LLM evaluation",
        "tool": "promptfoo or OpenAI Evals",
        "action": "Create three task-specific checks for a feature you already know well.",
    },
    {
        "topic": "retrieval systems",
        "tool": "FAISS or pgvector",
        "action": "Compare one keyword query against one embedding query on the same notes.",
    },
    {
        "topic": "model deployment",
        "tool": "vLLM",
        "action": "Read one deployment guide and list the serving bottlenecks it solves.",
    },
]

TEMPLATES = [
    "Focus on {topic} today. Try {tool}, because {reason}. Action: {action}",
    "A useful career move today is {topic}: explore {tool}. The signal is {reason}. Next step: {action}",
    "Your brief points toward {topic}. Use {tool} as the hands-on anchor; {reason}. Then {action}",
    "For skill growth, spend one focused block on {topic}. {tool} is the practical entry point because {reason}. {action}",
    "Today's best mentor nudge: {topic}. Pair it with {tool}; {reason}. Keep it concrete: {action}",
]


@dataclass(frozen=True)
class MentorSuggestion:
    message: str
    topic: str
    tool: str
    action: str
    reason: str
    article_id: str | None
    fallback: bool = False


def _article_metadata(article: NewsArticle) -> set[str]:
    analysis = article.analysis
    values = [
        article.title,
        article.description,
        article.source_domain,
    ]
    if analysis:
        values.extend([
            analysis.summary,
            analysis.category,
            analysis.subcategory,
            analysis.event_type,
            analysis.why_it_matters,
        ])
        for seq in (
            analysis.tags,
            analysis.keywords,
            analysis.companies,
            analysis.products_mentioned,
            analysis.technologies_mentioned,
            analysis.models_mentioned,
        ):
            values.extend(seq or [])
    return {str(v).strip().lower() for v in values if v}


def _pick_template(user_id: str, target_date: date) -> str:
    seed = f"{user_id}:{target_date.isoformat()}".encode("utf-8")
    idx = int(hashlib.sha256(seed).hexdigest(), 16) % len(TEMPLATES)
    return TEMPLATES[idx]


class MentorEngine:
    """Builds one grounded mentor suggestion for a user/day."""

    def build(
        self,
        user: User,
        articles: list[NewsArticle],
        preferences: UserPreferences | None = None,
        target_date: date | None = None,
    ) -> MentorSuggestion:
        target_date = target_date or date.today()
        best = self._best_article(articles, preferences)
        template = _pick_template(str(user.id), target_date)

        if not best:
            return self._fallback(template, user, target_date)

        topic, tool, reason, action = self._grounded_fields(best)
        if not self._reason_is_grounded(best, reason):
            return self._fallback(template, user, target_date)

        return MentorSuggestion(
            message=template.format(topic=topic, tool=tool, reason=reason, action=action),
            topic=topic,
            tool=tool,
            action=action,
            reason=reason,
            article_id=str(best.id),
            fallback=False,
        )

    def _best_article(
        self,
        articles: list[NewsArticle],
        preferences: UserPreferences | None,
    ) -> NewsArticle | None:
        if not articles:
            return None
        blocked = {b.lower() for b in (preferences.blocked_topics if preferences else [])}
        ranked = []
        for article in articles:
            metadata = _article_metadata(article)
            if any(blocked_term in metadata for blocked_term in blocked):
                continue
            score = max(article.final_score or 0.0, article.priority_score or 0.0)
            if preferences and article.analysis:
                if article.analysis.category in (preferences.favorite_categories or []):
                    score += 8
                if set(article.analysis.companies or []) & set(preferences.favorite_companies or []):
                    score += 6
            if score >= MENTOR_MIN_RELEVANCE:
                ranked.append((score, article))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1] if ranked else None

    def _grounded_fields(self, article: NewsArticle) -> tuple[str, str, str, str]:
        analysis = article.analysis
        topic = "AI practice"
        tool = "a small prototype"
        reason = article.title[:120]
        action = "Skim the source, then write one implementation note you can reuse."

        if analysis:
            topic = analysis.category or topic
            tool = (
                (analysis.products_mentioned or [None])[0]
                or (analysis.technologies_mentioned or [None])[0]
                or (analysis.models_mentioned or [None])[0]
                or (analysis.keywords or [None])[0]
                or tool
            )
            if analysis.summary:
                reason = analysis.summary[:180]
            elif analysis.tags:
                reason = f"the article is tagged {analysis.tags[0]}"
            if analysis.event_type in {"model_release", "api_release", "developer_tool", "framework"}:
                action = "Read the docs or release notes and build a 30-minute toy integration."
            elif analysis.event_type == "research_paper":
                action = "Read the abstract and reproduce one diagram, metric, or limitation in your own words."
            elif analysis.event_type == "security_incident":
                action = "Check whether your current stack has exposure and note one mitigation."

        return topic, tool, reason, action

    def _reason_is_grounded(self, article: NewsArticle, reason: str) -> bool:
        reason_lower = reason.lower()
        metadata = _article_metadata(article)
        return any(
            item and (item in reason_lower or reason_lower[:60] in item)
            for item in metadata
        )

    def _fallback(self, template: str, user: User, target_date: date) -> MentorSuggestion:
        seed = f"fallback:{user.id}:{target_date.isoformat()}".encode("utf-8")
        item = EVERGREEN_BACKLOG[int(hashlib.sha256(seed).hexdigest(), 16) % len(EVERGREEN_BACKLOG)]
        reason = "today's brief did not have a strong enough profile match"
        return MentorSuggestion(
            message=template.format(
                topic=item["topic"],
                tool=item["tool"],
                reason=reason,
                action=item["action"],
            ),
            topic=item["topic"],
            tool=item["tool"],
            action=item["action"],
            reason=reason,
            article_id=None,
            fallback=True,
        )
