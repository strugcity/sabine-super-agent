# =============================================================================
# Personal Super Agent - Python API + MCP Server
# =============================================================================
# This Dockerfile runs both the Python FastAPI server and workspace-mcp
# using a supervisor process to manage both services.
#
# Services:
#   - Python API (port 8001) - Main agent server
#   - workspace-mcp (port 8000) - Google Workspace MCP server
# =============================================================================

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install workspace-mcp
RUN pip install --no-cache-dir workspace-mcp

# Copy application code
COPY lib/ ./lib/
COPY scripts/ ./scripts/

# Create directories for runtime files
RUN mkdir -p /app/logs /app/data

# Copy supervisor configuration
COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Environment variables (defaults, override in Railway)
ENV PYTHONUNBUFFERED=1
ENV API_HOST=0.0.0.0
# Railway uses port 8080 for the main API
# MCP server runs internally on 8000
ENV API_PORT=8080
ENV MCP_SERVERS=http://localhost:8000/mcp

# Expose the main API port (Railway routes to 8080)
EXPOSE 8080

# Health check on port 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Start supervisor (manages both services)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
