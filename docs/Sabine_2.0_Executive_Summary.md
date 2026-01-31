# Sabine 2.0: Executive Summary

## The "Right-Hand" Evolution

**Document Type:** Executive Summary for Stakeholders
**Date:** January 30, 2026

---

## One-Liner

Transform Sabine from a reactive assistant into a proactive strategic partner who learns, remembers with nuance, and knows when to push back.

---

## The Problem

Current Sabine is functionally capable but cognitively limited:

| Limitation | Impact |
|------------|--------|
| **Flat Memory** | Can't answer "why did X fail?" or "who works on Y?" |
| **No Conflict Resolution** | Old info and new info coexist confusingly |
| **Static Skills** | Can't learn new capabilities without code deployment |
| **Yes-Man Syndrome** | Never challenges user requests, even bad ones |
| **Unbounded Context** | Dumps everything into LLM, wasting tokens and capacity |

---

## The Solution: Four Pillars

### 1. MAGMA Memory Architecture
**From:** Implicit relationships through shared memories
**To:** Explicit graphs for Semantic, Temporal, Causal, and Entity relationships

*Example:* "Why did the PriceSpider deal stall?" → Trace causal graph back 5 hops to root cause.

### 2. Adaptive Belief System
**From:** Append-only memory
**To:** Non-monotonic belief revision with tunable "open-mindedness"

*Example:* User says "I'm using Python 3.12 now." Sabine flags this against 15 memories mentioning Python 3.10 and asks for confirmation.

### 3. Autonomous Skill Acquisition
**From:** Static tool registry
**To:** Gap detection → Sandbox testing → User-approved skill promotion

*Example:* Sabine notices she fails at .msg file parsing 5 times. She researches a solution, tests it in an isolated sandbox, and presents a "Skill Proposal" for approval.

### 4. Strategic Push-Back
**From:** Blind compliance
**To:** Value-of-Information decision logic with evidence-based push-back

*Example:* "Cancel all meetings tomorrow." Sabine responds: "Your board presentation is marked critical. Should I cancel that too, or just the others?"

---

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────┐
│                        USER                                 │
│                   (SMS / Web / Voice)                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     FAST PATH (10-12s)                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────────────┐│
│  │ Parse   │→ │Retrieve │→ │   LLM   │→ │ Respond + Queue ││
│  │ Intent  │  │ Context │  │ Reason  │  │    to WAL       ││
│  └─────────┘  └─────────┘  └─────────┘  └─────────────────┘│
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ (Async)
┌─────────────────────────────────────────────────────────────┐
│                    SLOW PATH (2:00 AM)                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────────────┐│
│  │ Process │→ │ Extract │→ │ Update  │→ │   Prune &       ││
│  │   WAL   │  │ Graphs  │  │Salience │  │   Archive       ││
│  └─────────┘  └─────────┘  └─────────┘  └─────────────────┘│
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    STORAGE LAYER                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  Vector DB  │  │  Entity DB  │  │  Relationship Graph │ │
│  │  (pgvector) │  │  (Supabase) │  │  (MAGMA 4-layer)    │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Success Metrics

| Metric | Current | Target | Why It Matters |
|--------|---------|--------|----------------|
| **Turn-to-Resolution** | ~4 turns | < 2.5 turns | Efficiency |
| **Proactive Suggestions Accepted** | N/A | > 70% | Trust |
| **Push-back Acceptance** | N/A | > 60% | Strategic value |
| **Skills Learned per Month** | 0 | > 2 | Autonomy |

---

## Implementation Roadmap

| Phase | Duration | Focus | Exit Criteria |
|-------|----------|-------|---------------|
| **Foundation** | Weeks 1-4 | Dual-stream pipeline, salience memory | Worker processes independently |
| **Intelligence** | Weeks 5-10 | MAGMA graphs, belief revision, push-back | Causal queries work |
| **Autonomy** | Weeks 11-14 | Skill acquisition, sandbox testing | Hot-reload without restart |
| **Polish** | Weeks 15-16 | Telemetry, documentation, load testing | KPIs tracked, runbook complete |

---

## Key Technical Decisions Needed

| Decision | Options | Recommendation | Blocker For |
|----------|---------|----------------|-------------|
| Graph Storage | pg_graphql vs. Neo4j | pg_graphql (simplicity) | MAGMA implementation |
| Job Queue | Redis vs. in-process | Redis (isolation) | Slow Path worker |
| Sandbox Provider | E2B vs. Modal | E2B (better SDK) | Skill acquisition |

---

## Risk Summary

| Risk | Mitigation |
|------|------------|
| **Slow Path OOM** | Dedicated worker, 2GB limit, checkpointing |
| **User Confusion with Push-back** | Configurable "chattiness", disable option |
| **Skill Security** | Sandbox isolation, no network, code review |

---

## Investment Ask

| Resource | Quantity | Purpose |
|----------|----------|---------|
| Engineering | 1 senior backend | Full-time for 16 weeks |
| Infrastructure | Railway Background Worker | Slow Path isolation |
| External Services | E2B sandbox | Skill testing |
| External Services | Redis add-on | Job queue |

---

## Bottom Line

Sabine 2.0 transforms from a tool that *answers questions* to a partner that *thinks alongside you*. The investment is substantial (16 weeks), but the payoff is a system that gets smarter with every interaction—compounding intelligence rather than static capability.

**Next Step:** Technical Lead spike on MAGMA graph storage decision (Week 1).

---

*Full PRD available at: `docs/PRD_Sabine_2.0_Complete.md`*
