# Deployment Guide - Railway + Vercel

This guide walks through deploying the Personal Super Agent to production using Railway (Python API + MCP) and Vercel (Next.js frontend).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Vercel                                │
│                    (Next.js Frontend)                        │
│                                                              │
│  /api/gmail/webhook  ──────────────────────┐                │
│  /api/cron/gmail-watch (every 6 days)      │                │
└────────────────────────────────────────────┼────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────┐
│                       Railway                                │
│              (Python API + MCP Server)                       │
│                                                              │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │  Python API     │◄──►│  workspace-mcp  │                │
│  │  (port 8001)    │    │  (port 8000)    │                │
│  └─────────────────┘    └─────────────────┘                │
│           │                      │                          │
│           ▼                      ▼                          │
│     Anthropic API          Google APIs                      │
│     Supabase               (Gmail, Calendar, Drive)         │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **Accounts needed:**
   - [Railway](https://railway.app) account
   - [Vercel](https://vercel.com) account
   - GitHub account (for deployment triggers)

2. **Environment variables ready:**
   - All values from your local `.env` file
   - Google OAuth credentials
   - Anthropic API key
   - Supabase credentials

## Step 1: Deploy to Railway (Python API)

### 1.1 Create Railway Project

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Connect your `personal-super-agent` repository

### 1.2 Configure Railway Service

Railway will auto-detect the `Dockerfile`. Verify the settings:

1. Go to your service → Settings
2. Ensure "Builder" is set to "Dockerfile"
3. Set "Root Directory" to `/` (default)

### 1.3 Add Environment Variables

In Railway → Variables, add all required variables:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
AGENT_API_KEY=your-secure-key

# Google OAuth (for workspace-mcp)
GOOGLE_OAUTH_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxx
USER_GOOGLE_EMAIL=sabine@strugcity.com

# Gmail Configuration
ASSISTANT_EMAIL=sabine@strugcity.com
GMAIL_AUTHORIZED_EMAILS=rknollmaier@gmail.com,sabine@strugcity.com
DEFAULT_USER_ID=00000000-0000-0000-0000-000000000001

# Google Cloud (for Gmail Pub/Sub)
GOOGLE_CLOUD_PROJECT_ID=your-project-id
```

### 1.4 Get Railway URL

After deployment:
1. Go to Settings → Networking
2. Generate a public domain (e.g., `super-agent-production.up.railway.app`)
3. Note this URL - you'll need it for Vercel

## Step 2: Deploy to Vercel (Next.js)

### 2.1 Import Project

1. Go to [Vercel Dashboard](https://vercel.com/dashboard)
2. Click "Add New..." → "Project"
3. Import your GitHub repository
4. Framework Preset: Next.js (auto-detected)

### 2.2 Add Environment Variables

In Vercel → Settings → Environment Variables:

```bash
# Railway API URL (from Step 1.4)
PYTHON_API_URL=https://super-agent-production.up.railway.app

# Security
AGENT_API_KEY=your-secure-key  # Same as Railway
CRON_SECRET=your-cron-secret   # Generate a new secret

# Gmail Configuration
GMAIL_AUTHORIZED_EMAILS=rknollmaier@gmail.com,sabine@strugcity.com
DEFAULT_USER_ID=00000000-0000-0000-0000-000000000001

# Gmail Webhook (will be your Vercel URL)
GMAIL_WEBHOOK_URL=https://your-project.vercel.app/api/gmail/webhook

# Twilio (if using SMS)
TWILIO_ACCOUNT_SID=ACxxx
TWILIO_AUTH_TOKEN=xxx
```

### 2.3 Deploy

Click "Deploy" and wait for the build to complete.

## Step 3: Update Google Cloud Pub/Sub

After Vercel deployment, update your Gmail webhook URL:

### 3.1 Update Pub/Sub Subscription

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Navigate to Pub/Sub → Subscriptions
3. Find your Gmail subscription
4. Edit → Update push endpoint to:
   ```
   https://your-project.vercel.app/api/gmail/webhook
   ```

### 3.2 Initial Gmail Watch Setup

Run locally or via Railway console:

```bash
python scripts/setup_gmail_watch.py --webhook-url https://your-project.vercel.app/api/gmail/webhook
```

## Step 4: Verify Deployment

### 4.1 Health Checks

```bash
# Check Railway API
curl https://super-agent-production.up.railway.app/health

# Check Vercel webhook
curl https://your-project.vercel.app/api/gmail/webhook
```

### 4.2 Test Email Flow

1. Send an email to `sabine@strugcity.com` from an authorized address
2. Check Railway logs for processing
3. Verify you receive an AI-generated response

## Environment Variables Reference

### Railway (Python API)

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Supabase service role key |
| `AGENT_API_KEY` | Yes | API key for authenticating requests |
| `GOOGLE_OAUTH_CLIENT_ID` | Yes | Google OAuth client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Yes | Google OAuth client secret |
| `USER_GOOGLE_EMAIL` | Yes | Agent's Google email |
| `ASSISTANT_EMAIL` | Yes | Agent's email address |
| `GMAIL_AUTHORIZED_EMAILS` | Yes | Comma-separated authorized emails |
| `DEFAULT_USER_ID` | Yes | Default Supabase user ID |
| `GOOGLE_CLOUD_PROJECT_ID` | Yes | GCP project for Pub/Sub |

### Vercel (Next.js)

| Variable | Required | Description |
|----------|----------|-------------|
| `PYTHON_API_URL` | Yes | Railway service URL |
| `AGENT_API_KEY` | Yes | Same as Railway |
| `CRON_SECRET` | Yes | Secret for cron job auth |
| `GMAIL_WEBHOOK_URL` | Yes | Your Vercel webhook URL |
| `GMAIL_AUTHORIZED_EMAILS` | Yes | Same as Railway |
| `DEFAULT_USER_ID` | Yes | Same as Railway |

## Cron Jobs

Vercel runs the Gmail watch renewal automatically:

| Endpoint | Schedule | Purpose |
|----------|----------|---------|
| `/api/cron/gmail-watch` | Every 6 days | Renew Gmail push notification watch |

## Troubleshooting

### Railway Issues

**Container not starting:**
```bash
# Check Railway logs
railway logs
```

**MCP server not responding:**
- Verify Google OAuth credentials are set
- Check supervisor logs in Railway

### Vercel Issues

**Webhook not receiving notifications:**
1. Verify Pub/Sub subscription endpoint is correct
2. Check Vercel function logs
3. Ensure `PYTHON_API_URL` is correct

**Cron not running:**
1. Verify `CRON_SECRET` is set
2. Check Vercel cron logs
3. Manually trigger: `curl -H "Authorization: Bearer $CRON_SECRET" https://your-project.vercel.app/api/cron/gmail-watch`

### Gmail Watch Issues

**Watch expired:**
```bash
# Manually renew via Railway console
python scripts/setup_gmail_watch.py --webhook-url https://your-project.vercel.app/api/gmail/webhook
```

## Monitoring

### Railway
- Dashboard shows CPU, memory, and request metrics
- Set up alerts for service health

### Vercel
- Function logs show webhook and cron executions
- Analytics show request patterns

## Cost Estimates

| Service | Plan | Estimated Cost |
|---------|------|----------------|
| Railway | Hobby | $5-10/month |
| Vercel | Free/Pro | $0-20/month |
| **Total** | | **$5-30/month** |

Costs depend on:
- Number of emails processed
- Agent API calls (Anthropic)
- Database usage (Supabase)
