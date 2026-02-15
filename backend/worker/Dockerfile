# ============================================================================
# Sabine 2.0 Background Worker - Dockerfile
# ============================================================================
# Runs the rq worker service for Slow Path processing (ADR-002).
#
# Build:
#   docker build -t sabine-worker -f backend/worker/Dockerfile .
#
# Run:
#   docker run --env-file .env sabine-worker
#
# NOTE: Build context must be the repository root so that the full
#       Python package structure (backend/, lib/) is available.
# ============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (minimal -- no build tools needed)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Health check -- uses Railway's PORT if set, otherwise 8082
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8082}/health || exit 1

# Expose the health-check port (Railway overrides with PORT env var)
EXPOSE 8082

# Run the worker entry point
CMD ["python", "-m", "backend.worker.main"]
