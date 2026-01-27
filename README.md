# Personal Super Agent V1

Build a device-agnostic "Super Agent" that manages family logistics, complex tasks, and "Deep Context" (Custody Schedules) via SMS and Voice using Twilio.

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
- **Next.js:** http://localhost:3000
- **Python API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

## 🏗️ Architecture

The Personal Super Agent uses a **dual-server architecture**:

```
┌─────────────────────────────────────────────────────────┐
│  User sends SMS → Twilio → Next.js (Port 3000)         │
│                            ↓                            │
│                    Python FastAPI (Port 8000)           │
│                    • LangGraph Agent                    │
│                    • Claude 3.5 Sonnet                  │
│                    • Deep Context Injection             │
│                    • Local Skills + MCP Tools           │
│                            ↓                            │
│                    TwiML Response → Twilio → User      │
└─────────────────────────────────────────────────────────┘
```

## 🛠️ Technical Stack

- **Frontend/API:** Next.js 14+ (App Router) on Vercel
- **Backend Logic:** Python 3.11+ with LangGraph + FastAPI
- **Agent Brain:** Anthropic Claude 3.5 Sonnet
- **Database:** Supabase (Postgres + pgvector)
- **Messaging:** Twilio API
- **Integrations:** Model Context Protocol (MCP)

## 📁 Project Structure

```
personal-super-agent/
├── src/                          # Next.js source
│   └── app/
│       └── api/chat/             # Twilio webhook handler
│
├── lib/
│   ├── agent/                    # Python agent core
│   │   ├── core.py              # LangGraph orchestrator
│   │   ├── registry.py          # Unified tool registry
│   │   ├── mcp_client.py        # MCP integration
│   │   └── server.py            # FastAPI server
│   │
│   └── skills/                   # Local Python skills
│       ├── weather/             # Weather skill
│       └── custody/             # Custody schedule skill
│
├── supabase/
│   └── schema.sql               # Database schema
│
├── docs/
│   └── TWILIO_INTEGRATION.md    # Detailed Twilio guide
│
├── start-dev.sh                 # Development server starter
└── requirements.txt             # Python dependencies
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
ANTHROPIC_API_KEY=sk-ant-your-key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-key
ADMIN_PHONE=+1234567890
```

**Optional (for MCP integrations):**
```bash
MCP_SERVERS=https://gdrive-mcp.example.com/sse
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

- **Deep Context Injection** - Loads user rules, custody schedules, config, and memories before each query
- **Unified Tool Registry** - Seamlessly merges local Python skills with remote MCP integrations
- **SMS Integration** - Receive and respond to SMS via Twilio
- **Phone Number Validation** - Only authorized users can interact
- **Dual-Brain Memory** - Vector store (pgvector) + Knowledge graph (SQL)
- **FastAPI Server** - Exposes agent via HTTP endpoints
- **Development Tools** - Automated startup script and comprehensive logging

### 🔄 In Progress

- Voice call support (Twilio Voice + Whisper)
- Conversation history persistence
- Multi-user support with user lookup
- Memory storage and retrieval
- Additional local skills

### 📋 Roadmap

- Twilio signature validation
- Rate limiting
- Voice transcription (OpenAI Whisper)
- Google Drive integration (MCP)
- Calendar integration (MCP)
- Production deployment guides

## 📚 Documentation

- **[Twilio Integration Guide](docs/TWILIO_INTEGRATION.md)** - Complete guide for SMS setup
- **[Agent Core README](lib/agent/README.md)** - Deep dive into agent architecture
- **[Supabase README](supabase/README.md)** - Database schema documentation

## 🧪 Testing

### Test the Agent

```python
# Run example usage script
python lib/agent/example_usage.py
```

### Test Endpoints

```bash
# Health check
curl http://localhost:8000/health

# List tools
curl http://localhost:8000/tools

# Invoke agent
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What tools do you have?",
    "user_id": "00000000-0000-0000-0000-000000000000",
    "session_id": "test-session"
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

