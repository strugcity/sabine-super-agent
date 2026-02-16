# Sabine Super Agent

A personal AI agent that manages family logistics, complex tasks, and deep contextual memory. Sabine learns from every interaction, autonomously acquires new skills, and operates across SMS, email, Slack, and web interfaces.

## Architecture

```
                          SMS / Email / Slack / Web
                                    |
                     +--------------+--------------+
                     |                             |
              Next.js 15 (3000)            FastAPI (8001)
              - Chat webhook               - LangGraph Agent
              - Gmail push hook            - Claude Sonnet (primary)
              - Memory dashboard           - Groq / Ollama fallbacks
              - Overview dashboard         - Prompt Caching
                     |                             |
                     +----------+------------------+
                                |
          +---------------------+---------------------+
          |                     |                      |
    Supabase (Postgres)   Redis + rq Worker    External Services
    - pgvector search     - WAL consolidation   - Gmail (MCP)
    - 29 tables           - Salience scoring    - Google Calendar
    - 41 migrations       - Gap detection       - Slack (Socket Mode)
                          - Skill generation    - GitHub
                          - Effectiveness       - E2B Sandbox
                            scoring             - Twilio (SMS)
```

**Dual-Stream Pipeline:** Fast Path delivers responses in under 3 seconds. The Slow Path asynchronously consolidates memories, extracts entities, and updates the knowledge graph via a Write-Ahead Log and Redis job queue.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, React 19, Tailwind CSS, TypeScript |
| Backend | Python 3.11+, FastAPI, LangGraph, Pydantic v2 |
| Agent Brain | Claude Sonnet (primary), Groq, Ollama (fallbacks) |
| Database | Supabase (Postgres + pgvector), 29 tables, 41 migrations |
| Job Queue | Redis + rq (9 job types) |
| Integrations | Gmail (MCP), Google Calendar, Slack, GitHub, E2B, Twilio |
| Observability | Prometheus, Grafana, structured logging |

## Quick Start

```bash
# 1. Clone and install
npm install
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys (see Environment section below)

# 3. Start servers
./start-dev.sh
```

| Service | URL |
|---------|-----|
| Next.js Frontend | http://localhost:3000 |
| Memory Dashboard | http://localhost:3000/dashboard/memory |
| Overview Dashboard | http://localhost:3000/overview |
| FastAPI Backend | http://localhost:8001 |
| API Docs (Swagger) | http://localhost:8001/docs |
| Health Check | http://localhost:8001/health |

## Key Features

### Context Engine (Long-Term Memory)

Sabine remembers everything. Every conversation is ingested, entities are extracted, and memories are stored with vector embeddings for semantic retrieval. A nightly salience recalculation ensures the most relevant memories float to the top.

- **MAGMA** (Multi-Graph Memory Architecture) with 4 layers: people, events, causes, concepts
- **Salience scoring** with configurable per-user weights (Recency, Frequency, Utility)
- **Entity extraction** and relationship graph with traversal queries
- **Automatic archival** of low-salience memories

### Autonomous Skill Acquisition

Sabine detects its own capability gaps and learns new skills without human intervention:

1. **Gap Detection** -- Analyzes tool audit logs for recurring failures
2. **Skill Generation** -- Claude Haiku generates handler code + tests
3. **Sandbox Testing** -- E2B sandbox validates the code before promotion
4. **Promotion** -- Approved skills hot-reload into the live tool registry
5. **Effectiveness Tracking** -- Dopamine score (success rate, edit rate, repetition, gratitude signals) auto-disables underperformers

### Self-Improvement Loop

Pattern-based signal classifier detects implicit user feedback (gratitude, frustration, repetition) without LLM calls. Feeds into weekly effectiveness scoring that auto-disables skills below a 0.3 threshold after 10+ executions.

### Multi-Provider LLM Routing

Intelligent model router selects the optimal LLM tier per request based on role, task complexity, and cost. Supports Anthropic Claude (premium), Groq (fast), and Ollama (local/free) with automatic fallback chains.

### Deep Context Injection

Before every response, Sabine loads the user's active rules, custody schedule, preferences, and recent memories into the system prompt. Prompt caching reduces costs by up to 90% on repeated calls.

### Integrations (13 Skills)

| Skill | Description |
|-------|-------------|
| Gmail (MCP) | Search, read, send, auto-classify with domain compartmentalization |
| Google Calendar | Event CRUD with conflict detection and SMS reminders |
| Slack (Socket Mode) | Threaded messaging, team updates |
| GitHub | Issue management, repo operations |
| E2B Sandbox | Secure Python execution with 30s timeout |
| Reminders | Create/list/cancel via SMS, email, or Slack |
| Custody Schedule | Family logistics with custody-aware scheduling |
| Weather | Forecasts and conditions |
| Project Sync | Project data synchronization |

### Belief Revision

Sabine maintains beliefs about the user's world with confidence scores, detects contradictions, and uses Value-of-Information gating to decide when to ask clarifying questions vs. proceeding autonomously.

## Project Structure

```
sabine-super-agent/
+-- lib/
|   +-- agent/                # Core agent (44 files)
|   |   +-- core.py           # LangGraph orchestrator + telemetry
|   |   +-- server.py         # FastAPI server (port 8001)
|   |   +-- sabine_agent.py   # Main Sabine agent
|   |   +-- registry.py       # Unified tool registry (MCP + DB skills)
|   |   +-- model_router.py   # Multi-provider LLM routing
|   |   +-- memory.py         # Context engine ingestion
|   |   +-- retrieval.py      # Vector search + context retrieval
|   |   +-- scheduler.py      # APScheduler (briefings, reminders)
|   |   +-- routers/          # 11 FastAPI routers
|   |   +-- providers/        # LLM providers (Anthropic, Groq, Ollama)
|   +-- skills/               # 13 local Python skills
|   +-- db/                   # Database models + loaders
|   +-- parallel/             # Parallel session tracking (dev tooling)
|
+-- backend/
|   +-- services/             # 21 backend services
|   |   +-- wal.py            # Write-Ahead Log
|   |   +-- fast_path.py      # Hot-path request handling
|   |   +-- salience.py       # Memory salience scoring
|   |   +-- gap_detection.py  # Skill gap analysis
|   |   +-- skill_generator.py      # Auto skill generation (Haiku)
|   |   +-- skill_promotion.py      # Promote/disable/rollback skills
|   |   +-- skill_effectiveness.py  # Dopamine scoring + auto-disable
|   |   +-- signal_classifier.py    # Implicit feedback classification
|   |   +-- audit_logging.py        # Tool execution audit trail
|   |   +-- task_queue.py           # Multi-agent task orchestration
|   +-- worker/               # rq worker (11 files, 9 job types)
|   +-- belief/               # Belief revision + conflict detection
|   +-- inference/            # VOI gating + push-back patterns
|   +-- magma/                # MAGMA knowledge graph
|
+-- src/                      # Next.js 15 frontend
|   +-- app/
|   |   +-- page.tsx          # Home
|   |   +-- overview/         # Task overview dashboard
|   |   +-- dashboard/memory/ # Memory management dashboard
|   |   +-- api/chat/         # Twilio SMS webhook
|   |   +-- api/gmail/        # Gmail push notification handler
|   +-- components/           # 8 React components
|
+-- supabase/migrations/      # 41 database migrations
+-- tests/                    # 60 test files (unit, integration, load)
+-- docs/                     # 40+ docs (ADRs, plans, PRD, runbook)
+-- infra/                    # Prometheus + Grafana monitoring
+-- scripts/                  # Dev tooling (dashboard, verification)
```

## API Routers (11)

| Router | Prefix | Purpose |
|--------|--------|---------|
| `sabine.py` | -- | Core agent chat + task handling |
| `dream_team.py` | -- | Multi-agent task orchestration |
| `gmail.py` | `/gmail` | Email operations |
| `memory.py` | `/memory` | Memory CRUD, search, ingestion |
| `archive.py` | `/api/archive` | Memory archival management |
| `graph.py` | `/api/graph` | Entity relationship graph |
| `queue_routes.py` | `/api/queue` | Task queue operations |
| `skills.py` | `/api/skills` | Skill registry + management |
| `salience_settings.py` | `/api/settings` | Salience weight configuration |
| `user_config.py` | `/api/settings` | User preferences |
| `observability.py` | -- | Health checks, Prometheus metrics |

## Scheduled Jobs

The rq worker runs 9 job types on a weekly/nightly schedule:

| Job | Schedule | Purpose |
|-----|----------|---------|
| Salience Recalculation | Daily 04:00 UTC | Recalculate memory importance scores |
| Memory Archival | Daily 04:30 UTC | Archive low-salience memories |
| Gap Detection | Sunday 03:00 UTC | Find recurring tool failures |
| Skill Generation | Sunday 03:15 UTC | Generate proposals for open gaps (max 3) |
| Skill Digest | Sunday 03:30 UTC | Weekly summary via Slack |
| Skill Scoring | Sunday 04:00 UTC | Dopamine scoring + auto-disable |
| Morning Briefing | Daily 08:00 CST | Dual-context briefing via SMS |

## Environment Configuration

Copy `.env.example` and configure:

**Required:**
```bash
ANTHROPIC_API_KEY=sk-ant-...          # Primary LLM
SUPABASE_URL=https://....supabase.co  # Database
SUPABASE_SERVICE_ROLE_KEY=...         # DB service key
REDIS_URL=redis://...                 # Job queue
DEFAULT_USER_ID=...                   # Your user UUID
ADMIN_PHONE=+1...                     # Admin phone for SMS
```

**Optional Integrations:**
```bash
GROQ_API_KEY=...                # Fast LLM fallback
OLLAMA_BASE_URL=...             # Local LLM fallback
GOOGLE_CLIENT_ID=...            # Gmail / Calendar
GOOGLE_CLIENT_SECRET=...
SLACK_BOT_TOKEN=xoxb-...        # Slack integration
SLACK_APP_TOKEN=xapp-...
GITHUB_TOKEN=ghp_...            # GitHub integration
E2B_API_KEY=...                 # Sandbox execution
TWILIO_ACCOUNT_SID=...          # SMS
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
```

See `.env.example` for the full list (195 lines covering all integrations).

## Testing

```bash
# Run all unit tests
pytest tests/ -v

# Run specific test suites
pytest tests/test_skill_effectiveness.py -v   # Skill scoring
pytest tests/test_signal_classifier.py -v     # Signal classification
pytest tests/test_gap_detection.py -v         # Gap detection

# Run load tests (requires running server)
cd tests/load && locust -f locustfile.py

# Syntax check Python files
python -m py_compile lib/agent/core.py

# Lint frontend
npm run lint
npm run build
```

**Test markers:**
- `@pytest.mark.integration` -- requires live database
- `@pytest.mark.benchmark` -- performance tests
- `@pytest.mark.slow` -- extended runtime

## Monitoring

Local observability stack via Docker Compose:

```bash
cd infra
docker-compose -f docker-compose.monitoring.yml up -d
```

| Service | URL |
|---------|-----|
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 (admin/admin) |

The `sabine-overview` Grafana dashboard tracks request latency, success rates, queue depth, and worker health.

## Production Deployment

| Component | Platform |
|-----------|----------|
| Next.js Frontend | Vercel |
| FastAPI Backend | Railway |
| Database | Supabase |
| Redis | Railway (auto-provisioned) |

See [Deployment Guide](DEPLOYMENT.md) and [docs/runbook.md](docs/runbook.md) for operational procedures.

## Documentation

| Document | Description |
|----------|-------------|
| [PRD (Sabine 2.0)](docs/PRD_Sabine_2.0_Complete.md) | Complete product requirements |
| [Runbook](docs/runbook.md) | Operational procedures + incident response |
| [Self-Improvement Loop](docs/plans/self-improvement-loop.md) | Effectiveness tracker + signal classifier spec |
| [Memory Architecture](CONTEXT_ENGINE_COMPLETE.md) | Context engine deep dive |
| [Parallel Work Guide](docs/plans/parallel-work-best-practices.md) | Multi-agent dispatch protocol |
| [ADR-001 through ADR-004](docs/) | Architecture decision records |
| [Twilio Integration](docs/TWILIO_INTEGRATION.md) | SMS setup guide |

## License

MIT
