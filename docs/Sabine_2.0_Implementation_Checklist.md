# Sabine 2.0: Implementation Checklist

**Purpose:** Tracking document for PM and Tech Lead
**Last Updated:** January 30, 2026

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
| [ ] ADR-001: Graph Storage | pg_graphql vs. Neo4j | Tech Lead | |
| [ ] ADR-002: Job Queue | Redis vs. in-process APScheduler | Tech Lead | |
| [ ] ADR-003: Sandbox Provider | E2B vs. Modal | Tech Lead | |
| [ ] ADR-004: Cold Storage Format | Compressed summary vs. full archive | Tech Lead | |

---

## Phase 1: Foundation (Weeks 1-4)

### Week 1: Infrastructure Setup

#### Schema Migrations
- [ ] **MEM-001**: Add `salience_score` column to memories table
- [ ] **MEM-001**: Add `last_accessed_at` column to memories table
- [ ] **MEM-001**: Add `access_count` column to memories table
- [ ] **MEM-001**: Add `is_archived` column to memories table
- [ ] Create `write_ahead_log` table for WAL
- [ ] Create index on WAL for processing order

#### Redis Setup
- [ ] **INFRA-001**: Provision Railway Redis add-on
- [ ] Configure connection string in environment
- [ ] Test connectivity from FastAPI server

### Week 2: Background Worker

#### Worker Service
- [ ] **INFRA-002**: Create new Railway service for worker
- [ ] Set up worker Dockerfile/Procfile
- [ ] Implement health check endpoint `/worker/health`
- [ ] **INFRA-004**: Configure health monitoring

#### Queue Integration
- [ ] Select queue library (rq vs. dramatiq)
- [ ] Implement job producer in FastAPI
- [ ] Implement job consumer in worker
- [ ] Test queue roundtrip

### Week 3: Dual-Stream Pipeline

#### Fast Path (REQ: FAST-001 through FAST-004)
- [ ] **FAST-001**: Modify `ingest_user_message()` to write to WAL
- [ ] **FAST-002**: Ensure no graph mutations on hot path
- [ ] **FAST-003**: Parallelize entity extraction and embedding
- [ ] **FAST-004**: Implement read-only conflict detection

#### Slow Path (REQ: SLOW-001 through SLOW-005)
- [ ] **SLOW-001**: WAL processing job in worker
- [ ] **SLOW-002**: Implement checkpointing (every 100 entries)
- [ ] **SLOW-003**: Wire Haiku for causal edge extraction
- [ ] **SLOW-004**: Slack/SMS alert on failure
- [ ] **SLOW-005**: Memory profiling, enforce 2GB limit

### Week 4: Salience & Streaming

#### Salience Calculation (REQ: MEM-001 through MEM-004)
- [ ] **MEM-001**: Implement salience formula in Slow Path
- [ ] **MEM-002**: Archive job for S < 0.2 memories
- [ ] **MEM-003**: Cold storage table + retrieval API
- [ ] **MEM-004**: Settings API for weight configuration

#### Streaming Acknowledgment (REQ: META-004 through META-006)
- [ ] **META-004**: Timer thread in `/invoke` handler
- [ ] **META-005**: Verify SMS socket behavior
- [ ] **META-006**: Contextual acknowledgment templates

### Phase 1 Exit Criteria
- [ ] Worker processes WAL entries independently
- [ ] Salience scores calculated on nightly run
- [ ] Streaming ack prevents SMS timeout (manual test)
- [ ] No data loss on worker crash (chaos test)

---

## Phase 2: Intelligence (Weeks 5-10)

### Weeks 5-6: MAGMA Graph Architecture

#### Schema (REQ: MAGMA-001 through MAGMA-005)
- [ ] Create `entity_relationships` table
- [ ] Add indexes for source, target, type
- [ ] Implement relationship type taxonomy (see PRD 11.2)

#### Relationship Extraction
- [ ] Design extraction prompt for Haiku
- [ ] Implement extraction service in Slow Path
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
