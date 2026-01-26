# =============================================================================
# Personal Super Agent - Python API + MCP Server
# =============================================================================
# This Dockerfile runs both the Python FastAPI server and workspace-mcp
# using a supervisor process to manage both services.
#
# Services:
#   - Python API (Railway's PORT) - Main agent server (external)
#   - workspace-mcp (port 8000) - Google Workspace MCP server (internal)
#
# Railway injects PORT env var - the Python API listens on that port.
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

# Copy MCP credential setup script and MCP server wrapper
COPY deploy/setup-mcp-credentials.sh /app/setup-mcp-credentials.sh
COPY deploy/start-mcp-server.sh /app/deploy/start-mcp-server.sh
RUN chmod +x /app/setup-mcp-credentials.sh /app/deploy/start-mcp-server.sh

# Environment variables (defaults, override in Railway)
ENV PYTHONUNBUFFERED=1
ENV API_HOST=0.0.0.0
# MCP server runs internally on 8000
ENV MCP_SERVERS=http://localhost:8000/mcp

# Note: Railway injects PORT env var at runtime
# The server reads PORT directly and listens on it
# No need to EXPOSE or hardcode - Railway handles networking

# Start supervisor (manages both services)
# First setup MCP credentials from environment variables, then start supervisor
CMD ["/bin/bash", "-c", "/app/setup-mcp-credentials.sh && /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf"]
