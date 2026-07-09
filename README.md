# AI News — Personalized AI Intelligence Platform

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![Gemini AI](https://img.shields.io/badge/Gemini-2.0%20Flash-orange.svg)](https://ai.google.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**AI News** is a fully automated AI news intelligence platform that continuously ingests, deduplicates, clusters, enriches, ranks, and personalizes AI news — delivered as a sleek mobile-responsive web app.

> **Version:** 2.4.0 · **Stack:** FastAPI · SQLAlchemy 2.0 · PostgreSQL (Supabase) · Upstash Redis · Gemini AI · Firebase FCM · Vanilla JS SPA

---

## ✨ Key Features

| Feature | Details |
|---|---|
| 📡 **30 News Sources** | Official blogs, RSS feeds, scrapers, ArXiv, GitHub Trending, Hacker News |
| 🔍 **5-Layer Deduplication** | URL · Title hash · Content hash · Semantic embedding · Entity fingerprint |
| 🧩 **Event Clustering** | Groups same-story articles across batches using Jaccard + Gemini embeddings |
| 🤖 **Gemini AI Enrichment** | 25-field analysis: summary, sentiment, entities, importance score, predictions |
| 🏆 **Priority Engine** | Weighted scoring with tier labels: Breaking · Very Important · Important |
| 📈 **Trending Engine** | Tracks companies, models, topics, frameworks over 6h / 24h / 7d windows |
| 📋 **Daily Digest** | Structured digest with Top Stories, Research, Funding, Product Launches |
| 👤 **Personalization** | Per-user feeds scored against preferred categories, companies & topics |
| 🔔 **Push Notifications** | Firebase FCM for breaking news and daily brief delivery |
| ⚡ **Redis Cache** | Upstash REST-based caching with per-endpoint TTL strategy |
| 🔒 **JWT Auth** | Supabase-backed authentication with bcrypt password hashing |
| 🌗 **Dark / Light Mode** | Full theme system with CSS variables and persistent user preference |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      30 NEWS SOURCES                         │
│  Official Blogs · RSS Feeds · Scrapers · ArXiv · GitHub · HN │
└───────────────────────┬──────────────────────────────────────┘
                        │  every 2 hours (APScheduler)
                        ▼
              NEWS FETCH ORCHESTRATOR
              (asyncio.gather — all fetchers concurrently)
                        │
                        ▼
              VERIFICATION ENGINE
              (AI-relevance · Domain trust · Freshness)
                        │
                        ▼
           5-LAYER DUPLICATE DETECTION ENGINE
           L1: URL  L2: Title hash  L3: Content hash
           L4: Gemini embedding cosine  L5: Entity fingerprint
                        │ unique articles only
                        ▼
              DATABASE SAVE (PostgreSQL / Supabase)
                        │
                        ▼
              EVENT CLUSTERING ENGINE
              (Jaccard + Entity overlap → cross-batch cosine ≥ 0.88)
                        │
                        ▼
           GEMINI AI ENRICHMENT (25 fields per article)
                        │
                        ▼
           PRIORITY & RANKING ENGINE (0–100 score)
                   ┌────┴────┐
                   ▼         ▼
            FastAPI API   Trending Engine
            (REST layer)  (6h · 24h · 7d)
                   │
           ┌───────┴───────┐
           ▼               ▼
    Upstash Redis     Frontend SPA
    (cache TTL)       (index.html · Vanilla JS)
```

---

## 📁 Project Structure

```
AI-News/
├── README.md
├── .gitignore
├── codebase_analysis.md          ← Deep technical reference (32 sections)
├── venv/                         ← Python virtual environment (gitignored)
├── ngrok/                        ← ngrok binary for mobile testing (gitignored)
│
└── backend/
    ├── .env                      ← Secret keys (gitignored)
    ├── .env.example              ← Template for new developers
    ├── requirements.txt
    ├── Dockerfile
    ├── docker-compose.yml
    │
    └── app/
        ├── main.py               ← FastAPI app factory + lifespan manager
        ├── core/
        │   ├── config.py         ← Pydantic BaseSettings (all env vars)
        │   └── logging.py        ← Structured JSON logging
        ├── api/v1/
        │   ├── auth.py           ← JWT auth endpoints
        │   ├── news.py           ← Articles, sources, bookmarks
        │   ├── routers.py        ← Users, prefs, notifications, admin
        │   └── intelligence.py   ← Events, trends, digest, suggestions
        ├── database/
        │   └── connection.py     ← AsyncSession factory + health check
        ├── middleware/           ← CORS, rate limiting, security headers
        ├── models/               ← SQLAlchemy ORM (9 tables)
        ├── schemas/              ← Pydantic v2 request/response models
        ├── services/
        │   ├── ai/               ← Gemini client + enrichment logic
        │   ├── cache/            ← Upstash Redis REST client
        │   ├── duplicate_detection/  ← 5-layer dedup engine
        │   ├── news_fetchers/    ← RSS, scrapers, ArXiv, GitHub, HN
        │   ├── notifications/    ← Firebase FCM dispatcher
        │   ├── personalization/  ← User-specific feed scoring
        │   ├── ranking/          ← Feed ranking helpers
        │   ├── verification/     ← Source trust + AI-relevance filter
        │   ├── digest_generator.py
        │   ├── event_clustering.py
        │   ├── freshness_engine.py
        │   ├── priority_engine.py
        │   ├── search_service.py
        │   └── trending_engine.py
        ├── scheduler/
        │   ├── scheduler.py      ← APScheduler instance + job registration
        │   └── jobs.py           ← 9 async scheduled job implementations
        ├── templates/
        │   ├── index.html        ← Full SPA frontend (~3,500 lines, Vanilla JS)
        │   ├── logo.png          ← App logo (dark mode)
        │   └── logo_light.png    ← App logo (light mode)
        └── utils/
            ├── text_utils.py     ← Hashing, fingerprinting, normalization
            └── date_utils.py     ← UTC helpers, age calculations
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- [Supabase](https://supabase.com) project (free tier works)
- [Gemini API key](https://aistudio.google.com/app/apikey) (free)
- [Firebase](https://firebase.google.com) project with FCM enabled
- [Upstash Redis](https://console.upstash.com) database (free tier)

### 1. Clone & Install

```bash
git clone <your-repo-url>
cd "AI-News/backend"

python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

Minimum required variables:

```env
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_KEY=...
SUPABASE_JWT_SECRET=...
DATABASE_URL=postgresql+asyncpg://postgres:password@db.your-project.supabase.co:5432/postgres
GEMINI_API_KEY=...
FIREBASE_CREDENTIALS_JSON={"type":"service_account",...}
UPSTASH_REDIS_REST_URL=https://your-db.upstash.io
UPSTASH_REDIS_REST_TOKEN=...
```

See the [full environment variables reference](#-environment-variables) below.

### 3. Run Locally

```bash
uvicorn app.main:app --reload --port 8000
```

| Endpoint | URL |
|---|---|
| Frontend SPA | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Health check | http://localhost:8000/health |

---

## 🐳 Docker

```bash
# Build & run
docker build -t ai-news-backend .
docker run -d -p 8000:8000 --env-file .env ai-news-backend

# Or with Docker Compose
docker-compose up --build
```

---

## ☁️ Deploy to Render

1. Push to GitHub
2. Render → **New Web Service** → connect repo
3. Set:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add all `.env` variables in the Render dashboard
5. Deploy!

---

## 📡 API Reference

### Authentication — `/api/v1/auth/`
| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create account, returns JWT |
| POST | `/auth/login` | Login, returns JWT + refresh token |
| POST | `/auth/refresh` | Rotate JWT |
| POST | `/auth/logout` | Invalidate refresh token |

### News — `/api/v1/news/`
| Method | Path | Description |
|---|---|---|
| GET | `/news/articles` | Paginated article feed (latest first) |
| GET | `/news/articles/{id}` | Single article with full AI analysis |
| GET | `/news/articles/live` | Real-time fetch trigger |
| GET | `/news/sources` | List all sources |
| POST | `/news/sources` | Add a new source |
| PATCH | `/news/sources/{id}` | Toggle source active/inactive |
| DELETE | `/news/sources/{id}` | Delete a source |

### Intelligence — `/api/v1/intelligence/`
| Method | Path | Description |
|---|---|---|
| GET | `/intelligence/events` | NewsEvents sorted by priority score |
| GET | `/intelligence/trends` | Trending signals (6h / 24h / 7d) |
| GET | `/intelligence/digest` | Today's structured AI news digest |
| GET | `/intelligence/weekly-brief` | 7-day executive summary |
| POST | `/intelligence/suggestions` | Career mentor / market growth analysis |
| GET | `/intelligence/search` | Hybrid semantic + keyword search |

### Users & Preferences — `/api/v1/`
| Method | Path | Description |
|---|---|---|
| GET | `/users/me` | Current user profile |
| PATCH | `/users/me` | Update name, FCM token |
| GET | `/preferences` | Get user preferences |
| PUT | `/preferences` | Update categories / companies / topics |
| GET | `/bookmarks` | List bookmarked articles |
| POST | `/bookmarks/{id}` | Add bookmark |
| DELETE | `/bookmarks/{id}` | Remove bookmark |

---

## ⏰ Scheduled Jobs (APScheduler)

9 background jobs run automatically:

| Job | Schedule | Description |
|---|---|---|
| `job_fetch_and_cluster_news` | Every 2h | Full ingestion pipeline |
| `job_run_ai_enrichment` | Every 2h (+5 min offset) | Gemini analysis for new articles |
| `job_refresh_freshness` | Every 2h (+10 min offset) | Re-scores freshness for last 7d |
| `job_dispatch_breaking_news` | Every 2h | FCM push for breaking events (score ≥ 95) |
| `job_compute_trends` | Every 6h | Trending engine run |
| `job_generate_daily_digest` | Daily 10:00 UTC | Full digest generation |
| `job_send_notifications` | Daily 10:30 UTC | Personalized brief FCM push |
| `job_cleanup_old_articles` | Daily 00:00 UTC | Deletes articles older than 30 days |
| `job_refresh_source_health` | Every 6h | Updates source reliability scores |

Trigger the pipeline manually (admin only):

```bash
curl -X POST http://localhost:8000/api/v1/admin/fetch-now \
  -H "Authorization: Bearer <admin-token>"
```

---

## 🗃️ Data Models (9 Tables)

| Table | Purpose |
|---|---|
| `users` | Registered users (UUID, email, bcrypt hash, FCM token) |
| `user_preferences` | Preferred categories, companies, topics, notification settings |
| `news_sources` | All 30 sources with reliability scores and fetch stats |
| `news_articles` | Raw article storage with embeddings and fingerprints |
| `news_analyses` | Gemini 25-field enrichment (one-to-one with article) |
| `news_events` | Story clusters with priority score and tier label |
| `trends` | Rolling-window trending signals |
| `daily_briefs` | Per-user personalized daily feed snapshots |
| `notifications` | FCM push notification history |

---

## 📰 News Sources

**Tier 0 — Official Company Blogs**
OpenAI · Google AI · DeepMind · Hugging Face

**Tier 1 — Research & Tier-1 Media**
ArXiv (cs.AI/LG/CL) · TechCrunch · VentureBeat · MIT Technology Review · Bloomberg · Ars Technica

**Tier 2 — Developer & Community**
GitHub Trending · GitHub Releases · Hacker News · Product Hunt

**Tier 3 — Aggregators**
Google News AI

---

## 🔒 Security

- All secrets loaded from environment variables — nothing hardcoded
- JWT with HS256 signing; bcrypt password hashing via `passlib`
- Supabase JWT secret validation on every request
- Rate limiting: **100 req/min** (authenticated) · **20 req/min** (anonymous)
- Security headers: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`
- SQL injection prevented by SQLAlchemy ORM
- Non-root Docker user in production image

---

## 🧪 Tests

```bash
# Run full test suite
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=app --cov-report=html

# Specific module
pytest tests/test_duplicate_detection.py -v
```

---

## 🌍 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development` / `production` / `testing` |
| `APP_VERSION` | `2.4.0` | Application version |
| `LOG_LEVEL` | `info` | Logging verbosity |
| `SECRET_KEY` | — | Min 32-char random string for JWT signing |
| `SUPABASE_URL` | — | Supabase project URL |
| `DATABASE_URL` | — | `postgresql+asyncpg://...` connection string |
| `GEMINI_API_KEY` | — | Google AI Studio API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model for analysis |
| `GEMINI_EMBEDDING_MODEL` | `models/text-embedding-004` | Embedding model |
| `GEMINI_MAX_RPM` | `15` | Gemini API rate limit (requests/min) |
| `FIREBASE_CREDENTIALS_JSON` | — | Firebase service account JSON (inline or path) |
| `UPSTASH_REDIS_REST_URL` | — | Upstash Redis REST endpoint |
| `UPSTASH_REDIS_REST_TOKEN` | — | Upstash Redis auth token |
| `SCHEDULER_TIMEZONE` | `UTC` | Timezone for APScheduler |
| `DAILY_BRIEF_HOUR` | `10` | UTC hour for daily digest job |
| `CLEANUP_DAYS_OLD` | `30` | Delete articles older than N days |
| `RATE_LIMIT_PER_MINUTE_AUTHENTICATED` | `100` | Authenticated rate limit |
| `RATE_LIMIT_PER_MINUTE_ANONYMOUS` | `20` | Anonymous rate limit |
| `CORS_ORIGINS` | — | Comma-separated allowed origins |

---

## 📖 Deep Dive

For a complete technical walkthrough of every component — fetchers, deduplication layers, clustering algorithm, Gemini prompts, scoring weights, frontend rendering, and an end-to-end article lifecycle — see [`codebase_analysis.md`](./codebase_analysis.md).

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built with ❤️ — Powered by Gemini AI, FastAPI, and Supabase*
