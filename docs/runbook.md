# Operational Runbook - Sabine Super Agent

## 1. Architecture Overview

The Sabine Super Agent is a personal AI assistant built on a dual-stream architecture that separates real-time response (Fast Path) from background consolidation (Slow Path). The system comprises a FastAPI backend that processes user requests, a Redis-backed rq worker for async processing, Supabase (Postgres with pgvector) for persistent storage, E2B sandboxes for secure code execution, and Slack webhooks for operational alerts.

### Component Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                             FAST PATH (< 3s)                             │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
Client ──► FastAPI ──► LangGraph Agent ──► Claude Sonnet 4 ──► Response
  │           │                                                      │
  │           └──────► Write-Ahead Log (WAL) ───────────────────────┘
  │                           │
  └───────────────────────────┼───────────────────────────────────────────┐
                              │                                           │
┌─────────────────────────────────────────────────────────────────────────┤
│                            SLOW PATH (async)                            │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                    Redis Queue (rq)
                              │
                      rq Worker Process
                              │
                    ┌─────────┴─────────┐
                    │                   │
              Consolidation         E2B Sandbox
                    │               (Skill Testing)
                    │                   │
              Supabase Postgres     Sandbox Results
              (Memory + pgvector)       │
                    │                   │
                    └───────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        SCHEDULED OPERATIONS                              │
└─────────────────────────────────────────────────────────────────────────┘

Gap Detection (Weekly) ──► Skill Gaps Table ──► Skill Proposals ──► E2B Test
                                 │
                       Weekly Digest ──► Slack Webhook

Morning Briefing (Daily) ──► Context Retrieval ──► Claude Synthesis ──► SMS

Metrics Recording (5min) ──► Task Metrics ──► Prometheus Scraper
```

## 2. Service Health Checks

| Component | Health Check | Expected Response | Port |
|-----------|-------------|-------------------|------|
| FastAPI | `GET /health` | `{"status": "healthy", "database_connected": true}` | 8001 |
| Redis | `redis-cli ping` | `PONG` | 6379 |
| rq Worker | `rq info` | Shows worker count > 0 | N/A |
| Worker Health | `GET http://localhost:8082/health` | `{"status": "healthy", "redis_connected": true}` | 8082 |
| Supabase | Check `/health` response field | `database_connected: true` | N/A |
| E2B | `GET /e2b/test` | `{"success": true}` | 8001 |
| Prometheus | `GET /metrics/prometheus` | Text format metrics | 8001 |

### Health Check Examples

```bash
# FastAPI health
curl -X GET http://localhost:8001/health

# Redis connectivity
redis-cli ping

# Worker status
rq info --url redis://localhost:6379/0

# Worker health endpoint
curl http://localhost:8082/health

# E2B sandbox test
curl -X GET "http://localhost:8001/e2b/test?code=print('hello')" \
  -H "X-API-Key: your-agent-api-key"

# Prometheus metrics
curl http://localhost:8001/metrics/prometheus

# WAL statistics
curl -X GET http://localhost:8001/wal/stats \
  -H "X-API-Key: your-agent-api-key"
```

## 3. Failure Scenarios

### 3a. Worker Crash

**Symptoms:**
- WAL pending entries growing continuously
- `/wal/stats` shows increasing `pending` count with no decrease over time
- No job completions visible in worker logs
- `GET http://localhost:8082/health` returns connection refused or 503

**Diagnosis:**
```bash
# Check worker status
rq info --url $REDIS_URL

# Should show 0 workers if crashed
# Check systemd logs (if using systemd)
journalctl -u sabine-worker -n 50

# Check Docker logs (if using Docker)
docker logs sabine-worker --tail 50

# Check Railway logs (if on Railway)
railway logs --service worker
```

**Recovery:**
```bash
# Restart worker process (systemd)
sudo systemctl restart sabine-worker

# Restart worker (Docker)
docker restart sabine-worker

# Restart worker (Railway)
railway restart --service worker

# Verify recovery
rq info --url $REDIS_URL
curl http://localhost:8082/health
```

Stuck WAL entries will auto-retry according to exponential backoff (30s, 5m, 15m).

**Prevention:**
- Configure process supervisor with automatic restart (systemd `Restart=always`, Docker `restart: unless-stopped`)
- Set memory limits in Docker to prevent OOM kills (`--memory=2g`)
- Monitor worker health endpoint with alerting on downtime > 1 minute

---

### 3b. Redis Down

**Symptoms:**
- `/invoke` returns 500 errors with "Connection refused" in logs
- WAL entries cannot be queued to rq
- Worker health endpoint shows `redis_connected: false`
- `redis-cli ping` fails

**Diagnosis:**
```bash
# Test Redis connectivity
redis-cli -u $REDIS_URL ping

# Check Redis service status
sudo systemctl status redis

# Check Redis logs
journalctl -u redis -n 50

# Check Railway Redis status (if on Railway)
railway status --service redis
```

**Recovery:**
```bash
# Restart Redis (local)
sudo systemctl restart redis

# Restart Redis (Docker)
docker restart redis

# Restart Redis (Railway)
railway restart --service redis

# Verify recovery
redis-cli -u $REDIS_URL ping
curl http://localhost:8082/health | jq .redis_connected
```

Pending WAL entries will be re-queued automatically on next worker cycle once Redis is back up.

**Prevention:**
- Enable Redis persistence (AOF or RDB) to prevent data loss
- Set up monitoring alert on Redis health check failure
- Configure Redis with automatic restart policy
- Monitor Redis memory usage (alert at > 80% capacity)

---

### 3c. Supabase Outage

**Symptoms:**
- All database operations fail with connection timeouts or 500 errors
- `/health` returns `database_connected: false`
- Logs show "Connection to Supabase failed" errors
- Agent responses degrade gracefully but no memory is stored

**Diagnosis:**
```bash
# Check Supabase status page
open https://status.supabase.com

# Verify environment variables
echo $SUPABASE_URL
echo $SUPABASE_SERVICE_ROLE_KEY | head -c 20

# Test direct connection
curl "$SUPABASE_URL/rest/v1/" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY"

# Check FastAPI health
curl http://localhost:8001/health | jq .database_connected
```

**Recovery:**
- **If Supabase outage:** Wait for Supabase recovery (check status page). No action needed - service will auto-reconnect.
- **If credential issue:** Verify `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are correct and rotate if expired.
- **If network issue:** Check firewall rules and DNS resolution.

```bash
# After recovery, verify connectivity
curl http://localhost:8001/health

# Check for pending WAL entries that need processing
curl -X GET http://localhost:8001/wal/stats \
  -H "X-API-Key: $AGENT_API_KEY"
```

**Prevention:**
- Monitor Supabase status page (subscribe to notifications)
- Implement local caching for critical reads (if needed)
- Set up alerting on `database_connected: false` in health checks
- Document credential rotation procedures

---

### 3d. E2B Sandbox Timeout

**Symptoms:**
- Skill generation jobs hang for 30+ seconds then fail
- Skill proposals created with `sandbox_passed: false`
- Logs show "E2B execution timed out" or "E2B API error"
- `/e2b/test` endpoint returns `{"success": false}`

**Diagnosis:**
```bash
# Test E2B API key validity
curl -X GET "http://localhost:8001/e2b/test?code=print('test')" \
  -H "X-API-Key: $AGENT_API_KEY"

# Check E2B status page
open https://status.e2b.dev

# Verify API key is set
echo $E2B_API_KEY | head -c 20

# Check E2B account usage/limits
# (Visit E2B dashboard: https://e2b.dev/dashboard)
```

**Recovery:**
```bash
# If API key expired, regenerate from E2B dashboard
# Update environment variable
export E2B_API_KEY="e2b_new_key_here"

# Restart FastAPI server to pick up new key
sudo systemctl restart sabine-api
# or
railway restart --service api

# Retry failed skill generation
# Re-trigger gap detection to regenerate proposals
curl -X POST http://localhost:8001/api/dream-team/tasks \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "gap_detection",
    "role": "backend-architect-sabine",
    "description": "Retry gap detection after E2B recovery"
  }'
```

The 30-second timeout auto-kills hanging sandboxes to prevent resource leaks.

**Prevention:**
- Monitor E2B API key expiry (set calendar reminder)
- Set up billing alerts in E2B dashboard to catch quota limits
- Monitor E2B status page for planned maintenance
- Alert on repeated `sandbox_passed: false` in skill proposals

---

### 3e. WAL Backlog

**Symptoms:**
- `/wal/stats` shows growing `pending` count (should be near 0 in steady state)
- Slow Path consolidation lagging behind Fast Path responses
- Users report memory not being recalled correctly
- Queue depth increasing over time

**Diagnosis:**
```bash
# Check WAL statistics
curl -X GET http://localhost:8001/wal/stats \
  -H "X-API-Key: $AGENT_API_KEY"

# Check worker health
curl http://localhost:8082/health | jq .queue_depth

# Check rq worker status
rq info --url $REDIS_URL

# View pending entries
curl -X GET "http://localhost:8001/wal/pending?limit=10" \
  -H "X-API-Key: $AGENT_API_KEY"

# View failed entries (permanently failed after max retries)
curl -X GET "http://localhost:8001/wal/failed?limit=10" \
  -H "X-API-Key: $AGENT_API_KEY"
```

**Recovery:**

**If worker is down:** Follow **3a. Worker Crash** recovery steps.

**If worker is healthy but slow:**
```bash
# Option 1: Scale workers horizontally
# Start additional worker processes
rq worker --url $REDIS_URL --name worker-2 &

# Option 2: Review permanently failed entries
curl -X GET http://localhost:8001/wal/failed \
  -H "X-API-Key: $AGENT_API_KEY"

# Investigate error patterns in failed entries
# If entries are stuck due to transient errors, they will retry
# If entries are permanently failed, review error messages and fix root cause

# Option 3: Reduce batch sizes (if memory pressure)
# Adjust checkpoint_interval in worker configuration
```

**Prevention:**
- Set up alerting when `pending` count > 50 for more than 5 minutes
- Monitor worker memory usage (see **3f. Memory Pressure**)
- Scale workers before peak usage times
- Review failed entry error patterns weekly

---

### 3f. Memory Pressure (OOM)

**Symptoms:**
- Worker process killed by OS with "Killed" in logs
- Worker health endpoint shows `memory_status: "critical"` or `memory_status: "warning"`
- `@memory_profiled_job` logs show high RSS values (> 1536 MB)
- Batch processing jobs fail mid-execution
- `GET http://localhost:8082/health` shows `memory_rss_mb` near `memory_limit_mb`

**Diagnosis:**
```bash
# Check worker memory status
curl http://localhost:8082/health | jq '{
  memory_rss_mb,
  memory_limit_mb,
  memory_percent,
  memory_status
}'

# Check system memory
free -h

# Check Docker memory limits (if using Docker)
docker stats sabine-worker

# Review memory profiling logs
journalctl -u sabine-worker | grep "memory_profiled_job"
```

**Memory status thresholds:**
- `healthy`: RSS < 1536 MB
- `warning`: 1536 MB ≤ RSS < 2048 MB
- `critical`: RSS ≥ 2048 MB (default hard limit)

**Recovery:**
```bash
# Immediate: Restart worker to clear memory
sudo systemctl restart sabine-worker
# or
docker restart sabine-worker

# If using Docker, ensure memory limit is set
docker update --memory=2g sabine-worker

# Reduce batch processing size
# Edit environment variable or worker config
export CHECKPOINT_INTERVAL=50  # Default is 100

# Restart worker with new config
sudo systemctl restart sabine-worker
```

**Prevention:**
- Set Docker memory limits (`--memory=2g --memory-reservation=1.5g`)
- Configure systemd `MemoryMax=2G` in service file
- Monitor worker health endpoint for `memory_status: "warning"`
- Alert when memory usage > 1536 MB (warning threshold)
- Review memory profiling logs weekly to identify memory leaks

---

### 3g. Slack Webhook Failure

**Symptoms:**
- No alert notifications received in Slack channel
- Weekly skill digest not delivered
- Logs show "Slack webhook POST failed" or "SLACK_WEBHOOK_URL not set"
- Critical alerts (worker failures, WAL permanent failures) not reaching team

**Diagnosis:**
```bash
# Check if webhook URL is set
echo $SLACK_WEBHOOK_URL | head -c 30

# Test webhook manually
curl -X POST $SLACK_WEBHOOK_URL \
  -H "Content-Type: application/json" \
  -d '{"text": "Test notification from runbook"}'

# Check worker logs for Slack errors
journalctl -u sabine-worker | grep -i slack

# Check if alerts are being triggered but not sent
grep "SLACK_WEBHOOK_URL not set" /var/log/sabine-worker.log
```

**Recovery:**
```bash
# Regenerate webhook URL
# 1. Go to Slack App settings: https://api.slack.com/apps
# 2. Select your app > Incoming Webhooks
# 3. Generate new webhook URL or reactivate existing one

# Update environment variable
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/NEW/WEBHOOK/URL"

# Restart services to pick up new webhook
sudo systemctl restart sabine-worker
sudo systemctl restart sabine-api

# Test webhook
curl -X POST $SLACK_WEBHOOK_URL \
  -H "Content-Type: application/json" \
  -d '{"text": "Webhook restored - monitoring active"}'

# Manually trigger weekly digest to verify
curl -X POST http://localhost:8001/api/dream-team/tasks \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "weekly_digest",
    "role": "backend-architect-sabine",
    "description": "Test weekly digest after webhook fix"
  }'
```

**Prevention:**
- Document webhook URL in secure credential store (not just env vars)
- Set up alerting on webhook POST failures (send to alternate channel or email)
- Test webhook monthly with manual notification
- Monitor Slack app status page for known issues

---

### 3h. Anthropic API Failure

**Symptoms:**
- Agent responses fail with "API error" or timeout
- Skill generation returns "Haiku generation failed" errors
- Logs show "Anthropic API rate limit exceeded" or "Invalid API key"
- `/invoke` endpoint returns 500 errors consistently
- Morning briefing synthesis fails

**Diagnosis:**
```bash
# Check if API key is set
echo $ANTHROPIC_API_KEY | head -c 20

# Test API key validity with direct call
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 10,
    "messages": [{"role": "user", "content": "Hi"}]
  }'

# Check Anthropic status page
open https://status.anthropic.com

# Review API usage/limits in Anthropic console
open https://console.anthropic.com/settings/limits

# Check logs for rate limit errors
journalctl -u sabine-api | grep -i "rate limit"
```

**Recovery:**

**If API key expired:**
```bash
# Rotate API key in Anthropic console
# Update environment variable
export ANTHROPIC_API_KEY="sk-ant-new-key-here"

# Restart services
sudo systemctl restart sabine-api
sudo systemctl restart sabine-worker
```

**If rate limit hit:**
```bash
# Wait for rate limit reset (check Anthropic console for reset time)
# Typically resets every minute for requests, hourly for tokens

# Temporarily reduce request rate or switch to cached responses
# Check current cache metrics
curl http://localhost:8001/cache/metrics

# Monitor rate limit headers in logs
tail -f /var/log/sabine-api.log | grep "x-ratelimit"
```

**If Anthropic service outage:**
```bash
# Check status page for ETA
open https://status.anthropic.com

# Consider falling back to alternative models (if configured)
# Groq, Ollama, or Together AI can be used as fallbacks
# See model_router.py for tier-based routing
```

**Prevention:**
- Monitor Anthropic API key expiry date (set to non-expiring if possible)
- Set up billing alerts in Anthropic console
- Monitor rate limit consumption (alert at > 80% of quota)
- Configure prompt caching to reduce token usage
- Subscribe to Anthropic status page notifications
- Document API key rotation procedure

---

## 4. Scheduled Jobs Reference

| Job | Schedule | Function | Description | Priority |
|-----|----------|----------|-------------|----------|
| Gap Detection | Sunday 03:00 UTC | `run_gap_detection()` (via Dream Team task queue) | Analyzes 7-day failure window in tool audit log, creates/updates skill_gaps | Medium |
| Skill Generation | Sunday 03:15 UTC | `run_skill_generation_batch()` (via rq) | Generates proposals for up to 3 open gaps per run | Medium |
| Skill Scoring | Sunday 04:00 UTC | `run_skill_effectiveness_scoring()` (via rq) | Scores promoted skills and auto-disables underperformers | Low |
| Skill Digest | Sunday 03:30 UTC | `run_weekly_digest()` (via Dream Team task queue) | Sends weekly summary of gaps, proposals, promotions to Slack | Low |
| Metrics Recording | Every 5 minutes | `POST /metrics/record` | Snapshots queue depth, role performance, task metrics for Prometheus | High |
| Morning Briefing | Daily 08:00 local (CST) | `trigger_briefing()` | Generates dual-context briefing, sends via SMS | High |
| Salience Recalculation | Daily 02:00 UTC | `run_salience_recalculation()` | Recalculates memory salience scores based on access patterns | Medium |
| Memory Archival | Weekly Saturday 01:00 UTC | `run_archive_job()` | Archives low-salience memories (salience < 0.1, older than 90 days) | Low |

### Job Configuration

Jobs are managed by different schedulers:

**APScheduler Jobs** (in FastAPI process):
- Morning Briefing: Configured via `BRIEFING_HOUR` and `SCHEDULER_TIMEZONE` env vars
- Default: 8:00 AM CST

**rq Jobs** (worker process):
- Gap Detection: Triggered by Dream Team task queue
- Skill Digest: Triggered after gap detection completes
- Salience Recalculation: Scheduled via cron or Railway scheduled job
- Memory Archival: Scheduled via cron or Railway scheduled job

**Metrics Jobs** (external cron or monitoring system):
- Metrics Recording: Called via `POST /metrics/record` every 5 minutes

### Manual Job Triggers

```bash
# Trigger morning briefing now
curl -X POST http://localhost:8001/scheduler/trigger-briefing \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_name": "Ryan", "skip_sms": false}'

# Trigger gap detection
curl -X POST http://localhost:8001/api/dream-team/tasks \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "gap_detection",
    "role": "backend-architect-sabine",
    "description": "Manual gap detection trigger"
  }'

# Trigger weekly digest
curl -X POST http://localhost:8001/api/dream-team/tasks \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "weekly_digest",
    "role": "backend-architect-sabine",
    "description": "Manual digest trigger"
  }'

# Record metrics snapshot
curl -X POST http://localhost:8001/metrics/record \
  -H "X-API-Key: $AGENT_API_KEY"

# Trigger salience recalculation
curl -X POST http://localhost:8001/api/dream-team/tasks \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "salience_recalculation",
    "role": "backend-architect-sabine",
    "description": "Manual salience recalculation"
  }'
```

---

## 5. Environment Variables Reference

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| **Core API Keys** |
| `ANTHROPIC_API_KEY` | ✓ | Anthropic API key for Claude models (primary agent logic) | `sk-ant-api03-xxx...` |
| `AGENT_API_KEY` | ✓ | API key for authenticating requests to FastAPI endpoints | Generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| **Database** |
| `SUPABASE_URL` | ✓ | Supabase project URL | `https://xxxxx.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | ✓ | Supabase service role key (full admin access) | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` |
| `DATABASE_URL` | ✗ | Direct Postgres connection URL (optional, for migrations) | `postgresql://postgres:pass@db.xxx.supabase.co:5432/postgres` |
| **Queue & Caching** |
| `REDIS_URL` | ✓ | Redis connection URL for rq job queue | `redis://localhost:6379/0` or `redis://:password@host:port/db` |
| **External Services** |
| `E2B_API_KEY` | ✓ | E2B sandbox API key for secure code execution | `e2b_xxx...` |
| `SLACK_WEBHOOK_URL` | ✗ | Slack webhook URL for weekly digests | `https://hooks.slack.com/services/T.../B.../xxx` |
| `SLACK_ALERT_WEBHOOK_URL` | ✗ | Slack webhook for critical alerts (worker failures) | `https://hooks.slack.com/services/T.../B.../xxx` |
| **SMS & Voice** |
| `TWILIO_ACCOUNT_SID` | ✗ | Twilio account SID for SMS (morning briefings) | `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `TWILIO_AUTH_TOKEN` | ✗ | Twilio auth token | `your-twilio-auth-token` |
| `TWILIO_FROM_NUMBER` | ✗ | Twilio phone number for outbound SMS | `+1234567890` |
| `USER_PHONE` | ✗ | User phone number for morning briefings (E.164 format) | `+1234567890` |
| **MCP Integrations** |
| `MCP_SERVERS` | ✗ | Space-separated list of MCP server launcher scripts | `/app/deploy/start-mcp-server.sh /app/deploy/start-github-mcp.sh` |
| `GITHUB_TOKEN` | ✗ | GitHub Personal Access Token for GitHub MCP server | `ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| **Google Workspace** |
| `GOOGLE_OAUTH_CLIENT_ID` | ✗ | OAuth client ID for Google Workspace MCP | `xxxxx.apps.googleusercontent.com` |
| `GOOGLE_OAUTH_CLIENT_SECRET` | ✗ | OAuth client secret | `GOCSPX-xxxxx` |
| `GOOGLE_REFRESH_TOKEN` | ✗ | Refresh token for headless OAuth (production) | `1//xxxxx` |
| `GMAIL_AUTHORIZED_EMAILS` | ✗ | Comma-separated list of authorized email addresses | `you@gmail.com,agent@yourdomain.com` |
| **Alternative LLM Providers** |
| `OPENAI_API_KEY` | ✗ | OpenAI API key (for Whisper, GPT-4o-mini routing) | `sk-proj-xxx...` |
| `GROQ_API_KEY` | ✗ | Groq API key (Tier 2 fast inference) | `gsk_xxx...` |
| `OLLAMA_BASE_URL` | ✗ | Ollama base URL (local models) | `http://localhost:11434` |
| **Server Configuration** |
| `API_HOST` | ✗ | FastAPI server host (default: 0.0.0.0) | `0.0.0.0` |
| `API_PORT` | ✗ | FastAPI server port (default: 8001) | `8001` |
| `WORKER_HEALTH_PORT` | ✗ | Worker health check port (default: 8082) | `8082` |
| `PORT` | ✗ | Railway-injected port (overrides WORKER_HEALTH_PORT) | `8082` |
| **Scheduler Configuration** |
| `SCHEDULER_TIMEZONE` | ✗ | Timezone for scheduled jobs (default: America/Chicago) | `America/Chicago` |
| `BRIEFING_HOUR` | ✗ | Hour for morning briefing (0-23, default: 8) | `8` |
| `BRIEFING_MINUTE` | ✗ | Minute for morning briefing (0-59, default: 0) | `0` |
| `DEFAULT_USER_ID` | ✗ | Default user UUID for single-user mode | `00000000-0000-0000-0000-000000000001` |
| **Feature Flags** |
| `EMAIL_POLL_ENABLED` | ✗ | Enable email polling fallback (default: true) | `true` |
| `EMAIL_POLL_INTERVAL_MINUTES` | ✗ | Email polling interval (default: 2) | `2` |
| **Deployment** |
| `NODE_ENV` | ✗ | Node environment (development/production) | `production` |
| `NEXT_PUBLIC_APP_URL` | ✗ | Public URL for Next.js frontend | `https://your-app.vercel.app` |
| `PYTHON_API_URL` | ✗ | Python FastAPI URL for Next.js to call | `http://127.0.0.1:8001` or `https://api.railway.app` |

### Security Notes

- **Never commit** `.env` files to version control
- Use `.env.example` for documentation, actual values in `.env.local` and `.env`
- Rotate API keys quarterly or when compromised
- Use Railway/Vercel secret management for production deployments
- Set `AGENT_API_KEY` to a strong random value (32+ characters)
- Restrict `SUPABASE_SERVICE_ROLE_KEY` access to backend services only

---

## 6. Escalation Template

Use this template when documenting production incidents.

```markdown
# Incident Report: [Brief Title]

**Severity:** [Critical / High / Medium / Low]
**Component:** [FastAPI / Worker / Redis / Supabase / E2B / Slack / External API]
**Status:** [Investigating / Identified / Resolved]
**Incident Start:** [YYYY-MM-DD HH:MM UTC]
**Incident End:** [YYYY-MM-DD HH:MM UTC]
**Duration:** [XX minutes]

---

## Timeline

| Time (UTC) | Event |
|------------|-------|
| HH:MM | Initial alert: [describe alert/symptom] |
| HH:MM | Investigation started: [actions taken] |
| HH:MM | Root cause identified: [describe cause] |
| HH:MM | Mitigation applied: [describe fix] |
| HH:MM | Service restored: [verification steps] |
| HH:MM | Incident closed |

---

## Impact

**Users Affected:** [Number or percentage of users]
**Services Degraded:** [List affected services/endpoints]
**Data Loss:** [Yes/No - describe if yes]
**Functionality Impact:**
- [Describe what users couldn't do]
- [Quantify impact if possible]

---

## Root Cause

[Detailed technical explanation of what went wrong]

**Contributing Factors:**
- [Factor 1]
- [Factor 2]

**Why It Wasn't Caught Earlier:**
- [Explain gaps in monitoring/alerting]

---

## Resolution

**Immediate Fix:**
[Describe short-term fix applied to restore service]

**Verification:**
- [ ] Service health checks passing
- [ ] Error rates returned to normal
- [ ] User functionality restored
- [ ] No data corruption detected

**Commands Used:**
```bash
# Include actual commands used for recovery
```

---

## Action Items

**Immediate (Within 24h):**
- [ ] [Action item 1 - Owner: @person]
- [ ] [Action item 2 - Owner: @person]

**Short-term (Within 1 week):**
- [ ] [Action item 3 - Owner: @person]
- [ ] Add monitoring/alerting for this failure mode

**Long-term (Within 1 month):**
- [ ] [Architectural improvements to prevent recurrence]
- [ ] Update runbook with lessons learned

---

## Lessons Learned

**What Went Well:**
- [Things that worked during incident response]

**What Could Be Improved:**
- [Areas for improvement in detection, response, or prevention]

**Documentation Updates:**
- [ ] Update runbook with this scenario
- [ ] Update monitoring alert thresholds
- [ ] Document new recovery procedures

---

**Report Author:** [Name]
**Review Date:** [YYYY-MM-DD]
**Reviewed By:** [Names]
```

---

## Additional Resources

- **PRD:** `docs/PRD_Sabine_2.0_Complete.md` - Full product requirements
- **Architecture Docs:** `docs/architecture/` - System design documentation
- **Deployment Guide:** `DEPLOYMENT.md` - Production deployment procedures
- **Test Results:** `PHASE_4_TEST_RESULTS.md` - Phase 4 test coverage
- **Supabase Dashboard:** `https://supabase.com/dashboard` - Database management
- **Anthropic Console:** `https://console.anthropic.com` - API usage and billing
- **E2B Dashboard:** `https://e2b.dev/dashboard` - Sandbox usage and API keys
- **Railway Dashboard:** `https://railway.app` - Production deployment (if using Railway)

---

## Emergency Contacts

**On-Call Rotation:**
- Primary: [Name, Contact]
- Secondary: [Name, Contact]

**Escalation Path:**
1. Check this runbook for failure scenario
2. Attempt recovery following documented procedures
3. If recovery fails or unfamiliar scenario, escalate to on-call
4. For critical/high severity: Notify team lead immediately

**External Support:**
- Supabase Support: `support@supabase.io`
- Anthropic Support: Via console ticket system
- E2B Support: `support@e2b.dev`
- Railway Support: Via dashboard support chat
