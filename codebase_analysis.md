# AI News – Deep Codebase Analysis

> **Last updated:** July 2026  
> **App name:** AI News (formerly AI Pulse)  
> **Version:** 2.4.0  
> **Stack:** FastAPI · SQLAlchemy 2.0 · PostgreSQL (Supabase) · Upstash Redis · Gemini AI · Firebase FCM · Vanilla JS SPA

---

## Table of Contents

1.  [High-Level Architecture](#1-high-level-architecture)
2.  [Repository Layout](#2-repository-layout)
3.  [Backend Entry Point – `main.py`](#3-backend-entry-point--mainpy)
4.  [Configuration System – `core/config.py`](#4-configuration-system--coreconfigpy)
5.  [Database Layer](#5-database-layer)
6.  [ORM Models (Database Schema)](#6-orm-models-database-schema)
7.  [News Ingestion – Fetchers & Orchestrator](#7-news-ingestion--fetchers--orchestrator)
8.  [5-Layer Duplicate Detection Engine](#8-5-layer-duplicate-detection-engine)
9.  [Event Clustering Engine](#9-event-clustering-engine)
10. [Gemini AI Enrichment](#10-gemini-ai-enrichment)
11. [Priority & Ranking Engine](#11-priority--ranking-engine)
12. [Freshness Engine](#12-freshness-engine)
13. [Trending Engine](#13-trending-engine)
14. [Digest Generator](#14-digest-generator)
15. [Personalization & Daily Brief](#15-personalization--daily-brief)
16. [Notification System (Firebase FCM)](#16-notification-system-firebase-fcm)
17. [Upstash Redis Cache Layer](#17-upstash-redis-cache-layer)
18. [Scheduler – APScheduler Jobs](#18-scheduler--apscheduler-jobs)
19. [API Layer – All Endpoints](#19-api-layer--all-endpoints)
20. [Frontend SPA – `index.html`](#20-frontend-spa--indexhtml)
21. [Frontend – Theme System (Dark / Light Mode)](#21-frontend--theme-system-dark--light-mode)
22. [Frontend – Settings Panel](#22-frontend--settings-panel)
23. [Frontend – News Feed Rendering](#23-frontend--news-feed-rendering)
24. [Frontend – Bookmarks System](#24-frontend--bookmarks-system)
25. [Frontend – Sources Management Panel](#25-frontend--sources-management-panel)
26. [Frontend – AI Insights View](#26-frontend--ai-insights-view)
27. [Middleware Stack](#27-middleware-stack)
28. [Auth System – JWT + Supabase](#28-auth-system--jwt--supabase)
29. [Search Service](#29-search-service)
30. [ngrok – Mobile Testing Tunnel](#30-ngrok--mobile-testing-tunnel)
31. [Environment Variables Reference](#31-environment-variables-reference)
32. [Data Flow – End-to-End Journey of One Article](#32-data-flow--end-to-end-journey-of-one-article)

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        30 NEWS SOURCES                          │
│  Official Blogs · RSS Feeds · Scrapers · ArXiv · GitHub · HN    │
└────────────────────────────┬────────────────────────────────────┘
                             │ every 2 hours (APScheduler)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                 NEWS FETCH ORCHESTRATOR                         │
│  Runs all fetchers concurrently (asyncio.gather)                │
│  Returns URL-deduplicated list of RawArticle objects            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              VERIFICATION ENGINE                                │
│  AI-relevance filter · Domain trust · Freshness pre-check       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│           5-LAYER DUPLICATE DETECTION ENGINE                    │
│  L1: Exact URL  L2: Title hash  L3: Content hash                │
│  L4: Gemini embedding cosine similarity  L5: Entity fingerprint │
└────────────────────────────┬────────────────────────────────────┘
                             │ new unique articles only
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  DATABASE SAVE (PostgreSQL)                     │
│  NewsSource · NewsArticle tables                                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              EVENT CLUSTERING ENGINE                            │
│  Within-batch: Jaccard title similarity + entity overlap        │
│  Cross-batch: Gemini embedding cosine ≥ 0.88 (72h window)       │
│  Creates / updates NewsEvent records                            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│           GEMINI AI ENRICHMENT (25 fields)                      │
│  Summary · Takeaways · Entities · Sentiment · Market impact     │
│  Risk assessment · Predictions · Importance score (0-100)       │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              PRIORITY & RANKING ENGINE                          │
│  Weighted score: freshness · trust · source_count · impact      │
│  Tiers: Breaking(95+) · Very Important(80+) · Important(60+)    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
           ┌───────────────┐  ┌───────────────────┐
           │  FASTAPI API  │  │  TRENDING ENGINE  │
           │  (REST layer) │  │  6h · 24h · 7d    │
           └──────┬────────┘  └───────────────────┘
                  │
          ┌───────┴──────────┐
          ▼                  ▼
  ┌───────────────┐  ┌─────────────────┐
  │ Upstash Redis │  │ Frontend SPA    │
  │ (cache TTL)   │  │ index.html      │
  └───────────────┘  │ Vanilla JS      │
                     └─────────────────┘
```

---

## 2. Repository Layout

```
AI-News/
├── .gitignore                  ← Root-level ignores (venv, .env, ngrok, logs…)
├── README.md
├── codebase_analysis.md        ← THIS FILE
├── venv/                       ← Python virtual environment (gitignored)
├── ngrok/                      ← ngrok binary for mobile testing (gitignored)
│
└── backend/
    ├── .env                    ← Secret keys (gitignored)
    ├── .env.example            ← Template for new developers
    ├── .gitignore              ← Backend-specific ignores
    ├── requirements.txt        ← All Python dependencies
    ├── Dockerfile              ← Production container build
    ├── docker-compose.yml      ← Local stack orchestration
    ├── pytest.ini
    │
    └── app/
        ├── main.py             ← FastAPI app factory + lifespan manager
        ├── core/
        │   ├── config.py       ← Pydantic BaseSettings (all env vars)
        │   └── logging.py      ← Structured JSON logging setup
        ├── api/
        │   └── v1/
        │       ├── auth.py         ← JWT auth endpoints
        │       ├── news.py         ← Articles, sources, bookmarks API
        │       ├── routers.py      ← Users, prefs, notifs, admin…
        │       └── intelligence.py ← Events, trends, digest, suggestions
        ├── database/
        │   └── connection.py   ← AsyncSession factory, engine, health check
        ├── middleware/
        │   └── __init__.py     ← CORS, rate limiting, security headers
        ├── models/             ← SQLAlchemy ORM table definitions
        ├── schemas/            ← Pydantic v2 request/response models
        ├── services/
        │   ├── ai/             ← Gemini API client + enrichment logic
        │   ├── cache/          ← Upstash Redis REST client
        │   ├── duplicate_detection/ ← 5-layer dedup engine
        │   ├── news_fetchers/  ← RSS, scrapers, ArXiv, GitHub fetchers
        │   ├── notifications/  ← Firebase FCM dispatcher
        │   ├── personalization/ ← User-specific feed personalization
        │   ├── ranking/        ← Feed ranking helpers
        │   ├── verification/   ← Source trust + AI relevance filter
        │   ├── digest_generator.py
        │   ├── event_clustering.py
        │   ├── freshness_engine.py
        │   ├── priority_engine.py
        │   ├── search_service.py
        │   └── trending_engine.py
        ├── scheduler/
        │   ├── scheduler.py    ← APScheduler instance + job registration
        │   └── jobs.py         ← All 9 async job implementations
        ├── templates/
        │   ├── index.html      ← Full SPA frontend (Vanilla JS, ~3500 lines)
        │   ├── logo.png        ← App logo for dark mode
        │   └── logo_light.png  ← App logo for light mode
        └── utils/
            ├── text_utils.py   ← Hashing, fingerprinting, normalization
            └── date_utils.py   ← UTC helpers, age calculations
```

---

## 3. Backend Entry Point – `main.py`

`main.py` uses the **Application Factory** pattern to avoid circular imports and make testing easier.

### Startup Sequence (lifespan manager)

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # 1. check_database_connection()  ← Verifies PostgreSQL is reachable
    # 2. create_all_tables()           ← Only in dev/testing (Alembic in prod)
    # 3. setup_scheduler().start()     ← Starts APScheduler with all 9 jobs
    yield
    # Shutdown:
    # 4. scheduler.shutdown()
    # 5. dispose_engine()             ← Closes DB connection pool cleanly
```

### Static File Routes

In addition to all API routes, `main.py` registers three static-file routes directly on the FastAPI app:

| Route                 | Handler              | Purpose                                       |
| --------------------- | -------------------- | --------------------------------------------- |
| `GET /`               | `serve_index()`      | Serves `index.html` as the SPA shell          |
| `GET /logo.png`       | `serve_logo()`       | Dark mode app logo                            |
| `GET /logo_light.png` | `serve_logo_light()` | Light mode app logo (falls back to dark logo) |

### Router Registration

All API prefixes are versioned under `/api/v1` (set via `settings.api_prefix`). Routers registered:

```
health_router          → GET /health
auth_router            → /api/v1/auth/*
users_router           → /api/v1/users/*
preferences_router     → /api/v1/preferences/*
news_router            → /api/v1/news/*
brief_router           → /api/v1/brief/*
bookmarks_router       → /api/v1/bookmarks/*
categories_router      → /api/v1/categories/*
notifications_router   → /api/v1/notifications/*
admin_router           → /api/v1/admin/*
intelligence_router    → /api/v1/intelligence/*
```

---

## 4. Configuration System – `core/config.py`

All configuration is loaded from the `.env` file via **Pydantic BaseSettings**. This means:

- Every setting is type-validated at startup
- Required fields (marked with `Field(...)`) will raise a `ValidationError` if missing — fast fail before the app serves any traffic
- Sensitive keys never need to be hardcoded

Key settings groups:

| Group         | Variables                                                                                              |
| ------------- | ------------------------------------------------------------------------------------------------------ |
| App           | `app_env`, `app_name`, `app_version`, `log_level`, `secret_key`                                        |
| Database      | `supabase_url`, `database_url`, `supabase_jwt_secret`                                                  |
| Gemini AI     | `gemini_api_key`, `gemini_model` (`gemini-2.0-flash`), `gemini_embedding_model` (`text-embedding-004`) |
| Firebase      | `firebase_credentials_json` or `firebase_credentials_path`                                             |
| Redis         | `upstash_redis_rest_url`, `upstash_redis_rest_token`                                                   |
| Scheduler     | `scheduler_timezone`, `daily_brief_hour`, `daily_brief_minute`                                         |
| Rate Limiting | `rate_limit_per_minute_authenticated` (100), `rate_limit_per_minute_anonymous` (20)                    |
| CORS          | `cors_origins` (comma-separated string → list via validator)                                           |

---

## 5. Database Layer

**File:** `app/database/connection.py`

Uses **SQLAlchemy 2.0 async** with `AsyncSession`:

```python
engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,     ← Detects stale connections before use
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

Every request gets a fresh `AsyncSession` via FastAPI's dependency injection:

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

---

## 6. ORM Models (Database Schema)

### `User` — `users` table

Stores registered users. Fields: `id` (UUID), `email`, `hashed_password`, `display_name`, `fcm_token` (for push notifications), `is_active`, `created_at`, `last_login_at`.

### `UserPreferences` — `user_preferences` table

One-to-one with `User`. Stores JSON arrays:

- `preferred_categories` — e.g. `["model_release", "research", "funding"]`
- `preferred_companies` — e.g. `["OpenAI", "Anthropic"]`
- `preferred_topics` — e.g. `["LLMs", "robotics"]`
- `notification_settings` — push notification frequency/type preferences
- `bookmarked_article_ids` — list of bookmarked article UUIDs

### `NewsSource` — `news_sources` table

Each scraper/feed is a row here. Managed through the UI. Fields:

- `name` (unique key, e.g. `"techcrunch_ai"`)
- `display_name`, `domain`, `url`, `source_type` (`rss`/`scrape`/`api`)
- `is_active` — can be toggled from the frontend
- `reliability_score` (0–100, updated after each run)
- `consecutive_failures` — incremented on failure, resets on success
- `total_articles_fetched`

### `NewsArticle` — `news_articles` table

Raw article storage. Key fields:

- `url` (normalized, unique), `title`, `description`, `content_snippet`
- `source_name`, `source_domain`, `is_official`
- `published_at`, `fetched_at`
- `is_duplicate`, `canonical_article_id` (FK to self — duplicate chain)
- `title_fingerprint`, `content_fingerprint`, `embedding` (float array for semantic dedup)
- `event_id` (FK to `NewsEvent`)

### `NewsAnalysis` — `news_analyses` table

One-to-one with `NewsArticle`. All 25 Gemini-enriched fields:

- `summary`, `key_takeaways` (JSON list), `entities` (JSON: companies, people, technologies)
- `event_type` (e.g. `"model_release"`, `"funding"`, `"research_paper"`)
- `sentiment` (`positive`/`negative`/`neutral`)
- `importance_score` (0–100)
- `industry_impact`, `market_implications`, `technical_significance`
- `risk_factors`, `business_opportunities`
- `predictions` (short-term, long-term)
- `affected_industries` (JSON list)

### `NewsEvent` — `news_events` table

A cluster of articles covering the same story. Fields:

- `title`, `summary`, `event_type`
- `priority_score` (0–100, computed by Priority Engine)
- `tier` (`breaking`/`very_important`/`important`/`medium`/`low`)
- `is_breaking`
- `source_count` — how many independent sources covered this
- `article_ids` (JSON array of article UUIDs)
- `source_domains` (JSON array)
- `first_seen_at`, `last_updated_at`

### `Trend` — `trends` table

Trending signals over rolling windows. Fields:

- `trend_type` (`company`/`model`/`topic`/`keyword`/`repository`/`framework`)
- `term` — the entity name
- `window_hours` (6, 24, or 168)
- `mention_count`, `velocity_score` (growth rate vs previous window)
- `event_ids` (JSON — which events mention this term)

### `Bookmark` — `bookmarks` table

User reading list. Simple junction: `user_id` + `article_id` + `bookmarked_at`.

### `DailyBrief` — `daily_briefs` table

Personalized daily feed snapshots. Fields: `user_id`, `date`, `article_ids` (JSON), `generated_at`.

### `Notification` — `notifications` table

FCM push notification history. Fields: `user_id`, `title`, `body`, `article_id`, `sent_at`, `status`.

---

## 7. News Ingestion – Fetchers & Orchestrator

**Directory:** `app/services/news_fetchers/`

### Source Trust Tiers

| Tier | Category                | Sources                                                                  |
| ---- | ----------------------- | ------------------------------------------------------------------------ |
| 0    | Official company blogs  | OpenAI, Google AI, DeepMind, Hugging Face                                |
| 1    | Research + Tier-1 media | ArXiv, TechCrunch, VentureBeat, MIT Tech Review, Bloomberg, Ars Technica |
| 2    | Developer + community   | GitHub Trending, GitHub Releases, Hacker News, Product Hunt              |
| 3    | Aggregators             | Google News AI                                                           |

### Fetcher Types

**`rss_fetcher.py`** — Standard RSS/Atom feed parsers:

- Uses `feedparser` to parse XML feeds
- Normalizes dates to UTC, extracts title + description + link
- Returns list of `RawArticle` dataclass objects

**`scrapers.py`** — Web scrapers for sites without RSS:

- `OpenAIFetcher` — scrapes blog.openai.com
- `GoogleNewsFetcher` — uses Google News RSS with AI query
- `GitHubTrendingFetcher` — scrapes github.com/trending filtered for AI repos
- `ProductHuntAIFetcher` — scrapes Product Hunt for AI products

**`arxiv_fetcher.py`** — ArXiv API:

- Queries ArXiv API for recent `cs.AI`, `cs.LG`, `cs.CL` papers
- Extracts abstract as description, authors as entities

**`community_fetchers.py`** — Community aggregators:

- `HackerNewsFetcher` — HN Algolia API, filters by AI keyword scoring
- `GitHubReleasesFetcher` — GitHub REST API for AI-tagged repo releases

### `RawArticle` Dataclass

Every fetcher returns `RawArticle` objects:

```python
@dataclass
class RawArticle:
    url: str
    title: str
    source_name: str
    source_domain: str
    description: str | None
    content_snippet: str | None
    published_at: datetime | None
    is_official: bool = False
    author: str | None = None
    tags: list[str] = field(default_factory=list)
```

### Orchestrator Logic

`NewsFetchOrchestrator.fetch_all()`:

1. Queries `NewsSource` table for active sources
2. Maps each source name to its fetcher class
3. Runs all fetchers concurrently with `asyncio.gather(..., return_exceptions=True)`
4. Collects results, logs individual fetcher failures (they don't abort the pipeline)
5. Deduplicates by URL within the batch (pre-DB check)
6. Returns the combined list of `RawArticle` objects

---

## 8. 5-Layer Duplicate Detection Engine

**File:** `app/services/duplicate_detection/engine.py`

Every new article passes through five layers before being saved to the database. The layers are ordered cheapest → most expensive, and the check short-circuits at the first match.

### Layer 1 — Exact URL Match

Normalizes the URL (strips tracking params, trailing slashes, lowercases scheme+host) and checks for an exact match in `news_articles.url`.

```
Normalization: remove utm_*, fbclid, etc. → lowercase → strip trailing /
Cost: Single indexed DB lookup (O(1))
```

### Layer 2 — Normalized Title Hash

Strips punctuation, lowercases, removes stopwords, then SHA-256 hashes the result. Checks `news_articles.title_fingerprint`.

```python
def title_fingerprint(title: str) -> str:
    normalized = re.sub(r'[^\w\s]', '', title.lower())
    tokens = [t for t in normalized.split() if t not in STOPWORDS]
    return hashlib.sha256(' '.join(tokens).encode()).hexdigest()
```

Catches: same article re-published with minor title formatting differences.

### Layer 3 — Content Fingerprint

SHA-256 of the normalized title + first 200 chars of content snippet. Stored in `news_articles.content_fingerprint`.

Catches: same article re-published with different URL patterns (e.g. `/ai/` vs `/technology/`).

### Layer 4 — Gemini Semantic Embedding

For articles that pass layers 1-3, generates a 768-dimensional embedding via `gemini text-embedding-004`. Then computes **cosine similarity** against recent articles (last 48h) that have embeddings stored.

```python
def cosine_similarity(v1, v2) -> float:
    a, b = np.array(v1), np.array(v2)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

# Threshold: similarity >= 0.92 → duplicate
```

Catches: paraphrased versions of the same story from different outlets.

### Layer 5 — Entity Fingerprint

Extracts named entities (companies, products, people) from the title and content, then creates a set intersection with existing articles. If 3+ entities overlap, the articles are considered duplicates.

```python
def entity_fingerprint(title: str, content: str) -> str:
    entities = extract_entities(title + ' ' + content)  # regex + wordlist
    return '|'.join(sorted(entities[:10]))
```

Catches: news about the same event using completely different phrasing.

---

## 9. Event Clustering Engine

**File:** `app/services/event_clustering.py`

After duplicate removal, unique articles are grouped into `NewsEvent` clusters (same-story grouping).

### Configuration Constants

```python
JACCARD_THRESHOLD = 0.35           # Title word overlap to group within a batch
ENTITY_OVERLAP_THRESHOLD = 2       # Min shared entities to force-group
EMBEDDING_SIMILARITY_THRESHOLD = 0.88  # Cross-batch cosine similarity
EVENT_WINDOW_HOURS = 72            # Look back 72h for existing events
```

### Step 1 — Within-Batch Clustering (Jaccard Similarity)

For each pair of articles in the current batch:

```
Jaccard(A, B) = |words(A) ∩ words(B)| / |words(A) ∪ words(B)|

If Jaccard ≥ 0.35, OR shared_entities ≥ 2 → group together
```

Result: a list of `ArticleCluster` objects (one canonical + N similar articles).

### Step 2 — Cross-Batch Matching (Embedding Cosine)

Each cluster's canonical article embedding is compared against `NewsEvent` records from the last 72 hours. If `cosine_similarity ≥ 0.88`, the cluster's articles are **added to the existing event** (increments `source_count`, updates `last_updated_at`).

### Step 3 — Event Creation

If no existing event matches, a new `NewsEvent` is created with:

- `title` = canonical article title
- `event_type` = from Gemini enrichment (or pre-classified keyword rules)
- `source_count` = number of unique source domains in the cluster
- `priority_score` = computed immediately by the Priority Engine

---

## 10. Gemini AI Enrichment

**Directory:** `app/services/ai/`

After clustering, each unanalyzed `NewsArticle` is sent to Gemini for 25-field analysis.

### Prompt Structure

The Gemini client sends a structured JSON extraction prompt:

```
Given this AI news article, extract and return a JSON object with:
- summary: 2-3 sentence summary
- key_takeaways: ["takeaway1", "takeaway2", "takeaway3"]
- event_type: one of [model_release, funding, research_paper, product_launch, ...]
- sentiment: positive | negative | neutral
- importance_score: 0-100
- entities: { companies: [], people: [], technologies: [] }
- industry_impact: description of broader impact
- affected_industries: ["finance", "healthcare", ...]
- market_implications: short description
- technical_significance: short description
- risk_factors: ["risk1", "risk2"]
- business_opportunities: ["opportunity1", "opportunity2"]
- predictions: { short_term: "...", long_term: "..." }
```

### Rate Limiting

Gemini API is called with a built-in rate limiter (`gemini_max_rpm = 15`). A token bucket or semaphore ensures no more than 15 calls per minute, preventing `429 Too Many Requests` errors.

### Embedding Generation

For semantic dedup and search, the same Gemini `text-embedding-004` model generates 768-dimensional embeddings from `title + description`. Stored in `news_articles.embedding` as a PostgreSQL float array.

---

## 11. Priority & Ranking Engine

**File:** `app/services/priority_engine.py`

Computes a composite 0–100 **Priority Score** for every `NewsEvent`.

### Scoring Weights

```python
WEIGHTS = {
    "freshness":       0.20,   # How recently published
    "source_trust":    0.20,   # Trust level of covering sources
    "source_count":    0.10,   # Number of independent sources
    "industry_impact": 0.15,   # Industry-wide significance
    "research_sig":    0.10,   # Research paper significance
    "product_launch":  0.10,   # Whether it's a new product/model
    "funding":         0.05,   # Funding amount
    "gov_regulation":  0.05,   # Government/policy event
    "social_signal":   0.05,   # Community engagement
}
```

### Priority Tiers

| Score  | Tier           | Label             |
| ------ | -------------- | ----------------- |
| 95–100 | Breaking       | 🚨 Breaking News  |
| 80–94  | Very Important | 🔥 Very Important |
| 60–79  | Important      | 📌 Important      |
| 40–59  | Medium         | 📰 Medium         |
| 0–39   | Low            | 📄 Low Priority   |

### Event Type Bonuses

Certain event types get flat score bonuses on top of the weighted score:

| Event Type              | Bonus |
| ----------------------- | ----- |
| `model_release`         | +25   |
| `acquisition`           | +20   |
| `product_launch`        | +20   |
| `government_regulation` | +20   |
| `security_incident`     | +18   |
| `open_source_release`   | +15   |
| `ai_agent`              | +15   |
| `funding`               | +15   |

### High-Impact Company Bonus

Events involving OpenAI, Anthropic, Google, Google DeepMind, Microsoft, Meta, NVIDIA, Apple, Amazon, Tesla, or xAI receive an additional +5 bonus.

### Freshness Decay Curve

```
Age 0–2h   → 100 (full score)
Age 2–6h   → 100 → 85  (linear decay)
Age 6–12h  → 85  → 60
Age 12–24h → 60  → 40
Age 24–48h → 40  → 20
Age 48h–7d → 20  → 5
Age 7d+    → 2   (minimum floor)
```

---

## 12. Freshness Engine

**File:** `app/services/freshness_engine.py`

Runs every 2 hours as a separate job. Re-evaluates freshness scores of all articles published in the last 7 days and updates `news_articles.freshness_score`. This keeps the feed ordering accurate without requiring a full pipeline re-run.

---

## 13. Trending Engine

**File:** `app/services/trending_engine.py`

Runs every 6 hours. Analyzes `NewsEvent` records over three rolling windows (6h, 24h, 7d) to detect trending signals.

### What It Tracks

| Trend Type   | How Detected                                                           |
| ------------ | ---------------------------------------------------------------------- |
| `company`    | Named entities extracted from article metadata + analysis              |
| `model`      | Regex patterns matching known model names (GPT-_, Claude-_, Gemini-\*) |
| `topic`      | Keyword frequency from event titles and summaries                      |
| `keyword`    | Emerging new terms not seen in previous window                         |
| `framework`  | ML framework names (PyTorch, TensorFlow, JAX…)                         |
| `repository` | GitHub repo names from GitHub fetcher articles                         |

### Velocity Score

Each trend record includes a `velocity_score` — the growth rate compared to the previous window:

```
velocity = (current_count - previous_count) / max(previous_count, 1)
```

A velocity of 3.0 means "this term appeared 3× more in the latest window than the previous one" — a strong emerging signal.

---

## 14. Digest Generator

**File:** `app/services/digest_generator.py`

Runs daily at 10:00 UTC. Creates a structured daily digest with sections:

1. **Top Stories** — Events with `priority_score ≥ 80`
2. **Funding & Business** — Events with `event_type = "funding"` or `"acquisition"`
3. **Research Highlights** — ArXiv papers and research events
4. **Product Launches** — New models, APIs, tools
5. **Market Signals** — Regulatory events, industry impact
6. **AI Predictions** — Gemini-generated forward-looking statements

The digest is then used by the Personalization engine and can be fetched via `GET /api/v1/intelligence/digest`.

---

## 15. Personalization & Daily Brief

**Directory:** `app/services/personalization/`

After the digest is generated, a personalization pass creates per-user feeds:

1. Load all active users with `UserPreferences`
2. For each user, score each `NewsEvent` based on:
   - Overlap with `preferred_categories`
   - Overlap with `preferred_companies`
   - Overlap with `preferred_topics`
   - Whether the user has bookmarked related articles (implicit signal)
3. Sort events by personalized score (descending)
4. Save top 20 article IDs to the user's `DailyBrief` record

---

## 16. Notification System (Firebase FCM)

**Directory:** `app/services/notifications/`

**Breaking News Notifications** — Sent whenever a new `NewsEvent` with `is_breaking = True` is created (score ≥ 95). Uses Firebase Admin SDK to send FCM push to all users with registered `fcm_token`.

**Daily Brief Notifications** — Sent once daily (after brief generation) to users with notifications enabled in their preferences.

FCM token is registered by the frontend when the user grants notification permissions (via `Notification.requestPermission()` in the browser + Service Worker).

---

## 17. Upstash Redis Cache Layer

**File:** `app/services/cache/redis_client.py`

Uses **Upstash Redis REST API** — no persistent TCP socket, works in any serverless/edge environment.

```python
# HTTP-based: every Redis command is an HTTP GET request
GET /api/v1/news/articles → checks Redis key "news:articles:page1:20"
  ├── Cache HIT  → return cached JSON immediately
  └── Cache MISS → query PostgreSQL → cache result → return
```

### Cache TTL Strategy

| Endpoint                | TTL                       |
| ----------------------- | ------------------------- |
| `/news/articles`        | 5 minutes                 |
| `/intelligence/trends`  | 30 minutes                |
| `/intelligence/digest`  | 2 hours                   |
| `/intelligence/events`  | 10 minutes                |
| User-specific endpoints | Not cached (personalized) |

### Decorator Pattern

```python
@cache_response(ttl=300, key_prefix="news:articles")
async def get_articles(page: int, limit: int, db: AsyncSession):
    ...
```

---

## 18. Scheduler – APScheduler Jobs

**Files:** `app/scheduler/scheduler.py` · `app/scheduler/jobs.py`

Uses **APScheduler** (`AsyncIOScheduler`) with 9 registered jobs:

| Job                          | Trigger                  | What it does                             |
| ---------------------------- | ------------------------ | ---------------------------------------- |
| `job_fetch_and_cluster_news` | Every 2h                 | Full ingestion pipeline                  |
| `job_run_ai_enrichment`      | Every 2h (offset +5min)  | Gemini analysis for unenriched articles  |
| `job_refresh_freshness`      | Every 2h (offset +10min) | Re-scores freshness for last 7d articles |
| `job_dispatch_breaking_news` | Every 2h                 | Sends FCM for new breaking events        |
| `job_compute_trends`         | Every 6h                 | Trending engine run                      |
| `job_generate_daily_digest`  | Daily 10:00 UTC          | Full digest generation                   |
| `job_send_notifications`     | Daily 10:30 UTC          | Personalized brief notifications         |
| `job_cleanup_old_articles`   | Daily 00:00 UTC          | Deletes articles older than 30 days      |
| `job_refresh_source_health`  | Every 6h                 | Updates source reliability scores        |

### Error Isolation

Each job has its own `try/except` block and its own `AsyncSession`. A failure in one job does NOT cancel other jobs or crash the app.

---

## 19. API Layer – All Endpoints

### Auth (`/api/v1/auth/`)

| Method | Path             | Description                                    |
| ------ | ---------------- | ---------------------------------------------- |
| POST   | `/auth/register` | Create account, hash password, return JWT      |
| POST   | `/auth/login`    | Verify credentials, return JWT + refresh token |
| POST   | `/auth/refresh`  | Rotate JWT using refresh token                 |
| POST   | `/auth/logout`   | Invalidate refresh token                       |

### News (`/api/v1/news/`)

| Method | Path                  | Description                                |
| ------ | --------------------- | ------------------------------------------ |
| GET    | `/news/articles`      | Paginated article feed (latest first)      |
| GET    | `/news/articles/{id}` | Single article with full AI analysis       |
| GET    | `/news/articles/live` | Real-time fetch trigger for fresh articles |
| GET    | `/news/sources`       | List all news sources (active/inactive)    |
| POST   | `/news/sources`       | Add a new news source                      |
| PATCH  | `/news/sources/{id}`  | Toggle source active/inactive              |
| DELETE | `/news/sources/{id}`  | Delete a source                            |

### Intelligence (`/api/v1/intelligence/`)

| Method | Path                         | Description                                |
| ------ | ---------------------------- | ------------------------------------------ |
| GET    | `/intelligence/events`       | Paginated NewsEvents sorted by priority    |
| GET    | `/intelligence/trends`       | Trending signals (6h/24h/7d windows)       |
| GET    | `/intelligence/digest`       | Today's structured AI news digest          |
| GET    | `/intelligence/weekly-brief` | 7-day executive summary (Gemini-generated) |
| POST   | `/intelligence/suggestions`  | Career mentor or market growth analysis    |
| GET    | `/intelligence/search`       | Semantic + keyword search                  |

### Users & Preferences (`/api/v1/`)

| Method | Path                      | Description                        |
| ------ | ------------------------- | ---------------------------------- |
| GET    | `/users/me`               | Current user profile               |
| PATCH  | `/users/me`               | Update display name, FCM token     |
| GET    | `/preferences`            | Get user preferences               |
| PUT    | `/preferences`            | Update categories/companies/topics |
| GET    | `/bookmarks`              | List bookmarked articles           |
| POST   | `/bookmarks/{article_id}` | Add bookmark                       |
| DELETE | `/bookmarks/{article_id}` | Remove bookmark                    |

---

## 20. Frontend SPA – `index.html`

The entire frontend is a single ~3,500-line HTML file with embedded CSS and JavaScript. No framework, no build step — pure Vanilla JS.

### Screen Architecture

The app has three logical "screens" controlled by `display` style toggling:

```
1. auth-screen     ← Login / Register form (shown when not authenticated)
2. app-screen      ← Main app shell (shown when authenticated)
   ├── header      ← Logo + theme toggle button
   ├── view-feed   ← News feed view
   ├── view-suggestions ← AI Insights + Career Mentor
   ├── view-bookmarks   ← Saved articles
   ├── view-profile     ← User profile + settings
   └── view-sources     ← Manage news sources
3. drawer          ← Bottom sheet article detail drawer
```

### State Variables

```javascript
let articles = []; // All loaded articles
let savedBookmarks = new Set(); // Article IDs bookmarked by user
let userProfile = null; // User object from /users/me
let userPreferences = null; // Preferences from /preferences
let LIVE_PAGE = 0; // Pagination cursor for live news
```

### Authentication Flow

```javascript
// On every page load:
checkAuthState()
  → reads JWT from localStorage
  → if present: calls /users/me to verify token
    → success: show app-screen, call loadUserProfile() + loadArticles()
    → 401: clear token, show auth-screen
  → if absent: show auth-screen
```

---

## 21. Frontend – Theme System (Dark / Light Mode)

The app supports full dark/light theming using a **CSS class approach** on `<html>`.

### CSS Variables

```css
:root {
  /* Dark Theme (default) */
  --bg-app: #090a0f;
  --bg-mobile: #11131c;
  --bg-card: rgba(26, 29, 43, 0.7);
  --text-main: #f3f4f6;
  --text-muted: #9ca3af;
  --accent: #6366f1;
}

html.light {
  /* Light Theme overrides */
  --bg-app: #f3f4f6;
  --bg-mobile: #ffffff;
  --bg-card: rgba(243, 244, 246, 0.7);
  --text-main: #111827;
  --text-muted: #6b7280;
  --accent: #4f46e5;
}
```

### Theme Toggle Logic

```javascript
function toggleTheme() {
  const html = document.documentElement;

  if (html.classList.contains("dark")) {
    // Switch to light mode
    html.classList.replace("dark", "light");
    localStorage.setItem("theme", "light");
    // Swap to light logo
    document.getElementById("header-logo").src = "/logo_light.png";
    document.getElementById("auth-logo").src = "/logo_light.png";
  } else {
    // Switch to dark mode
    html.classList.replace("light", "dark");
    localStorage.setItem("theme", "dark");
    document.getElementById("header-logo").src = "/logo.png";
    document.getElementById("auth-logo").src = "/logo.png";
  }
  lucide.createIcons(); // re-render icons after DOM update
}
```

### Logo Serving

Two separate logos are served by the backend:

- `GET /logo.png` → dark mode logo (`app/templates/logo.png`)
- `GET /logo_light.png` → light mode logo (fallback to dark if not found)

On `DOMContentLoaded`, the correct logo is chosen from `localStorage` before any content renders (prevents flash of wrong logo).

### Light Mode Component Overrides

Specific CSS rules fix components that use hardcoded dark-friendly colors:

```css
html.light .article-card {
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}
html.light .switch-container .slider {
  background-color: #d1d5db !important;
} /* Toggle track */
html.light .skeleton-card {
  background: linear-gradient(90deg, rgba(0, 0, 0, 0.04) …);
}
html.light input {
  background-color: #f9fafb !important;
  color: #111827 !important;
}
html.light .settings-group-card {
  background: #f9fafb !important;
}
html.light .insights-tab-bar {
  background: rgba(0, 0, 0, 0.05) !important;
}
```

---

## 22. Frontend – Settings Panel

The Settings panel (under the Profile view) contains:

| Setting             | Component        | Behavior                                                           |
| ------------------- | ---------------- | ------------------------------------------------------------------ |
| Notifications       | Toggle switch    | Calls `Notification.requestPermission()`, saves to localStorage    |
| Dark Theme          | Toggle switch    | Calls `toggleDarkmodePref()` which invokes `toggleTheme()`         |
| Language            | Row with chevron | Opens custom in-app modal with English / Hindi / Gujarati selector |
| About               | Row with chevron | Opens custom in-app modal with version info                        |
| Manage News Sources | Row with chevron | Navigates to `view-sources` panel                                  |
| Logout              | Red row          | Clears JWT + user state, shows auth-screen                         |

**No browser `alert()` or `prompt()` calls** — all settings interactions use a custom in-app modal overlay (`#settings-custom-modal`) with a blurred backdrop.

---

## 23. Frontend – News Feed Rendering

### `buildArticleCardHTML(article, globalIdx)`

Core rendering function. Returns HTML string for a single news card. Key behaviors:

- **Source chip**: Shows source label with official badge (⚡) for Tier 0 sources. In light mode, uses dark border (`rgba(0,0,0,0.12)`) instead of white-transparent border.
- **Score badge** (★ 200): Background adapts to theme — dark `rgba(0,0,0,0.2)` or light `rgba(0,0,0,0.07)`. Color is green (≥80), amber (≥50), or gray.
- **Top Pick badge**: Only shown on `globalIdx === 0` (first article in feed).
- **Bookmark button**: State-aware icon — filled accent color if bookmarked, muted if not.
- **"Tap to read →"**: Opens the detail drawer.

### Pagination & Live Fetch

```javascript
let LIVE_PAGE = 0;
const LIVE_PAGE_SIZE = 20;

// On "Fetch Live News" button click:
async function fetchLiveNews() {
  LIVE_PAGE = 0;
  const data = await authenticatedFetch("/api/v1/news/articles/live");
  articles = data.articles; // newest first
  renderFeed();
}

// On scroll to bottom:
async function loadMoreArticles() {
  LIVE_PAGE++;
  const data = await authenticatedFetch(
    `/api/v1/news/articles?page=${LIVE_PAGE}`,
  );
  appendArticleCards(data.articles, articles.length);
  articles = [...articles, ...data.articles];
}
```

**Important**: The article order is always preserved from the API response (newest-first, sorted by `published_at DESC` in the backend). Refreshing fetches fresh articles without reordering existing ones.

---

## 24. Frontend – Bookmarks System

Bookmarks are stored in **two places simultaneously**:

1. **`savedBookmarks` Set** (in-memory, JS) — for instant UI toggling without network latency
2. **`UserPreferences.bookmarked_article_ids`** (persisted to backend) — via `savePreferences()` which calls `PUT /api/v1/preferences`

```javascript
async function toggleBookmarkFromFeed(event, articleId) {
  event.stopPropagation(); // Don't open drawer

  if (savedBookmarks.has(articleId)) {
    savedBookmarks.delete(articleId);
    // update icon to unfilled
  } else {
    savedBookmarks.add(articleId);
    // update icon to filled accent
  }

  // Re-render bookmarks view if currently visible
  if (document.getElementById("view-bookmarks").classList.contains("active")) {
    renderBookmarks();
  }

  await savePreferences(); // Persist to backend
}
```

---

## 25. Frontend – Sources Management Panel

The **Manage News Sources** panel (`view-sources`) lets users:

- **View** all sources with: icon, display name, type badge (RSS/API/Scrape), domain, relevance %, Active/Inactive status
- **Toggle** sources active/inactive (calls `PATCH /api/v1/news/sources/{id}`)
- **Add** custom sources via a form (calls `POST /api/v1/news/sources`)
- **Delete** sources (calls `DELETE /api/v1/news/sources/{id}`)

Source cards are rendered in JavaScript (`loadNewsSources()`) and are **theme-aware** — white cards in light mode, translucent dark cards in dark mode. The `isLightMode` flag is checked at render time:

```javascript
const isLightMode = document.documentElement.classList.contains("light");
card.style.cssText = `
  background: ${isLightMode ? "rgba(255,255,255,0.95)" : "rgba(17,19,28,0.45)"};
  border: 1px solid ${isLightMode ? "rgba(0,0,0,0.08)" : "rgba(99,102,241,0.15)"};
`;
```

---

## 26. Frontend – AI Insights View

Two tabs in the AI Insights panel:

### Career Mentor Tab

Calls `POST /api/v1/intelligence/suggestions` with `type: "personalized"`.

Backend:

1. Loads user's `preferred_categories`, `preferred_companies`, `preferred_topics`
2. Fetches user's last 5 bookmarks as context
3. Fetches today's top 10 news events
4. Sends a Gemini prompt: _"Act as a senior AI career mentor. Given this user's interests (...) and today's AI news (...), provide personalized action items, learning recommendations, and career opportunities."_
5. Returns structured markdown response

### Market Growth Tab

Calls `POST /api/v1/intelligence/suggestions` with `type: "market"`.

Backend:

1. Fetches current trending signals (6h window)
2. Fetches top funding events (last 7d)
3. Sends a Gemini prompt for VC-scale market analysis
4. Returns structured recommendations

---

## 27. Middleware Stack

**File:** `app/middleware/__init__.py`

Registered middleware (in order of execution, outermost first):

1. **CORS Middleware** — Allows configured origins, credentials, all methods/headers
2. **Rate Limiting Middleware** — Checks Redis for request count per IP per minute; 100 req/min for authenticated, 20 for anonymous
3. **Security Headers Middleware** — Adds `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`
4. **Request Logging Middleware** — Logs method, path, status code, response time for every request

---

## 28. Auth System – JWT + Supabase

**File:** `app/api/v1/auth.py`

Uses **Supabase JWT** with a custom `secret_key` for signing. The JWT payload:

```json
{
  "sub": "user-uuid",
  "email": "user@example.com",
  "exp": 1234567890,
  "iat": 1234567890
}
```

The `get_current_user` FastAPI dependency decodes the JWT on every protected request:

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user = await db.get(User, payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(401)
        return user
    except JWTError:
        raise HTTPException(401)
```

Passwords are hashed with **bcrypt** (via `passlib`). No plaintext passwords are ever stored or logged.

---

## 29. Search Service

**File:** `app/services/search_service.py`

The search endpoint (`GET /api/v1/intelligence/search?q=...`) runs a **hybrid search**:

1. **Keyword Search** — `ILIKE '%query%'` across article titles, descriptions, and entity JSON fields
2. **Semantic Search** — Generates a Gemini embedding for the query, then computes cosine similarity against stored article embeddings using PostgreSQL's float array operations
3. **Score Fusion** — Blends keyword match score + semantic similarity score (weighted 40/60)
4. **Results** — Returns top 20 articles sorted by fused score, with highlighted snippets

---

## 30. ngrok – Mobile Testing Tunnel

The `ngrok/` directory contains the ngrok binary. To expose the local backend to a mobile device on a different network:

```powershell
# In the ngrok/ directory:
.\ngrok http 8000
```

This creates a public HTTPS URL (e.g. `https://abc123.ngrok-free.app`) that tunnels to `localhost:8000`. The frontend works identically — all API calls use relative paths (`/api/v1/...`), so they automatically use the ngrok origin when opened from a mobile browser.

> ⚠️ **ngrok URLs expire after 8 hours** on the free tier. Restart ngrok for a fresh URL.

---

## 31. Environment Variables Reference

Full list of variables read from `.env` (see `.env.example` for defaults):

```bash
# Application
APP_ENV=development          # development | production | testing
APP_NAME="AI News"
APP_VERSION=2.4.0
LOG_LEVEL=info
SECRET_KEY=<min-32-char-random-string>

# Supabase (PostgreSQL + Auth)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_KEY=...
SUPABASE_JWT_SECRET=...
DATABASE_URL=postgresql+asyncpg://user:password@host/db

# Gemini AI
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash
GEMINI_EMBEDDING_MODEL=models/text-embedding-004
GEMINI_MAX_RPM=15

# Firebase (for push notifications)
FIREBASE_CREDENTIALS_JSON='{...}'  # OR
FIREBASE_CREDENTIALS_PATH=./credentials/firebase.json

# Upstash Redis
UPSTASH_REDIS_REST_URL=https://xxx.upstash.io
UPSTASH_REDIS_REST_TOKEN=...

# Scheduler
SCHEDULER_TIMEZONE=UTC
DAILY_BRIEF_HOUR=10
DAILY_BRIEF_MINUTE=0
CLEANUP_DAYS_OLD=30

# Rate Limiting
RATE_LIMIT_PER_MINUTE_AUTHENTICATED=100
RATE_LIMIT_PER_MINUTE_ANONYMOUS=20

# CORS
CORS_ORIGINS=http://localhost:3000,https://your-domain.com
```

---

## 32. Data Flow – End-to-End Journey of One Article

Here is the complete lifecycle of a single news article from source to user screen:

```
1. APScheduler fires job_fetch_and_cluster_news every 2 hours
   │
2. NewsFetchOrchestrator runs all ~30 fetchers concurrently
   │   e.g. TechCrunchAIFetcher parses RSS → RawArticle(
   │     url="https://techcrunch.com/2026/07/09/openai-gpt5",
   │     title="OpenAI Releases GPT-5",
   │     source_name="techcrunch_ai",
   │     source_domain="techcrunch.com",
   │     ...
   │   )
   │
3. VerificationEngine checks:
   │   ✓ domain trust score
   │   ✓ title contains AI keywords
   │   ✓ not too old (< 48h)
   │
4. DuplicateDetectionEngine runs:
   │   Layer 1: URL check → not in DB
   │   Layer 2: Title hash check → not in DB
   │   Layer 3: Content fingerprint → not in DB
   │   Layer 4: Embedding similarity → all < 0.92
   │   Layer 5: Entity fingerprint → < 3 shared entities
   │   Result: NOT a duplicate → proceed
   │
5. NewsArticle saved to PostgreSQL:
   │   id="uuid-abc123"
   │   title_fingerprint="sha256..."
   │   embedding=[0.123, -0.456, ...]  (768-dim vector)
   │
6. EventClusteringEngine:
   │   Within-batch: Jaccard("OpenAI Releases GPT-5", "GPT-5 Announced") = 0.60 ≥ 0.35
   │   → Grouped with 2 other articles from this batch
   │   Cross-batch: cosine("GPT-5", existing events) = 0.72 < 0.88 → no match
   │   → CREATE new NewsEvent(
   │       title="OpenAI Releases GPT-5",
   │       source_count=3,
   │       event_type="model_release"
   │     )
   │
7. Gemini AI Enrichment (job_run_ai_enrichment, offset +5min):
   │   → POST to Gemini API with article text
   │   → Returns NewsAnalysis(
   │       summary="OpenAI has released GPT-5...",
   │       importance_score=94,
   │       event_type="model_release",
   │       entities={companies:["OpenAI"], technologies:["GPT-5","LLM"]},
   │       sentiment="positive",
   │       key_takeaways=["GPT-5 achieves SOTA on MMLU...", ...],
   │       affected_industries=["software", "healthcare", "education"]
   │     )
   │
8. PriorityEngine computes score:
   │   freshness(0h) = 100 × 0.20 = 20.0
   │   source_trust(techcrunch=Tier1) = 85 × 0.20 = 17.0
   │   source_count(3) = 75 × 0.10 = 7.5
   │   industry_impact = 90 × 0.15 = 13.5
   │   event_bonus("model_release") = +25.0
   │   company_bonus("OpenAI") = +5.0
   │   total = 88.0 → Tier: VERY_IMPORTANT 🔥
   │
9. Breaking News Check:
   │   score=88 < 95 → not breaking → no FCM notification
   │
10. User opens AI News app:
    │   Frontend: GET /api/v1/news/articles → Redis cache MISS
    │   Backend: SELECT * FROM news_articles ORDER BY published_at DESC
    │   Result cached in Redis (5 min TTL)
    │
11. buildArticleCardHTML() renders:
    │   ⚡ TechCrunch  [★ 88 green badge]
    │   "OpenAI Releases GPT-5"
    │   "OpenAI has released GPT-5, achieving state-of-the-art..."
    │   🕐 Jul 9, 02:00 PM    [bookmark icon]  Tap to read →
    │
12. User taps card → bottom drawer opens:
    │   Full article detail: summary, takeaways, entities, source link
    │
13. User taps bookmark:
    │   savedBookmarks.add("uuid-abc123")
    │   PUT /api/v1/preferences → bookmarked_article_ids updated in DB
    │
14. Daily 10:00 UTC — PersonalizationEngine:
    │   User has "OpenAI" in preferred_companies
    │   → Article scores high in user's personalized feed
    │   → DailyBrief saved with this article in top 5
    │
15. FCM notification sent:
    │   "📰 Your AI News Daily Brief is ready"
    │   User taps → opens app → sees personalized feed
```

---

_This document reflects the codebase as of July 2026 including all UI improvements: dual logo system, comprehensive light mode support, in-app settings modals, bookmark button on every news card, and the ngrok mobile testing setup._
