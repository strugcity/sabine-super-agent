# Product Requirements Document: Sabine 2.0

## "The Right-Hand Evolution"

**Document Version:** 2.0.0
**Last Updated:** January 30, 2026
**Status:** Draft for Technical Review
**Authors:** Product Management + CTO Review

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Vision & Strategic Objectives](#2-vision--strategic-objectives)
3. [Current Architecture Baseline](#3-current-architecture-baseline)
4. [Functional Requirements](#4-functional-requirements)
   - 4.1 [Memory & Knowledge Management](#41-memory--knowledge-management)
   - 4.2 [Multi-Graph Memory Architecture (MAGMA)](#42-multi-graph-memory-architecture-magma)
   - 4.3 [Dual-Stream Ingestion Pipeline](#43-dual-stream-ingestion-pipeline)
   - 4.4 [Belief Revision & Epistemic Integrity](#44-belief-revision--epistemic-integrity)
   - 4.5 [Decision-Making & Learning](#45-decision-making--learning)
   - 4.6 [Autonomous Skill Acquisition](#46-autonomous-skill-acquisition)
   - 4.7 [Training & Reinforcement](#47-training--reinforcement)
   - 4.8 [Interaction & Articulation](#48-interaction--articulation)
5. [Technical Requirements](#5-technical-requirements)
   - 5.1 [Infrastructure & Deployment](#51-infrastructure--deployment)
   - 5.2 [Latency & Performance Budgets](#52-latency--performance-budgets)
   - 5.3 [State Management & Versioning](#53-state-management--versioning)
   - 5.4 [Observability & Telemetry](#54-observability--telemetry)
6. [Technical Guardrails](#6-technical-guardrails)
7. [Success Metrics (KPIs)](#7-success-metrics-kpis)
8. [Component Estimation Framework](#8-component-estimation-framework)
9. [Risk Register](#9-risk-register)
10. [Implementation Roadmap](#10-implementation-roadmap)
11. [Appendices](#11-appendices)

---

## 1. Executive Summary

### Purpose

This PRD defines the evolution of Sabine from a reactive assistant to a proactive strategic partner. The transformation is grounded in neuro-computational research that models human cognition—specifically attention management, hierarchical memory systems, belief revision, and metacognitive learning.

### Core Transformation

| Aspect | Sabine 1.0 (Current) | Sabine 2.0 (Target) |
|--------|---------------------|---------------------|
| Memory | Implicit graph via memory links | Explicit MAGMA multi-graph |
| Learning | Static tool registry | Autonomous skill acquisition |
| Decision Logic | Single-path optimization | Multi-criteria analysis (MCDA) |
| Belief Handling | Append-only | Non-monotonic revision with λ_α tuning |
| User Interaction | Reactive responses | Proactive push-back with VoI |
| Context Management | Unbounded retrieval | Salience-weighted token budgeting |

### Literature-Supported Principles

Based on Active Inference (Friston et al.) and Hierarchical Memory Systems (HiMeS):

1. **Memory-Index Model**: Humans store predictive models, not raw data. Sabine will use a Hippocampal Buffer (episodic, high-fidelity recent context) and Neocortical Graph (abstracted, long-term semantic knowledge).

2. **Minimizing Variational Free Energy**: Sabine's core drive is to minimize "surprise." Ambiguous requests trigger proactive clarification (Surprise > Threshold) rather than guessing.

3. **Metacognition & Skill Building**: By analyzing Task-Turn Efficiency, Sabine identifies Capability Gaps and initiates Self-Training Loops.

---

## 2. Vision & Strategic Objectives

### Vision Statement

To transition Sabine from a reactive assistant to a proactive partner who anticipates needs, manages her own knowledge base, and self-corrects based on a sophisticated understanding of the user's long-term goals.

### Strategic Objectives

| Objective | Definition | Target Metric |
|-----------|------------|---------------|
| **Autonomy** | Sabine identifies when she lacks information or skills and fixes it without being told | Skill Gap Detection Rate > 85% |
| **Alignment** | She develops a "Theory of Mind" regarding user preferences, enabling strategic push-back | Push-back Acceptance Rate > 60% |
| **Efficiency** | Reduce User-to-Agent friction through proactive outcome prediction | TTR Reduction by 40% |
| **Intelligence Compounding** | Each interaction makes her more capable | Monthly Skill Acquisition Rate > 2 |

---

## 3. Current Architecture Baseline

### Existing Components (Reference: `/lib/agent/`)

| Component | Current State | Location |
|-----------|---------------|----------|
| Vector DB | Supabase pgvector (1536 dims, IVFFlat) | `/lib/agent/memory.py` |
| Embedding Model | OpenAI text-embedding-3-small | `/lib/agent/memory.py` |
| Entity Extraction | Claude 3 Haiku with PydanticOutputParser | `/lib/agent/memory.py` |
| RAG Pipeline | Vector + keyword entity fuzzy match | `/lib/agent/retrieval.py` |
| Scheduler | APScheduler (morning briefing only) | `/lib/agent/scheduler.py` |
| Tool Registry | Unified local skills + MCP tools | `/lib/agent/registry.py` |
| Agent Core | LangGraph ReAct with deep context injection | `/lib/agent/core.py` |
| Prompt Caching | Anthropic API cache (static context ≥ 2048 tokens) | `/lib/agent/core.py` |

### Current Limitations Addressed by This PRD

1. **Implicit Graph Only**: Entities linked through memories, not explicit relationships
2. **No Relationship Types**: Cannot query "all documents managed by Person X"
3. **Append-Only Memory**: No conflict resolution or belief revision
4. **No Skill Acquisition**: Tool registry is static
5. **Single-User Scheduler**: Hardcoded `DEFAULT_USER_ID`
6. **No Token Budgeting**: Context window treated as unlimited

---

## 4. Functional Requirements

### 4.1 Memory & Knowledge Management

#### 4.1.1 Salience-Based Memory System

Sabine shall implement a Salience Scoring Algorithm to determine information retention priority.

**Formula:**
```
S = ω₁ · R + ω₂ · F + ω₃ · U
```

Where:
- `R` (Recency): Normalized time since last access (0-1 scale, exponential decay)
- `F` (Frequency): Log-normalized access count
- `U` (Utility): Positive reinforcement signal from user interactions

**Default Weights:** ω₁ = 0.3, ω₂ = 0.3, ω₃ = 0.4

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| MEM-001 | Calculate salience score on every memory access | Score updated within Slow Path cycle |
| MEM-002 | Archive memories where S < 0.2 after 30 days | Archived memories moved to cold storage |
| MEM-003 | Cold storage format: compressed summary + original ID reference | Retrieval latency < 500ms for cold memories |
| MEM-004 | User-configurable salience weights via settings | Weights persisted in `user_config` table |

**Schema Addition:**
```sql
ALTER TABLE memories ADD COLUMN salience_score FLOAT DEFAULT 0.5;
ALTER TABLE memories ADD COLUMN last_accessed_at TIMESTAMP DEFAULT NOW();
ALTER TABLE memories ADD COLUMN access_count INTEGER DEFAULT 0;
ALTER TABLE memories ADD COLUMN is_archived BOOLEAN DEFAULT FALSE;
```

#### 4.1.2 Knowledge Conflict Resolution

When new information (I_new) conflicts with existing memory (M_ext):

**Decision Matrix:**

| Scenario | Condition | Action |
|----------|-----------|--------|
| High-Confidence Override | Confidence(I_new) > Confidence(M_ext) + 0.2 | Append with version tag, prompt for confirmation |
| Marginal Update | Confidence difference < 0.2 | Flag for Slow Path reconciliation |
| Outlier Detection | I_new contradicts >3 related memories | Flag as "Temporary Deviation" |
| Pattern Violation | I_new contradicts established rule | Trigger push-back protocol |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| MEM-005 | Conflict detection on Fast Path ingestion | Conflicts flagged within 500ms |
| MEM-006 | Version tagging for conflicting memories | Version history queryable via API |
| MEM-007 | Temporary Deviation flag with 7-day expiry | Auto-promotion to permanent if reconfirmed |

---

### 4.2 Multi-Graph Memory Architecture (MAGMA)

#### 4.2.1 Graph Layer Specifications

Sabine shall maintain four orthogonal relational graphs for disentangled memory representation.

**Graph Definitions:**

| Graph | Purpose | Node Type | Edge Type | Query Pattern |
|-------|---------|-----------|-----------|---------------|
| **Semantic** | Conceptual meaning & categories | Entities | `is_type_of`, `similar_to` | Pattern matching across domains |
| **Temporal** | Chronological continuity | Events/Memories | `precedes`, `concurrent_with` | Timeline reconstruction |
| **Causal** | Cause-effect relationships | Actions/Outcomes | `caused_by`, `resulted_in` | Failure analysis, learning |
| **Entity** | Stakeholder relationships | People/Orgs/Tools | `works_with`, `manages`, `owns` | Ecosystem mapping |

**Schema Addition:**
```sql
CREATE TABLE entity_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    source_entity_id UUID NOT NULL REFERENCES entities(id),
    target_entity_id UUID NOT NULL REFERENCES entities(id),
    relationship_type VARCHAR(50) NOT NULL,
    graph_type VARCHAR(20) NOT NULL CHECK (graph_type IN ('semantic', 'temporal', 'causal', 'entity')),
    attributes JSONB DEFAULT '{}',
    confidence FLOAT DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_relationships_source ON entity_relationships(source_entity_id);
CREATE INDEX idx_relationships_target ON entity_relationships(target_entity_id);
CREATE INDEX idx_relationships_type ON entity_relationships(graph_type, relationship_type);
```

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| MAGMA-001 | Semantic graph populated from entity type hierarchies | 100% entity coverage |
| MAGMA-002 | Temporal graph maintains chronological edges | Topological sort produces valid timeline |
| MAGMA-003 | Causal graph extracted from action-outcome pairs | Failure traces ≤ 5 hops to root cause |
| MAGMA-004 | Entity graph captures explicit relationship mentions | Relationship extraction accuracy > 80% |
| MAGMA-005 | Cross-graph traversal queries supported | Query latency < 200ms for 3-hop traversals |

#### 4.2.2 Graph Query Patterns

**New Query Types Enabled:**

```python
# Causal Query: "Why did X fail?"
causal_trace = await graph.traverse(
    start_node="task_failure_xyz",
    graph_type="causal",
    direction="backward",
    max_hops=5
)

# Entity Query: "Who works on Project Alpha?"
team = await graph.traverse(
    start_node="project_alpha",
    graph_type="entity",
    edge_filter=["works_on", "manages"],
    direction="inward"
)

# Temporal Query: "What happened before the outage?"
timeline = await graph.traverse(
    start_node="outage_event",
    graph_type="temporal",
    direction="backward",
    time_window="24h"
)
```

---

### 4.3 Dual-Stream Ingestion Pipeline

#### 4.3.1 Fast Path (Synaptic Ingestion)

**Purpose:** Immediate recall capability, sub-second latency.

**Operations:**
1. Generate embedding (async, non-blocking)
2. Append to vector DB
3. Extract entities (Haiku, lightweight)
4. Queue raw interaction to Write-Ahead Log (WAL)
5. Return acknowledgment

**Latency Budget:** ≤ 500ms (excluding LLM inference)

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| FAST-001 | WAL write before response completion | Durability guarantee |
| FAST-002 | No graph mutations on Fast Path | Zero graph write latency |
| FAST-003 | Entity extraction in parallel with embedding | No sequential dependency |
| FAST-004 | Conflict detection is read-only | Flag for Slow Path only |

#### 4.3.2 Slow Path (Structural Consolidation)

**Purpose:** Deep structural analysis, graph mutation, memory consolidation.

**Operations:**
1. Process WAL entries
2. Resolve flagged conflicts
3. Extract relationship edges for MAGMA graphs
4. Update salience scores
5. Prune/archive low-salience memories
6. Recalculate entity importance rankings
7. Generate causal links from action-outcome patterns

**Timing:** Async background task, 2:00 AM CST (configurable)

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| SLOW-001 | Dedicated Railway Background Worker | Isolated from web server process |
| SLOW-002 | Checkpointing every 100 WAL entries | Resume capability after crash |
| SLOW-003 | Causal edge extraction via LLM | Claude Haiku for cost efficiency |
| SLOW-004 | Consolidation completion notification | Slack/SMS alert on failure |
| SLOW-005 | Memory usage < 2GB during consolidation | OOM prevention |

---

### 4.4 Belief Revision & Epistemic Integrity

#### 4.4.1 Martingale Score Monitoring

Sabine shall monitor her belief update patterns to detect confirmation bias.

**Formula:**
```
M = Σ(predicted_update - actual_update)² / n
```

If M approaches 0 consistently (updates are predictable), reasoning quality is declining.

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| BELIEF-001 | Calculate M on daily consolidation | Score logged to telemetry |
| BELIEF-002 | Alert if M < 0.1 for 7 consecutive days | Triggers self-reflection prompt |
| BELIEF-003 | M score visible in admin dashboard | Historical trend chart |

#### 4.4.2 Non-Monotonic Belief Revision

**Revision Formula:**
```
v' = a · λ_α + v
```

Where:
- `v` = current belief strength
- `a` = argument force (confidence of new evidence)
- `λ_α` = open-mindedness parameter (user-configurable)

**Open-Mindedness Parameter (λ_α):**

| Value Range | Behavior | Use Case |
|-------------|----------|----------|
| 0.1 - 0.3 | Stubborn: High bar for revision | Established facts, core preferences |
| 0.4 - 0.6 | Balanced: Default behavior | Most interactions |
| 0.7 - 0.9 | Malleable: Easy belief updates | Exploratory conversations |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| BELIEF-004 | λ_α configurable via settings dashboard | Persisted in `user_config` |
| BELIEF-005 | Default λ_α = 0.5 | Applied to new users |
| BELIEF-006 | Per-domain λ_α override | Work vs. Personal can differ |
| BELIEF-007 | Push-back triggered when revision would contradict high-confidence memory | VoI calculation applied |

---

### 4.5 Decision-Making & Learning

#### 4.5.1 Active Inference for Clarification

Sabine shall use Value of Information (VoI) to decide when to interrupt.

**Decision Logic:**
```
If (C_error × P_error) > C_int → ASK for clarification
Else → PROCEED with best guess
```

Where:
- `C_error` = Cost of making an error (impact severity)
- `P_error` = Probability of error given current information
- `C_int` = Cost of interruption (user friction)

**Impact Severity Matrix:**

| Action Type | C_error | Examples |
|-------------|---------|----------|
| Irreversible | 1.0 | Send email, delete file, make purchase |
| Reversible | 0.5 | Create draft, schedule tentative event |
| Informational | 0.2 | Answer question, provide summary |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| DECIDE-001 | Classify action type before execution | Classification logged |
| DECIDE-002 | Calculate P_error from context ambiguity | Ambiguity score 0-1 |
| DECIDE-003 | User-configurable C_int threshold | "Chattiness" setting |
| DECIDE-004 | Log all VoI calculations for tuning | Telemetry captured |

#### 4.5.2 Push-Back Protocol

When Prediction Error exceeds threshold:

**Protocol Steps:**
1. Identify conflicting goal or pattern
2. Articulate specific concern with evidence
3. Present alternative if available
4. Await user confirmation or override

**Example:**
```
User: "Cancel all meetings tomorrow"
Sabine: "I notice you have a board presentation at 2pm that was
marked as critical last week. Canceling might impact your Q1
deliverable discussion. Should I:
  A) Cancel all meetings including the board presentation
  B) Keep only the board presentation
  C) Reschedule the board presentation to a different day?"
```

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| PUSH-001 | Push-back includes specific evidence | Reference to memory/entity |
| PUSH-002 | Always provide actionable alternatives | Minimum 2 options |
| PUSH-003 | User override logged for learning | Updates λ_α calibration |
| PUSH-004 | Push-back rate tracked per user | Target: 5-15% of interactions |

---

### 4.6 Autonomous Skill Acquisition

#### 4.6.1 Gap Identification

Sabine tracks tasks resulting in "Human Correction" or "Search Failure."

**Gap Triggers:**
- User significantly edits Sabine's output (>30% change)
- User repeats command with different wording
- Tool execution fails with unknown error
- Task-Turn count exceeds 2σ above mean

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| SKILL-001 | Track gap triggers per task type | Gap frequency dashboard |
| SKILL-002 | Weekly gap analysis report | Top 5 gaps prioritized |
| SKILL-003 | Gap linked to specific capability area | Taxonomy of skills |

#### 4.6.2 Research Loop

**Workflow:**
1. Identify gap → Log to skill_gaps table
2. Autonomous research → Query documentation, GitHub, Stack Overflow
3. Prototype in sandbox → E2B ephemeral kernel
4. Validate → Run test cases
5. Present Skill Proposal → User approval required

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| SKILL-004 | E2B sandbox integration | 30-second timeout per execution |
| SKILL-005 | Sandbox isolation: no prod access | No env vars, no Supabase |
| SKILL-006 | Test data folder mount (read-only) | Controlled input data |
| SKILL-007 | Skill Proposal JSON schema defined | See Section 11.1 |

#### 4.6.3 Skill Promotion Ceremony

**Proposal Schema:**
```json
{
  "skill_id": "uuid",
  "name": "Parse MSG Email Files",
  "description": "Extracts content from Outlook .msg files",
  "trigger_pattern": "file.endswith('.msg')",
  "code": "def execute(file_path): ...",
  "dependencies": ["extract-msg>=0.28.0"],
  "test_results": [
    {"input": "sample.msg", "output": "...", "passed": true}
  ],
  "estimated_roi": {
    "frequency": 5,  // times per week
    "current_cost": 3,  // turns to accomplish
    "projected_cost": 1  // turns with skill
  },
  "created_at": "2026-01-30T10:00:00Z"
}
```

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| SKILL-008 | User approval required for promotion | Explicit "Approve" action |
| SKILL-009 | Approved skills added to tool registry | Hot-reload without restart |
| SKILL-010 | Skill audit log maintained | Approval timestamp + user |
| SKILL-011 | Rollback capability for skills | Disable without deletion |

---

### 4.7 Training & Reinforcement

#### 4.7.1 Implicit Reward Signal ("Dopamine Function")

**Positive Signals:**
- User uses output directly (no edits)
- User says "thank you" or equivalent
- User proceeds to logical next step
- Task completed in fewer turns than historical average

**Negative Signals:**
- User significantly edits output (>30%)
- User repeats command with different wording
- User abandons conversation
- User explicitly expresses frustration

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| TRAIN-001 | Classify implicit signal per turn | Signal logged to telemetry |
| TRAIN-002 | Aggregate signals per task type | Weekly pattern analysis |
| TRAIN-003 | Signals feed into Prompt Selection Policy | Context retrieval tuning |
| TRAIN-004 | No direct model fine-tuning | Prompt/retrieval optimization only |

---

### 4.8 Interaction & Articulation

#### 4.8.1 Metacognitive Monologue

For complex tasks, Sabine shares internal reasoning chain.

**Trigger Conditions:**
- Task estimated at >3 tool calls
- Ambiguity score > 0.5
- Cross-domain information required

**Example:**
```
"I'm cross-referencing your project notes with the current budget
to see if we can afford the third-party API. I'm slightly confused
by the Q3 projection—should I assume 5% growth as you mentioned
last month, or has that changed?"
```

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| META-001 | Monologue triggered by complexity threshold | Logged to telemetry |
| META-002 | Monologue includes specific uncertainty | Points to ambiguous data |
| META-003 | User can disable monologue via setting | `user_config.metacognitive_monologue` |

#### 4.8.2 Streaming Acknowledgment

When inference exceeds latency budget:

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| META-004 | At 8s mark, emit interim acknowledgment | "Let me check my notes..." |
| META-005 | Acknowledgment prevents SMS timeout | Twilio socket stays alive |
| META-006 | Acknowledgment is contextual | References current action |

---

## 5. Technical Requirements

### 5.1 Infrastructure & Deployment

#### 5.1.1 Slow Path Background Worker

**Current State:** APScheduler runs in-process with FastAPI server.

**Required Change:** Dedicated Railway Background Worker service.

**Architecture:**
```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│   FastAPI       │────▶│   Redis      │────▶│   Worker        │
│   (Web Server)  │     │   Queue      │     │   (Slow Path)   │
└─────────────────┘     └──────────────┘     └─────────────────┘
        │                                            │
        ▼                                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      Supabase                               │
│   ┌─────────┐  ┌─────────┐  ┌────────────────────────┐     │
│   │memories │  │entities │  │entity_relationships    │     │
│   └─────────┘  └─────────┘  └────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| INFRA-001 | Redis queue for job handoff | Railway Redis add-on |
| INFRA-002 | Worker process isolation | Separate Railway service |
| INFRA-003 | Checkpointing to Redis | Resume after crash |
| INFRA-004 | Health check endpoint on worker | `/worker/health` |
| INFRA-005 | Consolidation failure alerts | Slack webhook |

#### 5.1.2 E2B Sandbox Service

**Integration:**
```python
from e2b import Sandbox

async def execute_skill_prototype(code: str, test_data: dict):
    sandbox = Sandbox(template="python3")
    sandbox.filesystem.write("/input/data.json", json.dumps(test_data))
    result = sandbox.run_code(code, timeout=30)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code
    }
```

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| INFRA-006 | E2B SDK integrated via FastAPI | `/skill/prototype` endpoint |
| INFRA-007 | 30-second timeout per execution | Hard limit enforced |
| INFRA-008 | No network access in sandbox | Firewall rules applied |
| INFRA-009 | Cost tracking per sandbox spin-up | E2B billing monitored |

---

### 5.2 Latency & Performance Budgets

#### 5.2.1 Fast Path Latency Allocation

**Total Budget:** 10-15 seconds (SMS/Twilio constraint)

| Component | Allocated | Notes |
|-----------|-----------|-------|
| Ingestion/Parsing | 500ms | Entity extraction, embedding start |
| Context Retrieval | 150ms | Vector search + entity graph |
| LLM Inference | 8,000-10,000ms | Primary bottleneck |
| Async Queueing | 50ms | WAL write |
| SMS Gateway | 1,000ms | Twilio network overhead |
| **Total** | ~10-12s | ✓ Within budget |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| PERF-001 | P95 response latency < 12s | Measured via telemetry |
| PERF-002 | Context retrieval P99 < 200ms | Vector search optimized |
| PERF-003 | No graph writes on Fast Path | Enforced by architecture |

#### 5.2.2 Slow Path Performance

| Operation | Target Duration | Notes |
|-----------|-----------------|-------|
| Full consolidation (1000 memories) | < 30 minutes | Nightly window |
| Causal edge extraction (per memory) | < 2 seconds | Haiku inference |
| Salience recalculation (full corpus) | < 10 minutes | Batch SQL |
| Graph integrity check | < 5 minutes | Cycle detection |

---

### 5.3 State Management & Versioning

#### 5.3.1 Memory State Snapshots

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| STATE-001 | Snapshot created on every Slow Path completion | Timestamped archive |
| STATE-002 | Snapshots retained for 30 days | Configurable via env var |
| STATE-003 | Rollback endpoint: `/admin/rollback/{snapshot_id}` | Restores graph state |
| STATE-004 | Snapshot includes: memories, entities, relationships | Full state restoration |

#### 5.3.2 Skill Versioning

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| STATE-005 | Skills stored with version number | Semantic versioning |
| STATE-006 | Skill history preserved | `skill_versions` table |
| STATE-007 | Rollback to previous skill version | Disable current, enable previous |

**Schema:**
```sql
CREATE TABLE skill_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id UUID NOT NULL,
    version VARCHAR(20) NOT NULL,
    code TEXT NOT NULL,
    dependencies JSONB DEFAULT '[]',
    test_results JSONB DEFAULT '[]',
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMP,
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### 5.4 Observability & Telemetry

#### 5.4.1 Metrics to Capture

| Metric | Type | Purpose |
|--------|------|---------|
| `sabine.ttr` | Histogram | Turn-to-Resolution tracking |
| `sabine.proactivity.rate` | Gauge | Proactive suggestions accepted |
| `sabine.clarification.precision` | Gauge | Necessary vs. annoying ratio |
| `sabine.salience.distribution` | Histogram | Memory score spread |
| `sabine.martingale.score` | Gauge | Belief revision health |
| `sabine.skill_gap.count` | Counter | Identified capability gaps |
| `sabine.push_back.rate` | Gauge | Push-back frequency |
| `sabine.latency.fast_path` | Histogram | Response time distribution |
| `sabine.consolidation.duration` | Histogram | Slow path timing |

**Requirements:**

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| OBS-001 | All metrics exported to telemetry backend | Grafana dashboard |
| OBS-002 | Alerting on anomalies | PagerDuty integration |
| OBS-003 | Trace IDs link Fast Path to Slow Path | Correlation preserved |

---

## 6. Technical Guardrails

| Requirement | Description | Implementation |
|-------------|-------------|----------------|
| **HITL-001** | All Skill Updates require user approval | Approval workflow in `/skill/promote` |
| **HITL-002** | Memory Overwrites involving critical logic require confirmation | Flag in conflict resolution |
| **PRIVACY-001** | Personal neuropsychological modeling data encrypted at rest | Supabase column encryption |
| **PRIVACY-002** | λ_α and belief scores never leave local environment | No external API exposure |
| **STABILITY-001** | Nightly Consolidation Process ensures Knowledge Graph consistency | Cycle detection, orphan removal |
| **STABILITY-002** | Non-redundant graph enforcement | Duplicate edge prevention |
| **ROLLBACK-001** | Any state change reversible within 30 days | Snapshot-based restoration |

---

## 7. Success Metrics (KPIs)

| Metric | Definition | Target | Measurement |
|--------|------------|--------|-------------|
| **Turn-to-Resolution (TTR)** | Average turns to complete complex task | < 2.5 | Telemetry aggregate |
| **Proactivity Success Rate** | % proactive suggestions accepted | > 70% | User action tracking |
| **Clarification Precision** | % clarifications deemed "Necessary" | > 80% | Post-task survey |
| **Push-back Acceptance** | % push-backs where user changed course | > 60% | Conversation analysis |
| **Skill Acquisition Rate** | New skills promoted per month | > 2 | Skill registry logs |
| **Memory Salience Health** | Standard deviation of salience scores | < 0.3 | Slow Path report |
| **Martingale Score** | Belief revision randomness | > 0.15 | Daily calculation |

---

## 8. Component Estimation Framework

### 8.1 Estimation Template

For each component, the following structure applies:

```
Component: [Name]
Complexity: Low / Medium / High / Very High
Dependencies: [List of blockers]
Unknowns: [What could blow up the estimate]
Definition of Done: [Acceptance criteria]
Phases:
  - Research/Spike: [Description]
  - Implementation: [Description]
  - Testing: [Description]
  - Integration: [Description]
```

---

### 8.2 Component Estimates

#### 8.2.1 MAGMA Multi-Graph Architecture

```
Component: MAGMA Multi-Graph Architecture
Complexity: Very High
Dependencies:
  - Schema migration for entity_relationships table
  - LLM prompt engineering for relationship extraction
  - Decision: pg_graphql vs. external graph DB

Unknowns:
  - Relationship extraction accuracy with Haiku
  - Query performance at scale (>100k relationships)
  - Graph cycle handling complexity

Definition of Done:
  - Four graph types populated from existing memories
  - Cross-graph traversal queries return in <200ms
  - Causal trace successfully identifies root causes

Phases:
  Research/Spike:
    - Benchmark pg_graphql vs. Neo4j for traversal patterns
    - Test relationship extraction prompts with sample memories
    - Define relationship type taxonomy (20-30 types)
    Deliverable: ADR with chosen approach

  Implementation:
    - Schema migration + indexes
    - Relationship extraction service (Slow Path)
    - Graph query API endpoints
    - Backfill job for existing entities

  Testing:
    - Unit tests for each graph type
    - Performance tests at 10k, 50k, 100k relationships
    - Accuracy tests for extraction (target >80%)

  Integration:
    - Wire into retrieval.py for context enrichment
    - Update core.py deep context injection
    - Dashboard visualization (optional P2)
```

#### 8.2.2 Dual-Stream Ingestion Pipeline

```
Component: Dual-Stream Ingestion Pipeline
Complexity: High
Dependencies:
  - Redis queue setup on Railway
  - Worker service deployment
  - WAL table schema

Unknowns:
  - Redis connection reliability on Railway
  - Checkpoint restoration edge cases
  - WAL growth rate and cleanup strategy

Definition of Done:
  - Fast Path writes to WAL in <50ms
  - Slow Path processes WAL with checkpointing
  - No data loss on worker crash

Phases:
  Research/Spike:
    - Railway Redis add-on evaluation
    - Checkpoint schema design
    - Failure mode analysis
    Deliverable: Deployment architecture diagram

  Implementation:
    - Redis queue integration (rq or dramatiq)
    - Worker service with health checks
    - WAL table + cleanup job
    - Checkpoint save/restore logic

  Testing:
    - Chaos testing: kill worker mid-consolidation
    - Load testing: 10k WAL entries
    - Memory profiling during consolidation

  Integration:
    - Wire memory.py Fast Path to queue
    - Migrate scheduler.py jobs to worker
    - Alerting for consolidation failures
```

#### 8.2.3 Belief Revision System

```
Component: Belief Revision System (λ_α + Martingale)
Complexity: Medium
Dependencies:
  - Memory schema updates (confidence scores)
  - User config for λ_α
  - Telemetry for Martingale tracking

Unknowns:
  - Optimal default λ_α value
  - User comprehension of open-mindedness setting
  - Martingale calculation at scale

Definition of Done:
  - λ_α configurable per user, per domain
  - Conflict resolution uses belief revision formula
  - Martingale score calculated and logged daily

Phases:
  Research/Spike:
    - UX research: how to explain λ_α to users
    - Statistical validation of Martingale formula
    Deliverable: Settings UI mockup, formula validation

  Implementation:
    - Schema: add confidence to memories
    - Belief revision logic in conflict resolution
    - Martingale calculation in Slow Path
    - Settings API + UI component

  Testing:
    - Unit tests for revision formula
    - Simulation: does Martingale detect bias?
    - User testing for settings comprehension

  Integration:
    - Wire into memory.py conflict detection
    - Add to admin dashboard
    - Alerting on Martingale anomaly
```

#### 8.2.4 Autonomous Skill Acquisition

```
Component: Autonomous Skill Acquisition
Complexity: High
Dependencies:
  - E2B account and SDK integration
  - Skill registry refactor for hot-reload
  - Gap detection heuristics

Unknowns:
  - E2B cold start latency
  - Security review for sandbox boundaries
  - User trust in auto-generated skills

Definition of Done:
  - Gap triggers logged and surfaced
  - Research loop queries external docs
  - Skills tested in E2B sandbox
  - Promotion requires explicit approval
  - Hot-reload works without restart

Phases:
  Research/Spike:
    - E2B POC: spin up sandbox, run code, capture output
    - Define skill proposal schema
    - Gap trigger thresholds (user edit %, TTR)
    Deliverable: Working E2B POC, schema doc

  Implementation:
    - Gap detection in core.py
    - skill_gaps table + API
    - Research agent (Perplexity or RAG)
    - E2B execution wrapper
    - Skill proposal + approval workflow
    - Hot-reload mechanism for registry

  Testing:
    - Security audit of sandbox boundaries
    - Test full loop: gap → research → test → propose → approve
    - Hot-reload without service restart

  Integration:
    - Gap detection in implicit reward signal
    - Weekly digest of gaps to user
    - Skill inventory in dashboard
```

#### 8.2.5 Active Inference & Push-Back

```
Component: Active Inference & Push-Back Protocol
Complexity: Medium
Dependencies:
  - Action type classification
  - VoI calculation logic
  - Push-back prompt engineering

Unknowns:
  - Optimal C_int threshold per user
  - Push-back phrasing that doesn't annoy users
  - P_error estimation accuracy

Definition of Done:
  - VoI calculated before irreversible actions
  - Push-back triggers with evidence
  - User override updates learning

Phases:
  Research/Spike:
    - Catalog all action types by reversibility
    - User research: acceptable push-back rate
    - Prompt testing for push-back phrasing
    Deliverable: Action taxonomy, UX guidelines

  Implementation:
    - Action classifier in tool execution
    - VoI calculation module
    - Push-back prompt templates
    - Override logging for learning

  Testing:
    - A/B test push-back rate thresholds
    - User satisfaction survey
    - False positive rate for push-backs

  Integration:
    - Wire into core.py before tool execution
    - Telemetry for push-back metrics
    - Configurable C_int per user
```

#### 8.2.6 Salience-Based Memory Management

```
Component: Salience-Based Memory Management
Complexity: Medium
Dependencies:
  - Memory schema updates
  - Cold storage implementation
  - Salience algorithm tuning

Unknowns:
  - Optimal weight distribution (ω₁, ω₂, ω₃)
  - Cold storage retrieval latency
  - User expectations on memory retention

Definition of Done:
  - Salience score calculated and stored
  - Low-salience memories archived after 30 days
  - Cold storage retrieval <500ms

Phases:
  Research/Spike:
    - Analyze existing memory access patterns
    - Define cold storage format (summary vs. full)
    - Benchmark retrieval from cold storage
    Deliverable: Weight recommendations, storage format spec

  Implementation:
    - Schema migration for salience columns
    - Salience calculation in Slow Path
    - Archive job with 30-day threshold
    - Cold storage table + retrieval API

  Testing:
    - Validate salience distribution
    - Cold retrieval performance tests
    - User testing: are archived memories recoverable?

  Integration:
    - Wire into retrieval.py for hot/cold lookup
    - Dashboard: salience distribution chart
    - User control: manual "pin" to prevent archive
```

#### 8.2.7 Streaming Acknowledgment

```
Component: Streaming Acknowledgment
Complexity: Low
Dependencies:
  - SMS timeout behavior understanding
  - Background thread for timeout monitoring

Unknowns:
  - Exact Twilio timeout threshold
  - User preference for acknowledgment style

Definition of Done:
  - Interim message sent at 8s if response not ready
  - Acknowledgment is contextual
  - SMS socket remains alive

Phases:
  Research/Spike:
    - Test Twilio timeout behavior
    - Draft acknowledgment message templates
    Deliverable: Timeout documentation, templates

  Implementation:
    - Timer thread in invoke handler
    - Contextual acknowledgment generator
    - Early response pathway

  Testing:
    - Simulate slow LLM response
    - Verify SMS delivery after acknowledgment

  Integration:
    - Wire into server.py /invoke endpoint
    - Telemetry for acknowledgment frequency
```

---

### 8.3 Prioritization Matrix

Using MCDA framework from research paper:

| Component | Strategic Value | Technical Risk | Dependencies | Effort | Priority |
|-----------|----------------|----------------|--------------|--------|----------|
| Dual-Stream Pipeline | High | Medium | Redis, Worker | High | **P0** |
| Salience Memory | High | Low | Schema | Medium | **P0** |
| Streaming Ack | High | Low | None | Low | **P0** |
| MAGMA Graphs | High | High | Pipeline | Very High | **P1** |
| Belief Revision | Medium | Medium | Schema | Medium | **P1** |
| Active Inference | Medium | Medium | None | Medium | **P1** |
| Skill Acquisition | Medium | High | E2B, Registry | High | **P2** |

**Recommended Sequence:**
1. **P0 (Foundation):** Dual-Stream + Salience + Streaming Ack
2. **P1 (Intelligence):** MAGMA + Belief Revision + Active Inference
3. **P2 (Autonomy):** Skill Acquisition

---

## 9. Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|------------|--------|------------|
| R-001 | Slow Path OOM at scale | High | High | Dedicated worker, checkpointing, 2GB limit |
| R-002 | E2B cold start latency | Medium | Medium | Pre-warm sandbox pool, timeout handling |
| R-003 | Causal graph complexity explosion | Medium | High | Edge count limits (max 50 per node), pruning |
| R-004 | User confusion with push-back | Medium | Medium | λ_α tuning, clear explanations, disable option |
| R-005 | Relationship extraction accuracy | Medium | Medium | Human review sample, confidence thresholds |
| R-006 | Redis queue reliability | Low | High | Health checks, automatic reconnection, fallback to in-process |
| R-007 | Cold storage retrieval latency | Low | Medium | Index optimization, cache layer |
| R-008 | Skill security vulnerabilities | Medium | High | Sandbox isolation audit, no network access, code review |
| R-009 | λ_α misconfiguration | Low | Medium | Sensible defaults, guardrails (min 0.1, max 0.9) |
| R-010 | Martingale false positives | Low | Low | Human review for alerts, tuning threshold |

---

## 10. Implementation Roadmap

### Phase 1: Foundation (Weeks 1-4)

**Goal:** Establish infrastructure for Sabine 2.0

| Week | Deliverables |
|------|--------------|
| 1 | ADR: Redis vs. in-process queue; Schema migration for salience columns |
| 2 | Railway Background Worker deployed; WAL table implemented |
| 3 | Fast Path → WAL → Slow Path pipeline working end-to-end |
| 4 | Streaming acknowledgment implemented; Salience calculation in Slow Path |

**Exit Criteria:**
- [ ] Worker processes WAL independently
- [ ] Salience scores calculated nightly
- [ ] Streaming ack prevents SMS timeout

### Phase 2: Intelligence (Weeks 5-10)

**Goal:** Implement cognitive capabilities

| Week | Deliverables |
|------|--------------|
| 5-6 | MAGMA schema + relationship extraction service |
| 7 | Cross-graph query API; Backfill job for existing entities |
| 8 | Belief revision formula; λ_α in user settings |
| 9 | VoI calculation; Push-back protocol |
| 10 | Martingale monitoring; Admin dashboard updates |

**Exit Criteria:**
- [ ] Causal graph enables "why did X fail?" queries
- [ ] Push-back triggers on conflicting requests
- [ ] Martingale score alerts on bias

### Phase 3: Autonomy (Weeks 11-14)

**Goal:** Enable self-improvement

| Week | Deliverables |
|------|--------------|
| 11 | Gap detection heuristics; skill_gaps table |
| 12 | E2B integration; Sandbox execution wrapper |
| 13 | Research agent; Skill proposal workflow |
| 14 | Hot-reload mechanism; Skill inventory dashboard |

**Exit Criteria:**
- [ ] Sabine identifies skill gaps from conversation patterns
- [ ] Skills tested in sandbox before promotion
- [ ] Hot-reload works without restart

### Phase 4: Polish (Weeks 15-16)

**Goal:** Production readiness

| Week | Deliverables |
|------|--------------|
| 15 | Telemetry dashboard; Alerting configuration |
| 16 | Documentation; Runbook; Load testing |

**Exit Criteria:**
- [ ] All KPIs tracked in dashboard
- [ ] Runbook covers failure scenarios
- [ ] Load test confirms 10-15s latency at P95

---

## 11. Appendices

### 11.1 Skill Proposal JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["skill_id", "name", "trigger_pattern", "code", "test_results"],
  "properties": {
    "skill_id": {
      "type": "string",
      "format": "uuid"
    },
    "name": {
      "type": "string",
      "maxLength": 100
    },
    "description": {
      "type": "string",
      "maxLength": 500
    },
    "trigger_pattern": {
      "type": "string",
      "description": "Regex or condition that activates this skill"
    },
    "code": {
      "type": "string",
      "description": "Python code with execute(input) function"
    },
    "dependencies": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "test_results": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["input", "output", "passed"],
        "properties": {
          "input": {},
          "output": {},
          "passed": {"type": "boolean"}
        }
      }
    },
    "estimated_roi": {
      "type": "object",
      "properties": {
        "frequency": {"type": "integer"},
        "current_cost": {"type": "number"},
        "projected_cost": {"type": "number"}
      }
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    }
  }
}
```

### 11.2 Relationship Type Taxonomy

| Graph | Relationship Type | Source → Target |
|-------|-------------------|-----------------|
| **Semantic** | `is_type_of` | Entity → Category |
| **Semantic** | `similar_to` | Entity → Entity |
| **Semantic** | `part_of` | Entity → Entity |
| **Temporal** | `precedes` | Event → Event |
| **Temporal** | `concurrent_with` | Event → Event |
| **Temporal** | `follows` | Event → Event |
| **Causal** | `caused_by` | Outcome → Action |
| **Causal** | `resulted_in` | Action → Outcome |
| **Causal** | `prevented_by` | Outcome → Action |
| **Causal** | `enabled_by` | Action → Condition |
| **Entity** | `works_with` | Person → Person |
| **Entity** | `manages` | Person → Project |
| **Entity** | `owns` | Person → Document |
| **Entity** | `member_of` | Person → Organization |
| **Entity** | `related_to` | Entity → Entity |
| **Entity** | `depends_on` | Tool → Tool |
| **Entity** | `created_by` | Document → Person |

### 11.3 Telemetry Event Schema

```json
{
  "event_type": "string",
  "timestamp": "ISO8601",
  "user_id": "uuid",
  "session_id": "uuid",
  "properties": {
    "ttr": "integer",
    "salience_score": "float",
    "martingale_score": "float",
    "push_back_triggered": "boolean",
    "push_back_accepted": "boolean",
    "skill_gap_detected": "boolean",
    "clarification_asked": "boolean",
    "latency_ms": "integer",
    "tool_calls": "integer"
  }
}
```

### 11.4 Glossary

| Term | Definition |
|------|------------|
| **MAGMA** | Multi-Graph Agentic Memory Architecture |
| **Fast Path** | Real-time ingestion with minimal latency |
| **Slow Path** | Async consolidation for structural updates |
| **WAL** | Write-Ahead Log for durability |
| **λ_α** | Open-mindedness parameter for belief revision |
| **Martingale Score** | Metric for detecting confirmation bias |
| **VoI** | Value of Information - decision framework |
| **TTR** | Turn-to-Resolution metric |
| **HITL** | Human-in-the-Loop |
| **E2B** | Engine for 2-Byte - sandbox service |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-01-28 | PM | Initial PRD |
| 2.0.0 | 2026-01-30 | CTO | Added MAGMA, Dual-Stream, Belief Revision, Skill Acquisition, Estimation Framework |

---

*End of Document*
