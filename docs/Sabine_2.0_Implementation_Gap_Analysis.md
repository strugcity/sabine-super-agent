# Sabine 2.0 — Implementation Gap Analysis

**Date:** 2026-02-04
**Source:** Cross-referenced `docs/PRD_Sabine_2.0_Complete.md` against live codebase
**Branch:** `claude/review-session-recap-PB6Si`

---

## What's Already Shipped

| PRD Req | What's Done | Location |
|---|---|---|
| INFRA-006/007/008 | E2B sandbox skill — live and wired | `lib/skills/e2b_sandbox/` |
| SKILL-004/005 | E2B sandbox execution + isolation | `lib/skills/e2b_sandbox/` |
| Audit trail | Connected to all tool executions | `backend/services/audit_logging.py`, wired via `lib/agent/core.py:1412` |
| WAL service | Exists and is called in `/invoke` | `backend/services/wal.py`, called at `lib/agent/server.py:1463` |
| Entity extraction | Runs on ingestion via Haiku | `lib/agent/memory.py` |
| Vector store | pgvector 1536-dim, IVFFlat, cosine distance | `supabase/migrations/`, `lib/agent/memory.py` |

---

## P0 — Foundation (PRD Roadmap: Weeks 1–4)

These are the prerequisite layer. Nothing in P1 or P2 works cleanly without them.

### 1. Salience-Based Memory Management *(MEM-001 → MEM-004)*

- [ ] Migration: add `salience_score`, `last_accessed_at`, `access_count`, `is_archived` to `memories`
- [ ] Implement salience formula `S = ω₁·R + ω₂·F + ω₃·U` with defaults (0.3 / 0.3 / 0.4)
- [ ] Update `retrieval.py` to increment `access_count` and `last_accessed_at` on every read (currently read-only)
- [ ] Nightly archive job: move memories with S < 0.2 (after 30 days) to cold storage (compressed summary + original ID)
- [ ] Cold storage retrieval path with < 500ms target
- [ ] Expose salience weights in `user_config` so they are user-configurable

### 2. Dual-Stream Pipeline — Remaining Gaps *(FAST-001, FAST-003, FAST-004, SLOW-001 → SLOW-005)*

- [ ] Wire `memory.py` `ingest_user_message()` to write to WAL before returning — currently bypasses the WAL entirely (the WAL write in `server.py:1463` is a separate entry, not the memory ingestion path)
- [ ] Parallelize entity extraction and embedding generation in `memory.py` — currently sequential (embed first, then extract)
- [ ] Spin up a dedicated Railway Background Worker process for Slow Path — currently APScheduler runs in-process with FastAPI
- [ ] Provision Railway Redis add-on and wire it as the job queue between FastAPI and the Worker
- [ ] Implement Slow Path consolidation loop: drain WAL → resolve conflicts → extract MAGMA edges → recalculate salience → prune/archive → update entity rankings
- [ ] Checkpointing every 100 WAL entries with resume-on-crash capability
- [ ] Consolidation failure alert (Slack webhook)

### 3. Streaming Acknowledgment *(META-004 → META-006)*

- [ ] Add a background timer in the `/invoke` handler: if LLM has not returned by 8 seconds, emit an interim SMS (e.g., "Let me check my notes…")
- [ ] Make the interim message contextual to the current action
- [ ] Confirm this keeps the Twilio socket alive past its timeout

---

## P1 — Intelligence (PRD Roadmap: Weeks 5–10)

### 4. MAGMA Multi-Graph Architecture *(MAGMA-001 → MAGMA-005)*

- [ ] Migration: create `entity_relationships` table (source/target entity IDs, `graph_type` enum, `relationship_type`, `confidence`, `attributes` JSONB)
- [ ] Relationship extraction service — runs in Slow Path, uses Haiku to pull edges from WAL entries into the four graphs (semantic, temporal, causal, entity)
- [ ] Graph traversal query API — supports direction, edge filters, hop limits; target < 200ms for 3-hop queries
- [ ] Backfill job: retroactively extract relationships from all existing entities/memories
- [ ] Wire graph results into `retrieval.py` context enrichment and `core.py` deep context injection

### 5. Knowledge Conflict Resolution *(MEM-005 → MEM-007)*

- [ ] Conflict detection on Fast Path ingestion: compare new memory against existing ones for semantic contradiction (read-only; flags only, no mutations on Fast Path)
- [ ] Version tagging: when a conflict is detected, store the new memory with a version tag linking it to the conflicting original; make version history queryable
- [ ] Temporary Deviation flag: if new info contradicts ≥ 3 related memories, tag it as a deviation with a 7-day auto-expiry; auto-promote to permanent if the user reconfirms

### 6. Belief Revision System *(BELIEF-001 → BELIEF-007)*

- [ ] Add `confidence` score to the memories schema
- [ ] Implement non-monotonic revision formula: `v' = a · λ_α + v`
- [ ] `λ_α` (open-mindedness) configurable per user and per domain via `user_config`; default 0.5; guardrails 0.1–0.9
- [ ] Martingale score calculation in Slow Path: `M = Σ(predicted_update − actual_update)² / n`
- [ ] Alert if M < 0.1 for 7 consecutive days (triggers self-reflection prompt)
- [ ] Expose M score in the admin dashboard

### 7. Active Inference & Push-Back Protocol *(DECIDE-001 → DECIDE-004, PUSH-001 → PUSH-004)*

- [ ] Action-type classifier: before any tool executes, classify it as irreversible (C_error=1.0), reversible (0.5), or informational (0.2)
- [ ] VoI decision gate: `if (C_error × P_error) > C_int → ask; else → proceed`. P_error estimated from context ambiguity
- [ ] User-configurable `C_int` ("chattiness") threshold in `user_config`
- [ ] Push-back prompt: must cite specific evidence from memory/entities, present ≥ 2 alternatives, and await confirmation
- [ ] Log user overrides; feed them back into `λ_α` calibration
- [ ] Log all VoI calculations to telemetry

---

## P2 — Autonomy (PRD Roadmap: Weeks 11–14)

### 8. Autonomous Skill Acquisition *(SKILL-001 → SKILL-003, SKILL-006 → SKILL-011)*

- [ ] Gap detection heuristics in `core.py`: flag when user edits output > 30%, repeats a command with different wording, tool fails with unknown error, or TTR exceeds 2σ above mean
- [ ] Migration: create `skill_gaps` table
- [ ] Weekly gap analysis digest to user (top 5 prioritized gaps)
- [ ] Research loop: gap → autonomous query of docs / GitHub / StackOverflow → prototype
- [ ] Skill Proposal approval workflow: present proposal JSON (per PRD §11.1 schema) to user; require explicit approval before promotion
- [ ] Hot-reload mechanism: approved skills register in the tool registry without a service restart
- [ ] `skill_versions` table + rollback: every promoted skill is versioned; any version can be disabled and the previous one re-enabled
- [ ] Mount read-only test data into E2B sandbox for validation (SKILL-006)

---

## Cross-Cutting (Required Across All Tiers)

### 9. Training & Reinforcement / Implicit Reward Signal *(TRAIN-001 → TRAIN-004)*

- [ ] Per-turn signal classifier: positive (output used directly, "thank you", logical next step, fewer turns than avg) vs. negative (heavy edits, repeated command, abandonment, frustration)
- [ ] Aggregate signals per task type; weekly pattern analysis
- [ ] Feed signals into prompt / retrieval selection policy (no direct model fine-tuning per PRD)

### 10. Metacognitive Monologue *(META-001 → META-003)*

- [ ] Trigger conditions: estimated > 3 tool calls, ambiguity score > 0.5, or cross-domain info required
- [ ] Monologue must surface specific uncertainties, not just "thinking…"
- [ ] User toggle in `user_config` to disable

### 11. Telemetry & Observability *(OBS-001 → OBS-003)*

- [ ] Emit all 9 PRD-specified metrics: `ttr`, `proactivity.rate`, `clarification.precision`, `salience.distribution`, `martingale.score`, `skill_gap.count`, `push_back.rate`, `latency.fast_path`, `consolidation.duration`
- [ ] Grafana dashboard connected to telemetry backend
- [ ] Trace IDs that link a Fast Path request to its corresponding Slow Path consolidation
- [ ] Alerting on anomalies

### 12. State Management & Snapshots *(STATE-001 → STATE-007)*

- [ ] Snapshot the full memory / entity / relationship state on every Slow Path completion
- [ ] 30-day snapshot retention (configurable)
- [ ] `/admin/rollback/{snapshot_id}` endpoint
- [ ] Skill versioning via `skill_versions` table (ties into task 8)

---

## Summary

| Tier | Uncompleted Workstreams | Sub-tasks | PRD Req IDs |
|---|---|---|---|
| P0 Foundation | 3 | ~15 | MEM-001–004, FAST-001/003/004, SLOW-001–005, META-004–006 |
| P1 Intelligence | 4 | ~18 | MAGMA-001–005, MEM-005–007, BELIEF-001–007, DECIDE-001–004, PUSH-001–004 |
| P2 Autonomy | 1 | ~10 | SKILL-001–003, 006–011 |
| Cross-cutting | 4 | ~12 | TRAIN-001–004, META-001–003, OBS-001–003, STATE-001–007 |

### Notable Partial-Credit Items

- **WAL service** is built and wired into `/invoke`, but `memory.py` `ingest_user_message()` does not write through it — the memory ingestion path is a separate code path.
- **E2B sandbox** is live, but has no gap-detection, research-loop, or promotion-ceremony workflow wrapped around it.
- **Entity extraction** runs on every ingestion, but sequentially after embedding — not the parallel path the PRD assumes.
