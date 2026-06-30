FROM python:3.13-slim@sha256:eb43ff125d8d58d7449dcba7d336c23bcac412f526d861db493b9994d8010280 AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install production Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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

# Expose port
EXPOSE 8000

# Run application (production / load-test mode — 4 workers)
# Dev mode injects --reload via compose override.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--loop", "uvloop", "--timeout-keep-alive", "30"]
