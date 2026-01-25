#!/bin/bash
# =============================================================================
# Personal Super Agent - Local Development Startup Script (Unix/macOS/WSL)
# =============================================================================
#
# This script starts all required services for local development:
#   1. ngrok tunnel (exposes port 3000 for Gmail webhooks)
#   2. workspace-mcp server (Google Workspace MCP) - Port 8000
#   3. Python FastAPI server (Agent API) - Port 8001
#   4. Next.js frontend - Port 3000
#   5. Gmail watch setup (push notifications)
#
# Usage:
#   ./start-local.sh              # Start all services
#   ./start-local.sh --no-mcp     # Start without MCP server
#   ./start-local.sh --no-ngrok   # Start without ngrok tunnel
#   ./start-local.sh --no-gmail   # Skip Gmail watch setup
#   ./start-local.sh --help       # Show help
#
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Parse arguments
SKIP_MCP=false
SKIP_NGROK=false
SKIP_GMAIL=false
for arg in "$@"; do
    case $arg in
        --no-mcp|--skip-mcp)
            SKIP_MCP=true
            shift
            ;;
        --no-ngrok|--skip-ngrok)
            SKIP_NGROK=true
            shift
            ;;
        --no-gmail|--skip-gmail)
            SKIP_GMAIL=true
            shift
            ;;
        --help|-h)
            echo ""
            echo "Personal Super Agent - Local Development Startup"
            echo ""
            echo "USAGE:"
            echo "    ./start-local.sh              Start all services"
            echo "    ./start-local.sh --no-mcp     Start without MCP server"
            echo "    ./start-local.sh --no-ngrok   Start without ngrok tunnel"
            echo "    ./start-local.sh --no-gmail   Skip Gmail watch setup"
            echo "    ./start-local.sh --help       Show this help"
            echo ""
            echo "SERVICES STARTED:"
            echo "    1. ngrok (Port 3000 tunnel)  - Exposes local server for webhooks"
            echo "    2. workspace-mcp (Port 8000) - Google Workspace integration"
            echo "    3. Python API (Port 8001)    - FastAPI agent server"
            echo "    4. Next.js (Port 3000)       - Frontend and webhooks"
            echo "    5. Gmail Watch               - Push notification setup"
            echo ""
            echo "URLS:"
            echo "    Frontend:    http://localhost:3000"
            echo "    Agent API:   http://localhost:8001"
            echo "    API Docs:    http://localhost:8001/docs"
            echo "    MCP Server:  http://localhost:8000/mcp"
            echo ""
            exit 0
            ;;
    esac
done

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${MAGENTA}========================================${NC}"
echo -e "${MAGENTA} Personal Super Agent - Local Dev${NC}"
echo -e "${MAGENTA}========================================${NC}"
echo ""

# =============================================================================
# Pre-flight Checks
# =============================================================================

info "Running pre-flight checks..."

# Check Node.js
if command -v node &> /dev/null; then
    success "Node.js $(node --version)"
else
    error "Node.js not found. Please install Node.js 18+"
    exit 1
fi

# Check Python
if command -v python3 &> /dev/null; then
    success "Python $(python3 --version)"
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    success "Python $(python --version)"
    PYTHON_CMD="python"
else
    error "Python not found. Please install Python 3.11+"
    exit 1
fi

# Check ngrok (optional but warn if missing)
if [ "$SKIP_NGROK" = false ]; then
    if command -v ngrok &> /dev/null; then
        success "ngrok found"
    else
        warn "ngrok not found. Gmail webhooks won't work without it."
        warn "Install from: https://ngrok.com/download"
        SKIP_NGROK=true
    fi
fi

# Check .env file
if [ ! -f ".env" ]; then
    error ".env file not found. Copy .env.example to .env and configure it."
    exit 1
fi
success ".env file found"

# Check AGENT_API_KEY is set
if ! grep -q "AGENT_API_KEY=." .env; then
    error "AGENT_API_KEY not set in .env file. This is required for security."
    exit 1
fi
success "AGENT_API_KEY configured"

# Check node_modules
if [ ! -d "node_modules" ]; then
    warn "node_modules not found. Running npm install..."
    npm install
fi

# Check Python venv
if [ ! -d "venv" ]; then
    warn "Python venv not found. Creating..."
    $PYTHON_CMD -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
fi

echo ""

# =============================================================================
# Kill existing processes on our ports
# =============================================================================

info "Checking for existing processes..."

kill_port() {
    local port=$1
    local pid=$(lsof -ti :$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        warn "Port $port in use by PID $pid - killing..."
        kill -9 $pid 2>/dev/null || true
        sleep 0.5
    fi
}

kill_port 3000
kill_port 8000
kill_port 8001

# Kill existing ngrok processes
pkill -f "ngrok http" 2>/dev/null || true

echo ""

# =============================================================================
# Create logs directory
# =============================================================================

mkdir -p logs

# =============================================================================
# Cleanup function
# =============================================================================

PIDS=()
NGROK_URL=""

cleanup() {
    echo ""
    info "Shutting down services..."
    for pid in "${PIDS[@]}"; do
        if kill -0 $pid 2>/dev/null; then
            info "Stopping PID $pid..."
            kill $pid 2>/dev/null || true
        fi
    done
    pkill -f "ngrok http" 2>/dev/null || true
    kill_port 3000
    kill_port 8000
    kill_port 8001
    success "All services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

# =============================================================================
# Start Services
# =============================================================================

# --- Load Google OAuth credentials from .env ---
info "Loading Google OAuth credentials from .env..."

export GOOGLE_OAUTH_CLIENT_ID=$(grep "^GOOGLE_OAUTH_CLIENT_ID=" .env | cut -d'=' -f2-)
export GOOGLE_OAUTH_CLIENT_SECRET=$(grep "^GOOGLE_OAUTH_CLIENT_SECRET=" .env | cut -d'=' -f2-)
export USER_GOOGLE_EMAIL=$(grep "^USER_GOOGLE_EMAIL=" .env | cut -d'=' -f2-)

if [ -n "$GOOGLE_OAUTH_CLIENT_ID" ]; then
    success "GOOGLE_OAUTH_CLIENT_ID loaded"
else
    warn "GOOGLE_OAUTH_CLIENT_ID not found in .env"
fi

if [ -n "$GOOGLE_OAUTH_CLIENT_SECRET" ]; then
    success "GOOGLE_OAUTH_CLIENT_SECRET loaded"
else
    warn "GOOGLE_OAUTH_CLIENT_SECRET not found in .env"
fi

if [ -n "$USER_GOOGLE_EMAIL" ]; then
    success "USER_GOOGLE_EMAIL: $USER_GOOGLE_EMAIL"
else
    warn "USER_GOOGLE_EMAIL not found in .env"
fi

echo ""

# --- 0. Start ngrok tunnel ---
if [ "$SKIP_NGROK" = false ]; then
    info "Starting ngrok tunnel (Port 3000)..."

    ngrok http 3000 --log=stdout > logs/ngrok.log 2>&1 &
    PIDS+=($!)

    info "Waiting for ngrok to establish tunnel..."
    sleep 3

    # Try to get ngrok URL from API
    for i in {1..10}; do
        NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -o '"public_url":"https://[^"]*"' | head -1 | cut -d'"' -f4 || true)
        if [ -n "$NGROK_URL" ]; then
            success "ngrok tunnel: $NGROK_URL"
            break
        fi
        sleep 0.5
    done

    if [ -z "$NGROK_URL" ]; then
        warn "Could not get ngrok URL. Check logs/ngrok.log"
        warn "You may need to authenticate ngrok: ngrok config add-authtoken <token>"
    fi

    echo ""
else
    info "Skipping ngrok (--no-ngrok flag)"
    echo ""
fi

# --- 1. MCP Server (workspace-mcp) ---
if [ "$SKIP_MCP" = false ]; then
    info "Starting workspace-mcp server (Port 8000)..."

    # Find workspace-mcp - check PATH first, then common pip locations
    MCP_EXE=""
    if command -v workspace-mcp &> /dev/null; then
        MCP_EXE="workspace-mcp"
    elif [ -f "$HOME/.local/bin/workspace-mcp" ]; then
        MCP_EXE="$HOME/.local/bin/workspace-mcp"
    elif [ -f "$(python3 -m site --user-base)/bin/workspace-mcp" 2>/dev/null ]; then
        MCP_EXE="$(python3 -m site --user-base)/bin/workspace-mcp"
    fi

    if [ -n "$MCP_EXE" ]; then
        info "Found workspace-mcp at: $MCP_EXE"
        # Start MCP with Google OAuth env vars and HTTP transport mode
        $MCP_EXE --transport streamable-http > logs/mcp-server.log 2>&1 &
        PIDS+=($!)
        success "workspace-mcp starting... (logs: logs/mcp-server.log)"
    else
        warn "workspace-mcp not found. Install with: pip install workspace-mcp"
        warn "Continuing without MCP server..."
    fi
    sleep 2
else
    info "Skipping MCP server (--no-mcp flag)"
fi

# --- 2. Python FastAPI Server ---
info "Starting Python FastAPI server (Port 8001)..."
source venv/bin/activate
$PYTHON_CMD lib/agent/server.py > logs/python-api.log 2>&1 &
PIDS+=($!)
success "Python API starting... (logs: logs/python-api.log)"
sleep 3

# --- 3. Next.js Frontend ---
info "Starting Next.js frontend (Port 3000)..."
npm run dev > logs/nextjs.log 2>&1 &
PIDS+=($!)
success "Next.js starting... (logs: logs/nextjs.log)"
sleep 3

# --- 4. Setup Gmail Watch ---
if [ "$SKIP_GMAIL" = false ] && [ -n "$NGROK_URL" ]; then
    echo ""
    info "Setting up Gmail watch with ngrok URL..."

    $PYTHON_CMD scripts/setup_gmail_watch.py --ngrok-url "$NGROK_URL" 2>&1 | while read line; do
        if echo "$line" | grep -q "SUCCESS\|Expires on"; then
            success "$line"
        elif echo "$line" | grep -q "ERROR"; then
            error "$line"
        else
            echo "  $line"
        fi
    done
elif [ "$SKIP_GMAIL" = false ] && [ -z "$NGROK_URL" ]; then
    warn "Skipping Gmail watch setup (no ngrok URL available)"
else
    info "Skipping Gmail watch setup (--no-gmail flag)"
fi

# =============================================================================
# Summary
# =============================================================================

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN} All Services Started!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  Frontend:     http://localhost:3000"
echo "  Agent API:    http://localhost:8001"
echo "  API Docs:     http://localhost:8001/docs"
if [ "$SKIP_MCP" = false ]; then
    echo "  MCP Server:   http://localhost:8000/mcp"
fi
if [ -n "$NGROK_URL" ]; then
    echo ""
    echo -e "  ${CYAN}Public URL:   $NGROK_URL${NC}"
    echo -e "  ${CYAN}Gmail Hook:   $NGROK_URL/api/gmail/webhook${NC}"
fi
echo ""
echo "  Logs directory: ./logs/"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services...${NC}"
echo ""

# =============================================================================
# Tail logs
# =============================================================================

tail -f logs/python-api.log logs/nextjs.log 2>/dev/null || wait
