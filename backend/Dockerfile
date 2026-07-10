# =============================================================================
# AI Pulse – Dockerfile
# Multi-stage build for production (Railway-ready, root context)
# =============================================================================

# ── Stage 1: Builder ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install system dependencies required to compile Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies into /install
# Build context is repo root, so requirements.txt is inside backend/
COPY backend/requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Security: create a non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /bin/bash appuser

# Install only the runtime system libraries we actually need
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code from backend/app of the repo root context
COPY backend/app/ ./app/
COPY backend/alembic.ini* ./
COPY frontend/ ./frontend/


# Environment
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Expose default port
EXPOSE 8000

# Switch to non-root user
USER appuser

# Use shell form so ${PORT:-8000} variable substitution works.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --log-level info"]
