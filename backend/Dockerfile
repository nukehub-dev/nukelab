FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code explicitly
# This ensures only necessary code enters the image.
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY app/ ./app/

# Expose port
EXPOSE 8000

# Run application (production / load-test mode — 4 workers)
# Dev mode injects --reload via compose override.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--loop", "uvloop"]
