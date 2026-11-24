FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    gcc \
    libpq-dev \
    xfsprogs \
    && rm -rf /var/lib/apt/lists/*

# Install production Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    rm -rf /usr/local/lib/python*/site-packages/jaraco.context* && \
    rm -rf /usr/local/lib/python*/site-packages/wheel*

# Copy application code explicitly
# This ensures only necessary code enters the image.
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY app/ ./app/

# ── Test target ─────────────────────────────────────────────────────────────
# Pre-installs dev/test dependencies so tests run without network installs.
FROM base AS test

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

CMD ["python", "-m", "pytest"]

# ── Production / runtime target (default) ───────────────────────────────────
FROM base AS runtime

# The runtime does not install packages; drop the build-time package manager
# and its vendored dependencies from the shipped image.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip* \
    /usr/local/lib/python3.13/site-packages/setuptools* \
    /usr/local/lib/python3.13/site-packages/wheel* \
    /usr/local/bin/pip*

# Platform version injected by CI (from scripts/ci-version.sh). Empty for
# local builds; the app then falls back to the static version in
# app/version.py (see app/config.py: app_version).
ARG APP_VERSION=""
ENV APP_VERSION=${APP_VERSION}

# Expose port
EXPOSE 8000

# Run application (production / load-test mode — 4 workers)
# Dev mode injects --reload via compose override.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--loop", "uvloop", "--timeout-keep-alive", "30"]
