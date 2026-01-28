# =============================================================================
# Personal Super Agent - Python API + Node.js MCP Server
# =============================================================================
# Multi-stage build supporting both Python (FastAPI) and Node.js (workspace-mcp)
# This Dockerfile runs both services using supervisor process management.
#
# Stage 1: Python base with Node.js runtime
# Services:
#   - Python API (Railway's PORT) - Main agent server (external)
#   - workspace-mcp (Node.js CLI) - Google Workspace MCP server (internal, Stdio transport)
#
# Why multi-runtime: workspace-mcp is a Node.js CLI tool, not Python
# Railway injects PORT env var - the Python API listens on that port.
# =============================================================================

FROM python:3.11-slim

# Install system dependencies including Node.js
RUN apt-get update && apt-get install -y \
    supervisor \
    curl \
    ca-certificates \
    gnupg \
    lsb-release \
    libsecret-1-0 \
    libsecret-1-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (v20 LTS) via NodeSource repository
# workspace-mcp CLI requires Node.js to execute
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Verify Node.js and npm installation
RUN node --version && npm --version

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install workspace-mcp from npm (Node.js CLI for Google Workspace integration)
# This is installed globally so npx can find and execute it
RUN npm install -g @presto-ai/google-workspace-mcp && \
    npm cache clean --force

# Copy application code
COPY lib/ ./lib/
COPY scripts/ ./scripts/

# Create directories for runtime files
RUN mkdir -p /app/logs /app/data

# Create credentials directory that MCP server will use
RUN mkdir -p /root/.google_workspace_mcp/credentials && \
    chmod 700 /root/.google_workspace_mcp/credentials

# Copy supervisor configuration
COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy MCP credential setup script and MCP server wrapper
COPY deploy/setup-mcp-credentials.sh /app/setup-mcp-credentials.sh
COPY deploy/start-mcp-server.sh /app/deploy/start-mcp-server.sh
RUN chmod +x /app/setup-mcp-credentials.sh /app/deploy/start-mcp-server.sh

# Environment variables (defaults, override in Railway)
ENV PYTHONUNBUFFERED=1
ENV API_HOST=0.0.0.0
# MCP server uses Stdio transport (direct subprocess communication via stdin/stdout)
# The start-mcp-server.sh wrapper script launches workspace-mcp via npx
# registry.py parses this to create StructuredTool wrappers
ENV MCP_SERVERS=/app/deploy/start-mcp-server.sh
ENV NODE_ENV=production
ENV WORKSPACE_MCP_PORT=8000

# Health check: verify Python API is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Start supervisor (manages both Python API and workspace-mcp via start-mcp-server.sh)
# Step 1: Setup MCP credentials from Railway environment variables
# Step 2: Start supervisor to manage both services
CMD ["/bin/bash", "-c", "/app/setup-mcp-credentials.sh && /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf"]
