# Twilio Integration - Personal Super Agent

This document explains how the Personal Super Agent receives and responds to SMS messages via Twilio.

## Architecture Overview

The system uses a **dual-server architecture**:

1. **Next.js (Port 3000)** - Webhook receiver and proxy
2. **Python FastAPI (Port 8000)** - Agent brain (LangGraph + Claude)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Message Flow                              │
└─────────────────────────────────────────────────────────────────┘

  1. User sends SMS
       │
       ▼
  2. Twilio receives SMS
       │
       ▼
  3. Twilio sends webhook → Next.js (Port 3000)
       │                    /api/chat
       │                    • Validates phone number
       │                    • Extracts message
       ▼
  4. Next.js forwards → Python FastAPI (Port 8000)
       │                /invoke
       │                • Loads deep context
       │                • Runs LangGraph agent
       │                • Returns response
       ▼
  5. Python returns response
       │
       ▼
  6. Next.js generates TwiML
       │
       ▼
  7. Twilio receives TwiML
       │
       ▼
  8. Twilio sends SMS to user
```

## Components

### 1. Python FastAPI Server (`lib/agent/server.py`)

The brain of the system. Runs the LangGraph agent with Claude 3.5 Sonnet.

**Key Endpoints:**

- `POST /invoke` - Main endpoint for agent invocation
  ```json
  {
    "message": "What's on my schedule?",
    "user_id": "user-uuid",
    "session_id": "session-id",
    "conversation_history": []
  }
  ```

- `GET /health` - Health check
- `GET /tools` - List available tools
- `POST /test` - Quick test endpoint

**Features:**
- Loads deep context (rules, custody schedules, memories)
- Merges local skills + MCP tools
- Generates user-specific system prompts
- Handles async agent execution

**Running:**
```bash
# Development
python lib/agent/server.py

# Production
uvicorn lib.agent.server:app --host 0.0.0.0 --port 8000
```

### 2. Next.js API Route (`src/app/api/chat/route.ts`)

The proxy layer between Twilio and Python.

**Responsibilities:**
1. ✅ **Validation** - Checks if sender is authorized (`ADMIN_PHONE`)
2. 🔄 **Forwarding** - Sends message to Python API
3. 📱 **TwiML Generation** - Converts response to Twilio XML
4. 🔍 **User Lookup** - Maps phone number to user ID (TODO)

**TwiML Response Logic:**
- If response is `"Done"` → Empty TwiML (no SMS sent)
- If response has text → TwiML with `<Message>` tag
- If error → Error message via TwiML

**Example TwiML:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>Your custody schedule for this week is...</Message>
</Response>
```

### 3. Environment Configuration

**Required Variables:**

```bash
# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=your-auth-token
TWILIO_PHONE_NUMBER=+1234567890
ADMIN_PHONE=+1234567890  # Only this number can text the agent

# User Management
DEFAULT_USER_ID=00000000-0000-0000-0000-000000000000

# API Communication
PYTHON_API_URL=http://127.0.0.1:8000  # Development
# PYTHON_API_URL=https://your-api.railway.app  # Production

# Agent Configuration
ANTHROPIC_API_KEY=sk-ant-your-key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-key
```

## Development Setup

### Step 1: Install Dependencies

```bash
# Node.js dependencies
npm install

# Python dependencies
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
# Copy example file
cp .env.example .env

# Edit .env and fill in your credentials
# Required: ANTHROPIC_API_KEY, SUPABASE_*, ADMIN_PHONE
```

### Step 3: Start Both Servers

**Option A: Automated (Recommended)**
```bash
./start-dev.sh
```

This script:
- Checks dependencies
- Starts Python API on port 8000
- Starts Next.js on port 3000
- Shows logs and process IDs
- Handles graceful shutdown (Ctrl+C)

**Option B: Manual**

Terminal 1 - Python API:
```bash
source venv/bin/activate
python lib/agent/server.py
```

Terminal 2 - Next.js:
```bash
npm run dev
```

### Step 4: Test Locally

**Test Python API:**
```bash
curl http://localhost:8000/health
```

**Test Twilio Webhook (locally):**
```bash
curl -X POST http://localhost:3000/api/chat \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=+1234567890" \
  -d "Body=Hello!" \
  -d "MessageSid=SMxxxxxxxx"
```

### Step 5: Expose to Twilio (ngrok)

Twilio needs a public URL to send webhooks. Use ngrok for testing:

```bash
# Install ngrok (if not installed)
# https://ngrok.com/download

# Expose Next.js (port 3000)
ngrok http 3000

# You'll get a URL like: https://abc123.ngrok.io
```

Configure in Twilio Console:
1. Go to Phone Numbers → Your Number
2. Messaging Configuration → A Message Comes In
3. Webhook URL: `https://abc123.ngrok.io/api/chat`
4. HTTP Method: POST
5. Save

## Production Deployment

### Next.js → Vercel

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel

# Set environment variables in Vercel Dashboard:
# - PYTHON_API_URL (your Python API URL)
# - ADMIN_PHONE
# - DEFAULT_USER_ID
# - (Other required vars)
```

### Python FastAPI → Railway / Render / Fly.io

**Railway (Recommended):**

1. Create `railway.toml`:
```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "uvicorn lib.agent.server:app --host 0.0.0.0 --port $PORT"
```

2. Deploy:
```bash
railway login
railway init
railway up
```

3. Get your Railway URL (e.g., `https://your-app.railway.app`)

4. Update Vercel env var:
```
PYTHON_API_URL=https://your-app.railway.app
```

### Configure Twilio

Update webhook URL in Twilio:
```
https://your-vercel-app.vercel.app/api/chat
```

## Testing the Complete Flow

### Test 1: Health Checks

```bash
# Python API
curl https://your-api.railway.app/health

# Next.js webhook
curl https://your-app.vercel.app/api/chat
```

### Test 2: SMS Message

Send an SMS to your Twilio number from the `ADMIN_PHONE`:
```
What's on my custody schedule this week?
```

You should receive a response from the agent!

### Test 3: Check Logs

**Vercel Logs:**
```bash
vercel logs
```

**Railway Logs:**
```bash
railway logs
```

## Security Considerations

### Phone Number Validation

The system validates the sender's phone number against `ADMIN_PHONE`:

```typescript
if (ADMIN_PHONE && fromPhone !== ADMIN_PHONE) {
  return new NextResponse(
    generateTwiML('Sorry, this service is not available for your number.'),
    { status: 200, headers: { 'Content-Type': 'text/xml' } }
  );
}
```

**Production Enhancement:**
- Query `user_identities` table in Supabase
- Check if phone number is registered
- Support multiple authorized users

### API Security

**Python API:**
- Currently open (localhost only in dev)
- **TODO:** Add authentication header
- **TODO:** Rate limiting
- **TODO:** Request validation

**Next.js API:**
- Protected by phone number check
- **TODO:** Validate Twilio signature
- **TODO:** Add request logging

## Troubleshooting

### Issue: Python API not responding

**Check:**
```bash
# Is it running?
curl http://localhost:8000/health

# Check logs
tail -f logs/python-api.log

# Check process
lsof -ti:8000
```

**Solution:**
```bash
# Kill and restart
lsof -ti:8000 | xargs kill -9
python lib/agent/server.py
```

### Issue: Next.js can't reach Python API

**Check environment variable:**
```bash
echo $PYTHON_API_URL
# Should be: http://127.0.0.1:8000 (dev)
# Or: https://your-api.railway.app (prod)
```

**Test connection:**
```bash
curl $PYTHON_API_URL/health
```

### Issue: Twilio webhook times out

**Causes:**
- ngrok tunnel expired (regenerate)
- Python API is slow (check deep context loading)
- Next.js is down

**Check:**
```bash
# Test the complete flow
curl -X POST https://your-app.vercel.app/api/chat \
  -d "From=$ADMIN_PHONE" \
  -d "Body=test"
```

### Issue: Receiving error messages

**Check agent logs:**
```bash
# Python
tail -f logs/python-api.log

# Next.js
tail -f logs/nextjs.log
```

**Common errors:**
- Missing environment variables
- Database connection failed
- Anthropic API key invalid
- User ID not found

## Message Flow Examples

### Example 1: Simple Query

**User:** `What tools do you have?`

**Flow:**
1. Twilio → Next.js `/api/chat`
2. Next.js → Python `/invoke`
3. Python loads tools from registry
4. Agent generates response
5. Python → Next.js (JSON response)
6. Next.js → TwiML
7. Twilio → User (SMS)

**Response:** `I have access to weather information, custody schedule lookups, and [MCP tools if configured]...`

### Example 2: Custody Schedule

**User:** `What's my schedule this week?`

**Flow:**
1. Twilio → Next.js
2. Next.js → Python
3. Python loads deep context:
   - User rules
   - **Custody schedule** ✓
   - User config
   - Recent memories
4. Agent checks custody_schedule table
5. Returns formatted schedule
6. TwiML generated
7. SMS sent

**Response:** `Your custody schedule this week: Monday-Wednesday with Mom, Thursday-Sunday with Dad. Next pickup is Thursday at 3pm.`

### Example 3: "Done" Response

**User:** `Thanks!`

**Agent Response:** `Done`

**TwiML Generated:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response></Response>
```

**Result:** No SMS sent back (silent acknowledgment)

## Next Steps

1. ✅ Basic SMS integration working
2. 🔄 Implement user lookup from phone number
3. 🔄 Add conversation history persistence
4. 🔄 Add voice call support (Twilio Voice)
5. 🔄 Implement Twilio signature validation
6. 🔄 Add rate limiting
7. 🔄 Multi-user support
8. 🔄 Voice transcription (Whisper)

## Resources

- [Twilio SMS Quickstart](https://www.twilio.com/docs/sms/quickstart)
- [TwiML Reference](https://www.twilio.com/docs/sms/twiml)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Next.js API Routes](https://nextjs.org/docs/app/building-your-application/routing/route-handlers)
- [ngrok Documentation](https://ngrok.com/docs)
