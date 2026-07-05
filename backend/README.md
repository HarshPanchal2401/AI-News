# AI Pulse — Personalized AI News Intelligence Platform
## Production-Ready FastAPI Backend

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🧠 What is AI Pulse?

AI Pulse is an **AI Intelligence Assistant** — not a regular news app. It automatically:

1. **Fetches** AI news from 20 trusted sources every day at 10:00 AM UTC
2. **Verifies** each article with a trust score (0–100)
3. **Deduplicates** across 5 detection layers (URL, title hash, content hash, semantic embedding, entity fingerprint)
4. **Analyzes** each article using **Gemini 2.5 Flash** (summary, category, companies, keywords, importance score, why it matters)
5. **Ranks** articles by weighted score: `importance×0.35 + trust×0.30 + freshness×0.20 + official×0.15`
6. **Personalizes** a daily brief for each user based on their favorite companies, categories, and topics
7. **Notifies** users via **Firebase Cloud Messaging** push notification

---

## 🏗️ Architecture

```
User Request
     │
     ▼
FastAPI + Rate Limiter
     │
     ▼
JWT Auth (Supabase)
     │
     ▼
Upstash Redis Cache ──── HIT ──► Response
     │ MISS
     ▼
SQLAlchemy (Supabase PostgreSQL)
     │
     ▼
Response

Daily Pipeline (10AM UTC):
Orchestrator → Fetchers (20 sources) → Verification → Dedup Engine → DB
    ↓
Gemini AI Analysis → Ranking → Personalization → FCM Notifications
```

---

## 📦 Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 (async) |
| Validation | Pydantic v2 |
| Database | Supabase PostgreSQL |
| Auth | Supabase Auth + JWT |
| AI | Gemini 2.5 Flash (free tier) |
| Notifications | Firebase Cloud Messaging |
| Cache | Upstash Redis |
| Scheduler | APScheduler 3.x |
| Deployment | Docker + Render |

---

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.12+
- A [Supabase](https://supabase.com) project
- A [Gemini API key](https://makersuite.google.com/app/apikey) (free)
- A [Firebase](https://firebase.google.com) project with FCM enabled
- An [Upstash Redis](https://console.upstash.com) database (free tier)

### 2. Clone and Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd "AI News/backend"

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (macOS/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your actual credentials
notepad .env   # Windows
nano .env      # macOS/Linux
```

Required environment variables:
```env
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-key
SUPABASE_JWT_SECRET=your-jwt-secret
DATABASE_URL=postgresql+asyncpg://postgres:password@db.your-project.supabase.co:5432/postgres
GEMINI_API_KEY=your-gemini-api-key
FIREBASE_CREDENTIALS_JSON={"type":"service_account",...}
UPSTASH_REDIS_REST_URL=https://your-db.upstash.io
UPSTASH_REDIS_REST_TOKEN=your-token
```

### 4. Set Up Supabase Database

Run the following in the Supabase SQL Editor to create all tables:

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tables are created automatically by SQLAlchemy on startup (development mode)
-- For production, use Alembic migrations
```

Or let the application create tables automatically (development only):
```python
# In app/database/connection.py, call create_all_tables() on startup
```

### 5. Run Locally

```bash
# Development server with hot reload
uvicorn app.main:app --reload --port 8000

# Or using Python directly
python -m app.main
```

The API is now available at:
- **API**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health**: http://localhost:8000/health

---

## 🐳 Docker

### Build and Run

```bash
# Build image
docker build -t ai-pulse-backend .

# Run container
docker run -d \
  --name ai-pulse \
  -p 8000:8000 \
  --env-file .env \
  ai-pulse-backend
```

### Docker Compose (Development)

```bash
docker-compose up --build
```

---

## ☁️ Deploy to Render

1. Push your code to GitHub
2. Go to [Render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Environment**: Add all `.env` variables in the Render dashboard
5. Deploy!

---

## 📡 API Reference

### Authentication
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login (get JWT) |
| POST | `/api/v1/auth/refresh` | Refresh access token |

### News
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/news` | List articles (paginated, filterable) |
| GET | `/api/v1/news/{id}` | Get full article details |
| GET | `/api/v1/news/trending` | Today's top articles |
| GET | `/api/v1/news/search?q=...` | Full-text search |

### Daily Brief
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/brief/today` | Get today's personalized brief |
| GET | `/api/v1/brief/history` | Get past briefs |

### User & Preferences
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/users/me` | Get profile |
| PUT | `/api/v1/users/me` | Update profile |
| POST | `/api/v1/users/me/fcm-token` | Register FCM token |
| GET | `/api/v1/preferences` | Get preferences |
| PUT | `/api/v1/preferences` | Update preferences |

### Bookmarks
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/bookmarks` | List bookmarks |
| POST | `/api/v1/bookmarks` | Bookmark article |
| DELETE | `/api/v1/bookmarks/{article_id}` | Remove bookmark |

### Notifications
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/notifications` | Notification history |
| PUT | `/api/v1/notifications/{id}/read` | Mark as read |
| PUT | `/api/v1/notifications/read-all` | Mark all as read |

### Admin (admin users only)
| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/admin/fetch-now` | Manually trigger pipeline |
| GET | `/api/v1/admin/sources` | List all sources |
| PUT | `/api/v1/admin/sources/{id}` | Enable/disable source |
| GET | `/api/v1/admin/stats` | Application statistics |

### Health
| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Basic health check |
| GET | `/health/detailed` | DB + Cache + Scheduler status |

---

## ⏰ Scheduler

All jobs run automatically:

| Job | Schedule | Description |
|---|---|---|
| News Pipeline | Daily 10:00 AM UTC | Fetch → Verify → Dedup → AI → Rank → Brief |
| Push Notifications | Daily 10:05 AM UTC | Send FCM to all users |
| Cleanup | Daily 00:00 AM UTC | Delete articles > 30 days old |
| Source Health | Every 6 hours | Test all sources, disable failing ones |

Trigger manually (admin only):
```bash
curl -X POST http://localhost:8000/api/v1/admin/fetch-now \
  -H "Authorization: Bearer <admin-token>"
```

---

## 🧪 Running Tests

```bash
# Install test dependencies (included in requirements.txt)
pip install pytest pytest-asyncio pytest-cov

# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=app --cov-report=html

# Run specific test module
pytest tests/test_duplicate_detection.py -v
pytest tests/test_all.py::TestTrustScoring -v
```

---

## 🔧 Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Environment: development/production/testing |
| `LOG_LEVEL` | `info` | Logging verbosity |
| `DAILY_BRIEF_HOUR` | `10` | UTC hour for daily pipeline |
| `MIN_TRUST_SCORE` | `40` | Minimum trust to accept an article |
| `MIN_FINAL_SCORE` | `30` | Minimum score to include in brief |
| `MIN_BRIEF_ARTICLES` | `10` | Minimum articles per daily brief |
| `SEMANTIC_SIMILARITY_THRESHOLD` | `0.92` | Cosine similarity for duplicate detection |
| `CLEANUP_DAYS_OLD` | `30` | Delete articles older than N days |

---

## 📁 Project Structure

```
backend/
├── app/
│   ├── main.py                    # FastAPI app entry point
│   ├── api/v1/                    # REST API routers
│   ├── core/                      # Config, logging, exceptions, security
│   ├── database/                  # SQLAlchemy connection and base
│   ├── models/                    # ORM models (8 tables)
│   ├── schemas/                   # Pydantic v2 request/response schemas
│   ├── services/
│   │   ├── news_fetchers/         # 13 fetchers + orchestrator (20 sources)
│   │   ├── duplicate_detection/   # 5-layer dedup engine
│   │   ├── verification/          # Trust scoring + cross-referencing
│   │   ├── ai/                    # Gemini client + analyzer + batch processor
│   │   ├── ranking/               # Weighted ranking algorithm
│   │   ├── personalization/       # Daily brief generation
│   │   ├── notifications/         # FCM push notifications
│   │   └── cache/                 # Upstash Redis client
│   ├── scheduler/                 # APScheduler jobs
│   ├── middleware/                # Rate limiting, logging, CORS
│   └── utils/                     # Text, date, HTTP utilities
├── tests/                         # pytest test suite
├── Dockerfile                     # Multi-stage production Docker build
├── docker-compose.yml             # Local development compose
├── requirements.txt               # Pinned dependencies
└── .env.example                   # Environment variable template
```

---

## 🛡️ Security

- All secrets via environment variables (never hardcoded)
- JWT tokens with configurable expiry
- Supabase JWT secret validation
- Rate limiting: 100 req/min (authenticated), 20 req/min (anonymous)
- Non-root Docker user
- Input validation via Pydantic v2
- SQL injection prevented by SQLAlchemy ORM

---

## 📈 Monitoring

- **Health endpoint**: `GET /health/detailed` — DB, Cache, Scheduler status
- **Prometheus metrics**: Available at `/metrics` (production)
- **Structured logging**: JSON in production (structlog)
- **Request tracing**: X-Request-ID header on every response

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Write tests for your changes
4. Run the test suite: `pytest tests/ -v`
5. Submit a pull request

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built with ❤️ by the AI Pulse team — Powered by Gemini, FastAPI, and Supabase*
