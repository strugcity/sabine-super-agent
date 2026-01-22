#!/bin/bash

# =============================================================================
# Personal Super Agent - Development Server Starter
# =============================================================================
# This script starts both the Next.js frontend and Python FastAPI backend
# in development mode with hot-reloading enabled.
# =============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Personal Super Agent - Development Mode                   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  Warning: .env file not found!${NC}"
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo ""
    echo -e "${YELLOW}Please edit .env and add your API keys before continuing.${NC}"
    echo "Press Enter to continue or Ctrl+C to exit..."
    read
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Check for required dependencies
echo -e "${BLUE}Checking dependencies...${NC}"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}✗ Node.js is not installed!${NC}"
    echo "Please install Node.js from https://nodejs.org"
    exit 1
fi
echo -e "${GREEN}✓ Node.js found:${NC} $(node --version)"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 is not installed!${NC}"
    echo "Please install Python 3.11+ from https://python.org"
    exit 1
fi
echo -e "${GREEN}✓ Python found:${NC} $(python3 --version)"

# Check npm dependencies
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing Node.js dependencies...${NC}"
    npm install
fi

# Check Python dependencies
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating Python virtual environment...${NC}"
    python3 -m venv venv
fi

echo -e "${YELLOW}Installing Python dependencies...${NC}"
source venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo -e "${GREEN}✓ All dependencies ready${NC}"
echo ""

# Kill any existing processes on ports 3000 and 8000
echo -e "${BLUE}Checking for existing servers...${NC}"
lsof -ti:3000 | xargs kill -9 2>/dev/null || true
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
echo -e "${GREEN}✓ Ports cleared${NC}"
echo ""

# Create log directory
mkdir -p logs

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Starting Servers                                           ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Start Python FastAPI server in background
echo -e "${BLUE}🐍 Starting Python FastAPI server on port 8000...${NC}"
source venv/bin/activate
python lib/agent/server.py > logs/python-api.log 2>&1 &
PYTHON_PID=$!
echo -e "${GREEN}✓ Python API running (PID: $PYTHON_PID)${NC}"
echo -e "   Logs: ${BLUE}logs/python-api.log${NC}"
echo ""

# Wait for Python server to be ready
echo -e "${YELLOW}Waiting for Python API to be ready...${NC}"
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Python API is ready!${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ Python API failed to start${NC}"
        echo "Check logs/python-api.log for details"
        kill $PYTHON_PID 2>/dev/null || true
        exit 1
    fi
done
echo ""

# Start Next.js development server in background
echo -e "${BLUE}⚛️  Starting Next.js development server on port 3000...${NC}"
npm run dev > logs/nextjs.log 2>&1 &
NEXTJS_PID=$!
echo -e "${GREEN}✓ Next.js running (PID: $NEXTJS_PID)${NC}"
echo -e "   Logs: ${BLUE}logs/nextjs.log${NC}"
echo ""

# Wait for Next.js to be ready
echo -e "${YELLOW}Waiting for Next.js to be ready...${NC}"
for i in {1..60}; do
    if curl -s http://localhost:3000 > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Next.js is ready!${NC}"
        break
    fi
    sleep 1
done
echo ""

echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   🚀 Personal Super Agent is Running!                       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Services:${NC}"
echo -e "  • Next.js Frontend:  ${GREEN}http://localhost:3000${NC}"
echo -e "  • Python API:        ${GREEN}http://localhost:8000${NC}"
echo -e "  • API Docs:          ${GREEN}http://localhost:8000/docs${NC}"
echo -e "  • Twilio Webhook:    ${GREEN}http://localhost:3000/api/chat${NC}"
echo ""
echo -e "${BLUE}Process IDs:${NC}"
echo -e "  • Python API: ${PYTHON_PID}"
echo -e "  • Next.js:    ${NEXTJS_PID}"
echo ""
echo -e "${BLUE}Logs:${NC}"
echo -e "  • Python:  ${YELLOW}tail -f logs/python-api.log${NC}"
echo -e "  • Next.js: ${YELLOW}tail -f logs/nextjs.log${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop both servers${NC}"
echo ""

# Trap Ctrl+C and kill both processes
trap "echo ''; echo -e '${YELLOW}Shutting down servers...${NC}'; kill $PYTHON_PID $NEXTJS_PID 2>/dev/null; echo -e '${GREEN}✓ Servers stopped${NC}'; exit 0" INT

# Wait for either process to exit
wait $PYTHON_PID $NEXTJS_PID
