# Worker-Service Stability Plan

**Date:** 2026-02-17
**Status:** Draft — awaiting review
**Goal:** Achieve industry-standard deployment reliability (99.9% deploy success, <30s recovery)

---

## Executive Summary

The worker-service has failed to deploy twice after merging `claude/sabine-email-attachments-0MBJC`. Code analysis reveals **no Python-level bug introduced by that PR** — the PR changed only `lib/agent/` and `lib/skills/`, which the worker never imports. The failures are **infrastructure and startup-resilience issues** that surface when Railway triggers a redeployment.

This plan identifies **7 root-cause candidates**, ranks them by likelihood, and prescribes a fix + pre-test for each. Fixes are ordered so the highest-impact items come first.

---

## Root-Cause Analysis Matrix

| # | Candidate | Likelihood | Evidence | Impact if True |
|---|-----------|-----------|----------|----------------|
| 1 | Redis unavailable at startup → `sys.exit(1)` crash loop | **HIGH (70%)** | `main.py:262` exits immediately; no retry; Railway cold-starts Redis add-on in parallel with service | Container never starts |
| 2 | Missing/wrong `REDIS_URL` env var on worker-service in Railway dashboard | **HIGH (60%)** | Default is `redis://localhost:6379/0` which fails in Railway; `railway.json` has no deploy section since commit `2f15ff5` removed it to "unlock dashboard settings" | Container crashes every attempt |
| 3 | Railway health-check path misconfigured in dashboard | **MEDIUM (40%)** | `railway.json` has no `healthcheckPath`; Railway may probe `/` instead of `/health` → gets 404 → marks deployment failed | Health check never passes |
| 4 | Railway using wrong Dockerfile (root `Dockerfile` instead of `backend/worker/Dockerfile`) | **MEDIUM (35%)** | No service-level railway.toml; Railway dashboard must specify custom Dockerfile path; single `railway.json` at root could cause confusion | Runs supervisord+FastAPI instead of rq worker |
| 5 | Docker build slow / timeout due to missing `.dockerignore` | **LOW-MEDIUM (25%)** | No `.dockerignore` exists; `COPY . .` sends entire repo (~500MB+ with `node_modules/`, `.git/`, `.next/`) as build context | Build times out on Railway's 20-min limit |
| 6 | `Procfile` conflict with Dockerfile CMD | **LOW (15%)** | `backend/worker/Procfile` exists; Railway may prefer Procfile over Dockerfile CMD depending on service config | Might override CMD silently |
| 7 | PORT env var conflict between rq worker and health server | **LOW (10%)** | Railway injects `PORT`; health server binds to it; but rq worker also needs a port for internal communication | Unlikely — rq doesn't bind PORT |

> **Note:** Likelihoods compound — the actual failure is likely a combination of #1 + (#2 or #3).

---

## Fix Plan (Ordered by Impact)

### Fix 1: Add Redis connection retry with backoff (addresses RC #1)

**Problem:** `main.py` calls `redis_conn.ping()` exactly once. If Redis is cold-starting (common in Railway), this single attempt fails and the worker exits with `sys.exit(1)`. The container restarts, tries once more, fails again → crash loop.

**Fix:** Replace the single-shot Redis connection with a retry loop (5 attempts, exponential backoff: 2s, 4s, 8s, 16s, 32s = 62s max wait). Start the health server BEFORE attempting Redis, so Railway's health probe gets a response during startup.

```
Startup order change:
  BEFORE: Load env → Connect Redis (FATAL) → Start health → Create queue → Work
  AFTER:  Load env → Start health → Connect Redis (retry 5x) → Create queue → Work
```

**Pre-test:**
```bash
# Simulate: start worker with unreachable Redis, verify it retries
REDIS_URL=redis://localhost:9999/0 timeout 30 python -c "
import sys; sys.path.insert(0, '.')
from backend.worker.main import run_worker
run_worker()
" 2>&1 | grep -E 'retry|attempt|backoff|Failed|starting'
# EXPECT: 5 retry log lines over ~62 seconds, then exit
# CURRENT: immediate sys.exit(1) after first failure
```

**Success criteria:** Worker logs show 5 retry attempts before giving up. Health endpoint responds with `{"status": "degraded"}` during retry window.

**Likelihood this fixes the deployment:** **70%** (if Redis cold-start is the root cause)

---

### Fix 2: Validate Railway dashboard configuration (addresses RC #2, #3, #4)

**Problem:** Commit `2f15ff5` removed the `[deploy]` section from `railway.json`, delegating all deploy settings to the Railway dashboard. If ANY of these settings are wrong, the worker fails:
- `REDIS_URL` not set → defaults to localhost → crash
- Health check path wrong → probes `/` instead of `/health` → 404 → fail
- Dockerfile path wrong → builds main API instead of worker → wrong service

**Fix:** Create a Railway configuration validation script that checks all critical settings. Also add `railway.toml` to the worker directory as a codified backup.

**Pre-test (checklist to verify manually in Railway dashboard):**
```
[ ] Worker service → Settings → Build:
    [ ] Builder = Dockerfile
    [ ] Dockerfile Path = backend/worker/Dockerfile
    [ ] Watch Paths = backend/**, requirements.txt (NOT src/**)

[ ] Worker service → Settings → Deploy:
    [ ] Health Check Path = /health
    [ ] Health Check Timeout = 60s
    [ ] Restart Policy = Always

[ ] Worker service → Variables:
    [ ] REDIS_URL is set (should match Redis add-on's internal URL)
    [ ] PORT is NOT manually set (Railway auto-injects this)
    [ ] SUPABASE_URL is set
    [ ] SUPABASE_SERVICE_ROLE_KEY is set
    [ ] DEFAULT_USER_ID is set
    [ ] ANTHROPIC_API_KEY is set (for skill generation jobs)
```

**Likelihood this fixes the deployment:** **60%** (if config is the root cause, this is a guaranteed fix)

---

### Fix 3: Add `.dockerignore` to eliminate build bloat (addresses RC #5)

**Problem:** No `.dockerignore` exists. `COPY . .` sends the ENTIRE repository as Docker build context, including:
- `node_modules/` (~300MB+ for Next.js)
- `.git/` (~50MB+ for history)
- `.next/` (~50MB+ build cache)
- `__pycache__/`, `.pytest_cache/`, etc.

This slows builds dramatically (may time out on Railway's 20-min build limit) and produces an unnecessarily large image.

**Fix:** Create `.dockerignore` at repository root:
```
node_modules/
.next/
.git/
__pycache__/
*.pyc
.pytest_cache/
.env
.env.*
!.env.example
*.md
docs/
tests/
*.log
.parallel/
```

**Pre-test:**
```bash
# Measure build context size before and after
du -sh --exclude=.git .
# After adding .dockerignore, simulate:
tar --exclude-from=.dockerignore -cf /dev/null . 2>/dev/null
# Should drop from ~500MB to ~50MB
```

**Likelihood this fixes the deployment:** **25%** (only if builds are timing out)

---

### Fix 4: Move health server startup before Redis connection (addresses RC #1)

**Problem:** The health server starts at step 3, but Redis connection is step 2. If Redis is unreachable, the worker `sys.exit(1)` before the health server ever binds. Railway's health probe gets "connection refused" (not even a 503), which is the worst possible signal.

**Fix:** Restructure `run_worker()` so the health server starts FIRST, then Redis connection is attempted with retries. During the retry window the health endpoint returns `{"status": "degraded", "redis_connected": false}` with HTTP 200 (per the existing 45s grace period logic).

**Pre-test:**
```bash
# Start worker with no Redis, verify health endpoint is reachable
REDIS_URL=redis://localhost:9999/0 python -c "
import sys, threading, time; sys.path.insert(0, '.')
# Just start health server, not full worker
from backend.worker.health import start_health_server
start_health_server()
time.sleep(2)
import urllib.request
resp = urllib.request.urlopen('http://localhost:8082/health')
print(f'Status: {resp.status}')
print(resp.read().decode())
" 2>&1
# EXPECT: HTTP 200 with {"status": "degraded"}
```

**Likelihood this fixes the deployment:** **65%** (combined with Fix 1, this is very likely to resolve the issue)

---

### Fix 5: Remove Procfile or ensure it matches Dockerfile CMD (addresses RC #6)

**Problem:** `backend/worker/Procfile` contains `worker: python -m backend.worker.main`. Depending on Railway's service configuration (Nixpacks vs Dockerfile builder), Railway may prefer the Procfile over the Dockerfile CMD. If Railway detects the Procfile but builds with Nixpacks instead of Dockerfile, the build would use a completely different strategy (no system dependencies installed, no health check configured).

**Fix:** Delete `backend/worker/Procfile` — the Dockerfile CMD is the canonical entry point. If needed for local dev, rename to `Procfile.local`.

**Pre-test:**
```bash
# Verify CMD in Dockerfile matches Procfile command
grep "CMD" backend/worker/Dockerfile
cat backend/worker/Procfile
# If they match, Procfile is redundant. If they differ, one is wrong.
```

**Likelihood this fixes the deployment:** **15%** (only if Railway is confused by the Procfile)

---

### Fix 6: Add structured startup logging with stage markers (diagnostic)

**Problem:** When the worker crashes during startup, Railway logs show a Python traceback or exit message, but no structured context about WHICH stage failed or WHY. This makes root-cause analysis slow.

**Fix:** Add stage-by-stage logging with explicit markers:

```python
logger.info("[STAGE 1/6] Loading environment...")
logger.info("[STAGE 2/6] Starting health server...")
logger.info("[STAGE 3/6] Connecting to Redis (attempt %d/%d)...", attempt, max_attempts)
logger.info("[STAGE 4/6] Creating job queue...")
logger.info("[STAGE 5/6] Registering scheduled jobs...")
logger.info("[STAGE 6/6] Starting worker loop...")
```

**Pre-test:** N/A — this is observability, not a fix. But it will make the NEXT failure diagnosable in <30 seconds from Railway logs.

**Likelihood this fixes the deployment:** **0%** (diagnostic only — but critical for future incidents)

---

### Fix 7: Add a smoke-test Docker build to CI (prevention)

**Problem:** Docker build issues are only discovered when Railway builds the image. There's no CI step that validates the worker Dockerfile.

**Fix:** Add a GitHub Actions step that builds the worker Docker image on every PR:
```yaml
- name: Build worker image
  run: docker build -f backend/worker/Dockerfile -t worker-test .

- name: Smoke-test worker startup
  run: |
    docker run --rm -e REDIS_URL=redis://fake:6379/0 worker-test \
      python -c "from backend.worker.main import run_worker; print('imports OK')"
```

**Pre-test:** Run the above commands locally to verify they pass.

**Likelihood this fixes the deployment:** **0%** (prevention only — catches future regressions)

---

## Implementation Order

```
Phase 1: Immediate (fix the deployment NOW)
├── Fix 2: Verify Railway dashboard config (manual, 5 min)
├── Fix 4: Health server before Redis (code, 10 min)
├── Fix 1: Redis retry with backoff (code, 15 min)
└── Fix 6: Structured startup logging (code, 5 min)

Phase 2: Hardening (prevent recurrence)
├── Fix 3: Add .dockerignore (code, 2 min)
├── Fix 5: Remove Procfile (code, 1 min)
└── Fix 7: CI smoke test (code, 15 min)
```

**Phase 1** should be deployed as a single commit. All changes are in `backend/worker/main.py`, `backend/worker/health.py`, and `backend/worker/Dockerfile`. No changes to `lib/` or frontend code.

---

## Pre-Testing Protocol

Before pushing Phase 1, run this validation sequence locally:

### Test A: Import chain validation
```bash
python -c "
import sys; sys.path.insert(0, '.')
# Verify the entire import chain works
from backend.worker.main import run_worker
from backend.worker.health import start_health_server, _collect_health
from backend.worker.jobs import process_wal_entry
from backend.worker.memory_guard import memory_profiled_job
print('All imports OK')
"
```

### Test B: Health server standalone
```bash
python -c "
import sys, time; sys.path.insert(0, '.')
from backend.worker.health import start_health_server
start_health_server(port=9999)
time.sleep(1)
import urllib.request
resp = urllib.request.urlopen('http://localhost:9999/health')
print(f'HTTP {resp.status}')
import json; data = json.loads(resp.read())
print(f'Status: {data[\"status\"]}')
assert data['status'] in ('degraded', 'healthy', 'warning')
print('PASS')
"
```

### Test C: Redis retry simulation
```bash
REDIS_URL=redis://localhost:9999/0 timeout 70 python -c "
import sys; sys.path.insert(0, '.')
from backend.worker.main import run_worker
run_worker()
" 2>&1 | tee /tmp/worker-retry.log
grep -c 'attempt' /tmp/worker-retry.log
# EXPECT: 5 attempts logged
```

### Test D: Dockerfile build
```bash
docker build -f backend/worker/Dockerfile -t sabine-worker-test . 2>&1 | tail -5
echo "Exit code: $?"
# EXPECT: exit 0
```

### Test E: Container startup (no Redis)
```bash
docker run --rm -e REDIS_URL=redis://fake:6379/0 -e PORT=8082 -p 8082:8082 sabine-worker-test &
sleep 5
curl -s http://localhost:8082/health | python3 -m json.tool
docker stop $(docker ps -q --filter ancestor=sabine-worker-test)
# EXPECT: HTTP 200 with {"status": "degraded", "redis_connected": false}
```

---

## Risk Assessment

| Fix | Risk of Regression | Blast Radius | Reversibility |
|-----|-------------------|-------------|---------------|
| Fix 1 (retry) | Low — adds delay, doesn't remove functionality | Worker startup only | Git revert |
| Fix 2 (dashboard) | None — external config | Railway dashboard only | Dashboard revert |
| Fix 3 (.dockerignore) | Low — could exclude needed files | Build only | Delete file |
| Fix 4 (reorder startup) | Low — health server is independent | Worker startup only | Git revert |
| Fix 5 (remove Procfile) | Very low — Dockerfile CMD takes precedence | Build only | Git revert |
| Fix 6 (logging) | None — additive only | Logs only | Git revert |
| Fix 7 (CI test) | None — additive only | CI only | Remove workflow step |

---

## Success Metrics

After implementing all fixes:

1. **Deploy success rate:** 100% on next 5 consecutive deployments
2. **Cold-start time:** Worker health endpoint responds within 10 seconds of container start
3. **Redis recovery:** Worker survives 60-second Redis outage without redeployment
4. **Build time:** Docker build completes in <5 minutes (down from potentially 15+ with no .dockerignore)
5. **Diagnosability:** Any future startup failure identifiable from logs within 30 seconds

---

## Open Questions for Review

1. **Redis add-on configuration:** Is the Railway Redis add-on shared with the main API service? Does it have persistence enabled? Auto-scaling?
2. **Railway restart policy:** What is the current `restartPolicyMaxRetries` for worker-service? (Default is 10 — we should verify)
3. **Memory limits:** Is the Railway worker service configured with a memory limit? The `memory_guard.py` assumes 2048 MB hard limit — does Railway's container limit match?
4. **REDIS_URL value:** Can we confirm the actual REDIS_URL value configured in Railway's dashboard for the worker-service? (Even a masked version like `redis://*****@internal-host:6379/0` would help)
