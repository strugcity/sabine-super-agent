# Sabine 2.0: Implementation Checklist

**Purpose:** Tracking document for PM and Tech Lead
**Last Updated:** February 14, 2026

---

## How to Use This Document

- [ ] = Not started
- [~] = In progress
- [x] = Complete
- [!] = Blocked

Each item includes the requirement ID from the PRD for traceability.

---

## Phase 0: Architecture Decisions (Week 0)

### ADRs Required

| ADR | Decision | Owner | Status |
|-----|----------|-------|--------|
| [x] ADR-001: Graph Storage | **pg_graphql** (Postgres recursive CTEs) | Tech Lead | ✅ Accepted 2026-02-13 |
| [x] ADR-002: Job Queue | **Redis + rq** (separate Railway worker) | Tech Lead | ✅ Accepted 2026-02-13 |
| [x] ADR-003: Sandbox Provider | **E2B** (existing integration) | Tech Lead | ✅ Accepted 2026-02-13 |
| [x] ADR-004: Cold Storage Format | **Compressed Summary** (Haiku summaries + S3 backup) | Tech Lead | ✅ Accepted 2026-02-13 |

---

## Phase 1: Foundation (Weeks 1-4)

### Week 1: Infrastructure Setup

#### Schema Migrations
- [x] **MEM-001**: Add `salience_score` column to memories table — `20260213_phase1_schema.sql`
- [x] **MEM-001**: Add `last_accessed_at` column to memories table — `20260213_phase1_schema.sql`
- [x] **MEM-001**: Add `access_count` column to memories table — `20260213_phase1_schema.sql`
- [x] **MEM-001**: Add `is_archived` column to memories table — `20260213_phase1_schema.sql`
- [x] Create `write_ahead_log` table for WAL — `20260213_phase1_schema.sql`
- [x] Create index on WAL for processing order — `20260213_phase1_schema.sql`

#### Redis Setup
- [x] **INFRA-001**: Provision Railway Redis add-on — deployed, Online
- [x] Configure connection string in environment — `backend/services/redis_client.py`
- [x] Test connectivity from FastAPI server — health check in `backend/worker/health.py`

### Week 2: Background Worker

#### Worker Service
- [x] **INFRA-002**: Create new Railway service for worker — `worker-service`, Online, same Redis
- [x] Set up worker Dockerfile/Procfile — `backend/worker/Dockerfile`, `backend/worker/Procfile`
- [x] Implement health check endpoint `/worker/health` — `backend/worker/health.py`
- [x] **INFRA-004**: Configure health monitoring — health server on port 8082

#### Queue Integration
- [x] Select queue library (rq vs. dramatiq) — **rq** (ADR-002)
- [x] Implement job producer in FastAPI — `backend/services/queue.py`
- [x] Implement job consumer in worker — `backend/worker/jobs.py`
- [x] Test queue roundtrip — unit tests passing

### Week 3: Dual-Stream Pipeline

#### Fast Path (REQ: FAST-001 through FAST-004)
- [x] **FAST-001**: Modify `ingest_user_message()` to write to WAL — `backend/services/fast_path.py`
- [x] **FAST-002**: Ensure no graph mutations on hot path — WAL decouples writes
- [x] **FAST-003**: Parallelize entity extraction and embedding — `asyncio.gather()` in fast_path
- [x] **FAST-004**: Implement read-only conflict detection — `backend/services/fast_path.py`

#### Slow Path (REQ: SLOW-001 through SLOW-005)
- [x] **SLOW-001**: WAL processing job in worker — `backend/worker/slow_path.py`
- [x] **SLOW-002**: Implement checkpointing (every 100 entries) — `backend/services/checkpoint.py`
- [x] **SLOW-003**: Wire Haiku for causal edge extraction — Claude Haiku in `slow_path.py`
- [x] **SLOW-004**: Slack/SMS alert on failure — `backend/worker/alerts.py` (httpx webhook)
- [ ] **SLOW-005**: Memory profiling, enforce 2GB limit

### Week 4: Salience & Streaming

#### Salience Calculation (REQ: MEM-001 through MEM-004)
- [x] **MEM-001**: Implement salience formula in Slow Path — `backend/services/salience.py` (keyword emotional weight + graph centrality)
- [x] **MEM-002**: Archive job for S < 0.2 memories — `backend/worker/salience_job.py` (flips `is_archived`; full cold-storage move Phase 2)
- [x] **MEM-003**: Cold storage table + retrieval API — `lib/agent/routers/archive.py` (list/get/restore endpoints)
- [ ] **MEM-004**: Settings API for weight configuration

#### Streaming Acknowledgment (REQ: META-004 through META-006)
- [x] **META-004**: Timer thread in `/invoke` handler — `AcknowledgmentManager` + real Twilio SMS
- [~] **META-005**: Verify SMS socket behavior — webhook→/invoke→TwiML flow verified via curl simulation; ack timer needs Twilio creds on Railway + real carrier test after campaign approval
- [x] **META-006**: Contextual acknowledgment templates — topic-aware templates in `streaming_ack.py`

#### Nightly Scheduling
- [x] Wire `rq` scheduler for nightly salience recalc — `backend/worker/main.py` (`with_scheduler=True`)
- [x] Wire `rq` scheduler for nightly archive job — `_register_scheduled_jobs()` in worker

### Phase 1 Exit Criteria
- [x] Worker processes WAL entries independently — rq worker, separate Dockerfile
- [x] Salience scores calculated on nightly run — scheduler wired
- [~] Streaming ack prevents SMS timeout (manual test) — code complete, needs carrier test
- [ ] No data loss on worker crash (chaos test)

---

## Phase 2: Intelligence (Weeks 5-10)

### Weeks 5-6: MAGMA Graph Architecture

#### Schema (REQ: MAGMA-001 through MAGMA-005)
- [x] Create `entity_relationships` table — already exists in Supabase schema
- [x] Add indexes for source, target, type — included in schema
- [ ] Implement relationship type taxonomy (see PRD 11.2)

#### Relationship Extraction
- [x] Design extraction prompt for Haiku — `backend/worker/slow_path.py`
- [x] Implement extraction service in Slow Path — Claude Haiku with 10s timeout + fallback
- [ ] Test accuracy on sample memories (target >80%)

#### Graph Queries
- [ ] **MAGMA-005**: Cross-graph traversal API
- [ ] Benchmark: <200ms for 3-hop traversals
- [ ] Implement `causal_trace()` function
- [ ] Implement `entity_network()` function

### Week 7: Backfill & Integration

- [ ] Backfill job for existing entities → relationships
- [ ] Wire MAGMA queries into `retrieval.py`
- [ ] Update deep context injection in `core.py`
- [ ] Dashboard visualization (P2, optional)

### Week 8: Belief Revision

#### Schema Updates
- [ ] Add `confidence` column to memories
- [ ] Add `belief_version` column for tracking

#### Belief Logic (REQ: BELIEF-004 through BELIEF-007)
- [ ] **BELIEF-004**: `λ_α` in user_config
- [ ] **BELIEF-005**: Default λ_α = 0.5
- [ ] **BELIEF-006**: Per-domain override support
- [ ] **BELIEF-007**: Push-back trigger on high-confidence conflict

#### Conflict Resolution (REQ: MEM-005 through MEM-007)
- [ ] **MEM-005**: Conflict detection in Fast Path
- [ ] **MEM-006**: Version tagging implementation
- [ ] **MEM-007**: Temporary Deviation flag with expiry

### Week 9: Active Inference & Push-Back

#### VoI Calculation (REQ: DECIDE-001 through DECIDE-004)
- [ ] **DECIDE-001**: Action type classifier
- [ ] **DECIDE-002**: Ambiguity score calculation
- [ ] **DECIDE-003**: User-configurable C_int
- [ ] **DECIDE-004**: VoI logging to telemetry

#### Push-Back Protocol (REQ: PUSH-001 through PUSH-004)
- [ ] **PUSH-001**: Evidence citation in push-back
- [ ] **PUSH-002**: Alternative generation (min 2 options)
- [ ] **PUSH-003**: Override logging for learning
- [ ] **PUSH-004**: Push-back rate tracking

### Week 10: Martingale & Dashboard

#### Martingale Monitoring (REQ: BELIEF-001 through BELIEF-003)
- [ ] **BELIEF-001**: Daily M score calculation
- [ ] **BELIEF-002**: Alert on M < 0.1 for 7 days
- [ ] **BELIEF-003**: Admin dashboard integration

#### Dashboard Updates
- [ ] Salience distribution chart
- [ ] Martingale trend chart
- [ ] Push-back rate metrics
- [ ] Conflict resolution log

### Phase 2 Exit Criteria
- [ ] Causal query: "Why did X fail?" returns valid trace
- [ ] Push-back triggers on conflicting high-stakes requests
- [ ] λ_α configurable in user settings
- [ ] Martingale alerts functional

---

## Phase 3: Autonomy (Weeks 11-14)

### Week 11: Gap Detection

#### Gap Triggers (REQ: SKILL-001 through SKILL-003)
- [ ] **SKILL-001**: Track edit percentage per output
- [ ] **SKILL-001**: Track command repetition patterns
- [ ] **SKILL-002**: Weekly gap analysis job
- [ ] **SKILL-003**: Link gaps to capability taxonomy

#### Schema
- [ ] Create `skill_gaps` table
- [ ] Create `skill_proposals` table
- [ ] Create `skill_versions` table

### Week 12: E2B Sandbox

#### Integration (REQ: INFRA-006 through INFRA-009)
- [ ] **INFRA-006**: E2B SDK integration
- [ ] **INFRA-007**: 30-second timeout enforcement
- [ ] **INFRA-008**: Network isolation verification
- [ ] **INFRA-009**: Cost tracking setup

#### Execution Wrapper
- [ ] `/skill/prototype` endpoint
- [ ] Test data folder mounting
- [ ] Output capture (stdout, stderr, exit code)

### Week 13: Research & Proposal

#### Research Agent
- [ ] Perplexity or RAG integration for documentation lookup
- [ ] GitHub/Stack Overflow query capability
- [ ] Research result formatting

#### Skill Proposal (REQ: SKILL-007, SKILL-008)
- [ ] **SKILL-007**: Proposal JSON schema validation
- [ ] **SKILL-008**: Approval workflow UI
- [ ] ROI estimation logic

### Week 14: Hot-Reload & Inventory

#### Hot-Reload (REQ: SKILL-009 through SKILL-011)
- [ ] **SKILL-009**: Dynamic tool registry refresh
- [ ] **SKILL-010**: Audit log for approvals
- [ ] **SKILL-011**: Skill disable/rollback capability

#### Skill Dashboard
- [ ] Skill inventory view
- [ ] Gap frequency visualization
- [ ] Proposal queue management

### Phase 3 Exit Criteria
- [ ] Gap detected from conversation pattern (demo)
- [ ] Skill tested in E2B sandbox
- [ ] Approved skill available without restart
- [ ] Full loop: gap → research → test → propose → approve

---

## Phase 4: Polish (Weeks 15-16)

### Week 15: Observability

#### Telemetry (REQ: OBS-001 through OBS-003)
- [ ] **OBS-001**: Grafana dashboard with all metrics
- [ ] **OBS-002**: PagerDuty alerting rules
- [ ] **OBS-003**: Trace ID correlation (Fast → Slow Path)

#### Metrics Implementation
- [ ] `sabine.ttr` histogram
- [ ] `sabine.proactivity.rate` gauge
- [ ] `sabine.clarification.precision` gauge
- [ ] `sabine.salience.distribution` histogram
- [ ] `sabine.martingale.score` gauge
- [ ] `sabine.skill_gap.count` counter
- [ ] `sabine.push_back.rate` gauge
- [ ] `sabine.latency.fast_path` histogram
- [ ] `sabine.consolidation.duration` histogram

### Week 16: Documentation & Testing

#### Documentation
- [ ] Architecture diagram (final)
- [ ] Runbook: Slow Path failures
- [ ] Runbook: Skill security incidents
- [ ] Runbook: Rollback procedures
- [ ] API documentation updates

#### Load Testing
- [ ] P95 latency < 12s under load
- [ ] Consolidation completes for 1000 memories < 30min
- [ ] Graph queries < 200ms at 100k relationships

### Phase 4 Exit Criteria
- [ ] All KPIs visible in dashboard
- [ ] Runbooks reviewed by on-call
- [ ] Load test results documented
- [ ] Sign-off from stakeholders

---

## Guardrail Verification

| Guardrail | Verification Method | Status |
|-----------|---------------------|--------|
| HITL-001: Skill approval required | Manual test: approve/reject flow | [ ] |
| HITL-002: Memory overwrite confirmation | Manual test: conflict scenario | [ ] |
| PRIVACY-001: Data encrypted at rest | Supabase audit | [ ] |
| PRIVACY-002: λ_α stays local | API audit: no external exposure | [ ] |
| STABILITY-001: Graph consistency | Cycle detection test | [ ] |
| STABILITY-002: No duplicate edges | Constraint test | [ ] |
| ROLLBACK-001: 30-day restore | Snapshot restore test | [ ] |

---

## Risk Monitoring

| Risk | Indicator | Threshold | Current | Status |
|------|-----------|-----------|---------|--------|
| R-001: Slow Path OOM | Memory usage | > 1.5GB | - | [ ] |
| R-002: E2B cold start | Spin-up time | > 5s | - | [ ] |
| R-003: Graph explosion | Edges per node | > 50 | - | [ ] |
| R-004: User confusion | Push-back rejection rate | > 50% | - | [ ] |
| R-005: Extraction accuracy | Relationship accuracy | < 80% | - | [ ] |

---

## Known Issues / Tech Debt

| ID | Issue | Severity | Details | Status |
|----|-------|----------|---------|--------|
| DEBT-001 | **Google OAuth refresh token expiry (`invalid_grant`)** | **High** | **Root cause found:** 3 different OAuth client IDs were hardcoded across `reauthorize_google.py`, `exchange_code.py`, and `trigger_oauth.py`. Tokens generated with one client ID fail with `invalid_grant` when refreshed with a different client ID on Railway. **Fixed (2026-02-14):** (a) `reauthorize_google.py` now reads `GOOGLE_CLIENT_ID` from `.env` — no more hardcoded client IDs, (b) `TokenExpiredError` + `invalid_grant` detection in `get_access_token()`, (c) `GET /gmail/token-health` proactive health-check endpoint, (d) email poller back-off after 3 consecutive failures + Slack alert. **After re-auth:** re-run `reauthorize_google.py` for both user + agent accounts using the `.env` client ID, then update Railway env vars. | [~] Needs re-auth |
| DEBT-002 | **Duplicate reminders in database** | Medium | 9 copies of "Send weekly baseball YouTube video" reminder all firing at once. Needs dedup logic or a unique constraint on (user_id, title, recurrence_pattern). | [ ] Not started |
| DEBT-003 | **Entity extraction returns prose instead of JSON** | Low | Claude Haiku sometimes returns freeform text instead of JSON for low-signal messages (e.g., "what's the weather?"). The `OutputParserException` is caught gracefully but is noisy. Consider adding a retry with `response_format` or a fallback empty-JSON path. | [ ] Not started |
| DEBT-004 | **SMS reminder delivery: no phone number configured** | Medium | All SMS reminders fail with "No phone number configured for SMS notification". The `user_config` table has 0 config settings for the test user — phone number needs to be stored there or pulled from `user_identities`. | [ ] Not started |

---

## Sign-Off

| Milestone | Date | Signed By |
|-----------|------|-----------|
| Phase 1 Complete | | |
| Phase 2 Complete | | |
| Phase 3 Complete | | |
| Phase 4 Complete | | |
| Production Release | | |

---

*This checklist maps to PRD_Sabine_2.0_Complete.md*
