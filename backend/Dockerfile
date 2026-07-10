# =============================================================================
# AI Pulse – Dockerfile
# Multi-stage build for production (Railway-ready)
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

# Copy and install dependencies into /install (not user-local)
# Using --prefix=/install ensures packages end up in a path
# that can be COPY'd into the runtime stage and accessed by any user.
COPY requirements.txt .
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

# Copy installed packages from builder into the system site-packages path.
# /usr/local is owned by root and readable by all users — fixes the bug
# where packages in /root/.local were invisible to appuser.
COPY --from=builder /install /usr/local

# Copy application code
COPY app/ ./app/
COPY alembic.ini* ./

# Environment
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Health check
# Use ${PORT:-8000} so it works both locally (port 8000) and on Railway (dynamic port)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Expose default port (Railway overrides via $PORT at runtime)
EXPOSE 8000

# Switch to non-root user
USER appuser

# Use shell form so ${PORT:-8000} variable substitution works.
# Railway injects $PORT at deploy time; locally it falls back to 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --log-level info"]
