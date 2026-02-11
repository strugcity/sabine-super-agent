# Personal Super Agent V1

Build a device-agnostic "Super Agent" that manages family logistics, complex tasks, and "Deep Context" (Custody Schedules) via SMS and Voice using Twilio.

## ✨ What's New: Context Engine

The agent now has **long-term memory**! It automatically:
- 📝 **Remembers** every conversation (people, places, events, documents)
- 🔍 **Retrieves** relevant context before responding
- 🧠 **Learns** about your world through natural conversation

👉 See [Context Engine Documentation](CONTEXT_ENGINE_QUICKREF.md) for details.

## ⚡ Quick Start

```bash
# 1. Clone and install
npm install
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Set up database
./supabase/apply-schema.sh  # Or paste schema.sql into Supabase SQL Editor

# 4. Start both servers
./start-dev.sh
```

Visit:
- **Next.js Frontend:** http://localhost:3000
- **Memory Dashboard:** http://localhost:3000/dashboard/memory
- **Overview Dashboard:** http://localhost:3000/overview
- **Python API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health

## 🏗️ Architecture

The Personal Super Agent uses a **dual-server architecture** with **Context Engine** and **Task Orchestration**:

```
┌─────────────────────────────────────────────────────────────┐
│  User sends SMS → Twilio → Next.js (Port 3000)             │
│                            ↓                                │
│                    Python FastAPI (Port 8000)               │
│                    • LangGraph Agent                        │
│                    • Claude 3.5 Sonnet (+ Groq/Ollama)     │
│                    • Context Engine                         │
│                      - Memory Ingestion                     │
│                      - Vector Search (pgvector)             │
│                      - Entity Extraction & Graph            │
│                    • Deep Context Injection                 │
│                    • Task Queue & WAL                       │
│                    • Local Skills + MCP Tools               │
│                      - Gmail (MCP)                          │
│                      - Google Calendar                      │
│                      - Slack (Socket Mode)                  │
│                      - GitHub                               │
│                      - E2B Sandbox                          │
│                            ↓                                │
│                    TwiML/Response → External Services       │
└─────────────────────────────────────────────────────────────┘
```

## 🛠️ Technical Stack

- **Frontend/API:** Next.js 15 (App Router) on Vercel
- **Backend Logic:** Python 3.11+ with LangGraph + FastAPI
- **Agent Brain:** Anthropic Claude 3.5 Sonnet (with Groq/Ollama fallbacks)
- **Database:** Supabase (Postgres + pgvector)
- **Messaging:** Twilio API (SMS)
- **Integrations:** Gmail (MCP), Google Calendar, Slack (Socket Mode), GitHub, E2B Sandbox
- **Infrastructure:** Model Context Protocol (MCP), Write-Ahead Log (WAL), Task Queue

## 📁 Project Structure

```
sabine-super-agent/
├── src/                          # Next.js source
│   └── app/
│       ├── api/
│       │   ├── chat/            # Chat endpoint
│       │   ├── gmail/           # Gmail webhook handler
│       │   ├── memory/          # Memory API routes
│       │   └── cron/            # Cron jobs (Gmail watch renewal)
│       ├── dashboard/           # Dashboard pages
│       │   └── memory/          # Memory management UI
│       └── overview/            # Task overview dashboard
│
├── lib/
│   ├── agent/                   # Python agent core
│   │   ├── core.py             # LangGraph orchestrator
│   │   ├── registry.py         # Unified tool registry
│   │   ├── mcp_client.py       # MCP integration
│   │   ├── server.py           # FastAPI server
│   │   ├── memory.py           # Context engine ingestion
│   │   ├── retrieval.py        # Vector search & retrieval
│   │   ├── gmail_handler.py    # Gmail processing
│   │   ├── slack_manager.py    # Slack Socket Mode
│   │   ├── scheduler.py        # Reminder scheduler
│   │   └── routers/            # FastAPI route handlers
│   │       ├── sabine.py       # Core agent endpoints
│   │       ├── dream_team.py   # Task orchestration
│   │       ├── gmail.py        # Gmail endpoints
│   │       ├── memory.py       # Memory endpoints
│   │       └── observability.py # Health & metrics
│   │
│   ├── skills/                  # Local Python skills
│   │   ├── github/             # GitHub issue management
│   │   ├── calendar/           # Google Calendar
│   │   ├── slack_ops/          # Slack messaging
│   │   ├── reminder/           # Reminders (SMS/Email/Slack)
│   │   ├── custody/            # Custody schedule
│   │   ├── weather/            # Weather forecasts
│   │   ├── e2b_sandbox/        # Secure code execution
│   │   └── project_sync/       # Project synchronization
│   │
│   └── db/                      # Database interactions
│
├── backend/
│   └── services/                # Backend services
│       ├── wal.py              # Write-Ahead Log
│       ├── task_queue.py       # Task queue management
│       └── output_sanitization.py # Security sanitization
│
├── supabase/
│   └── schema.sql              # Database schema
│
├── docs/                        # Documentation
│   ├── TWILIO_INTEGRATION.md   # Twilio setup guide
│   ├── MEMORY_ARCHITECTURE.md  # Context engine docs
│   └── PRD_Sabine_2.0_Complete.md # Product requirements
│
├── start-dev.sh                # Development server starter
└── requirements.txt            # Python dependencies
```

## 🚀 Getting Started

### Prerequisites

- **Node.js** 18+
- **Python** 3.11+
- **Supabase** account
- **Anthropic API** key
- **Twilio** account (for SMS)

### 1. Install Dependencies

```bash
# Node.js
npm install

# Python
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Database Setup

1. Create a Supabase project at https://supabase.com
2. Apply the schema:
   - Option A: Copy `supabase/schema.sql` into Supabase SQL Editor and run
   - Option B: Run `./supabase/apply-schema.sh` (requires psql)

### 3. Environment Configuration

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

**Required:**
```bash
# Anthropic API (main agent)
ANTHROPIC_API_KEY=sk-ant-your-key

# Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-key

# Admin access
ADMIN_PHONE=+1234567890
DEFAULT_USER_ID=00000000-0000-0000-0000-000000000000
```

**Optional Integrations:**
```bash
# Multi-provider LLM (cost optimization)
GROQ_API_KEY=gsk-your-groq-key
OLLAMA_BASE_URL=http://localhost:11434

# Gmail Integration (MCP)
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GMAIL_USER_REFRESH_TOKEN=your-refresh-token
GMAIL_AGENT_REFRESH_TOKEN=your-agent-refresh-token

# Slack Integration (Socket Mode)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_CHANNEL_ID=C1234567890

# GitHub Integration
GITHUB_TOKEN=ghp_your-personal-access-token

# E2B Sandbox (secure code execution)
E2B_API_KEY=e2b_your-api-key

# Twilio (SMS)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_PHONE_NUMBER=+1234567890

# Model Context Protocol
MCP_SERVERS=/app/deploy/start-mcp-server.sh /app/deploy/start-github-mcp.sh
```

### 4. Start Development Servers

**Automated (Recommended):**
```bash
./start-dev.sh
```

**Manual:**

Terminal 1 - Python API:
```bash
source venv/bin/activate
python lib/agent/server.py
```

Terminal 2 - Next.js:
```bash
npm run dev
```

### 5. Test Locally

```bash
# Test Python API
curl http://localhost:8000/health

# Test Twilio webhook
curl -X POST http://localhost:3000/api/chat \
  -d "From=+1234567890" \
  -d "Body=Hello!"
```

### 6. Expose to Twilio (Development)

```bash
# Install ngrok
brew install ngrok  # macOS
# or download from https://ngrok.com

# Expose Next.js
ngrok http 3000

# Configure webhook in Twilio Console:
# https://abc123.ngrok.io/api/chat
```

## 🎯 Key Features

### ✅ Implemented

**Core Agent:**
- **Deep Context Injection** - Loads user rules, custody schedules, config, and memories before each query
- **Context Engine** - Long-term memory with automatic entity extraction and vector search
- **Unified Tool Registry** - Seamlessly merges local Python skills with remote MCP integrations
- **Prompt Caching** - Reduces latency and costs via cached context
- **Write-Ahead Log (WAL)** - Durability layer for critical operations
- **Task Queue** - Background task management with dependency tracking

**Integrations (Production-Ready):**
- **Gmail** - Email handling via MCP, push notifications, auto-classification
- **Google Calendar** - Event creation/retrieval with SMS reminders
- **Slack** - Socket Mode integration ("The Gantry") with threaded updates
- **GitHub** - Issue management, repo operations, authorization checks
- **E2B Sandbox** - Secure Python code execution with timeout protection
- **Twilio** - SMS notifications for reminders

**Skills/Tools (11+):**
- GitHub operations (issues, comments, file ops)
- Calendar events (get/create with reminders)
- Slack messaging (team updates with threading)
- Reminder management (create/list/cancel via SMS/Email/Slack)
- Custody schedule queries
- Weather forecasts
- Secure code execution
- Project synchronization

**Frontend:**
- **Memory Dashboard** - Entity management, file upload, memory stream viewer
- **Overview Dashboard** - Task statistics and activity log
- **Theme Support** - Dark/light mode toggle
- **Mobile-Responsive** - Tailwind CSS design

**API (40+ Endpoints):**
- Core agent invocation (`/invoke`, `/invoke/cached`)
- Task orchestration (Dream Team - 25+ endpoints)
- Gmail handling and diagnostics
- Memory ingestion and query
- Health checks and observability metrics

### 🔄 In Progress

- Voice call support (Twilio Voice + Whisper)
- Multi-user support with user lookup
- Enhanced conversation history UI
- Additional MCP server integrations

### 📋 Roadmap

- Twilio signature validation
- Rate limiting and authentication
- Voice transcription (OpenAI Whisper)
- Google Drive integration (MCP)
- Production deployment automation
- Enhanced analytics dashboard

## 📚 Documentation

- **[Context Engine Quick Reference](CONTEXT_ENGINE_QUICKREF.md)** - Memory and entity management
- **[Context Engine Complete](CONTEXT_ENGINE_COMPLETE.md)** - Detailed architecture
- **[Twilio Integration Guide](docs/TWILIO_INTEGRATION.md)** - Complete guide for SMS setup
- **[Agent Core README](lib/agent/README.md)** - Deep dive into agent architecture
- **[Supabase README](supabase/README.md)** - Database schema documentation
- **[Deployment Guide](DEPLOYMENT.md)** - Railway + Vercel production setup
- **[Product Requirements](docs/PRD_Sabine_2.0_Complete.md)** - Complete product vision

## 🧪 Testing

### Test the Agent

```bash
# Run interactive API test
python test_api_interactive.py

# Test memory ingestion
python test_memory_ingestion.py

# Test Gmail integration
python test_gmail_e2e.py

# Test security
python test_security_uat.py
```

### Test Endpoints

```bash
# Health check
curl http://localhost:8000/health

# List available tools
curl http://localhost:8000/tools

# Get system metrics
curl http://localhost:8000/metrics

# Invoke agent with caching
curl -X POST http://localhost:8000/invoke/cached \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What tools do you have?",
    "user_id": "00000000-0000-0000-0000-000000000000",
    "session_id": "test-session"
  }'

# Memory ingestion
curl -X POST http://localhost:8000/memory/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "00000000-0000-0000-0000-000000000000",
    "text": "John prefers morning meetings on Tuesdays"
  }'
```

## 🌐 Production Deployment

### Next.js → Vercel

```bash
vercel
```

Set environment variables in Vercel Dashboard:
- `PYTHON_API_URL` (your Python API URL)
- `ADMIN_PHONE`
- `DEFAULT_USER_ID`

### Python API → Railway

```bash
railway init
railway up
```

Update `PYTHON_API_URL` in Vercel to your Railway URL.

See [TWILIO_INTEGRATION.md](docs/TWILIO_INTEGRATION.md) for detailed deployment instructions.

## 🔒 Security

- ✅ Phone number validation (ADMIN_PHONE)
- ✅ Environment variable protection
- ⚠️ TODO: Twilio signature validation
- ⚠️ TODO: Rate limiting
- ⚠️ TODO: Request authentication

## 🤝 Contributing

This is a personal project, but feel free to fork and adapt for your own use!

## 📄 License

MIT

