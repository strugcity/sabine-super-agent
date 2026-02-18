# Dual-Track Implementation Plan: Dream Team + Sabine 2.0 Frontend + SINC

**Status:** DRAFT
**Date:** 2026-02-18
**Owner:** Ryan Knollmaier (CTO)
**Companion Docs:**
- `docs/plans/sabine-frontend-architecture.md` (Frontend Architecture Plan)
- `docs/plans/2026-02-13-sabine-2.0-implementation.md` (Sabine 2.0 Backend)
- `docs/plans/PRD_Mission_Control_Dispatch.md` (Mission Control)
- `docs/PRD_Sabine_2.0_Complete.md` (Sabine 2.0 PRD)
- `docs/PRODUCT_VISION.md` (5-Year Product Vision)

---

## 0. Executive Summary

This document analyzes three interconnected projects, determines their dependencies, and recommends a sequenced implementation strategy.

**The three projects:**

| # | Project | What It Is | Where It Lives |
|---|---------|------------|----------------|
| 1 | **Dream Team** | Multi-agent task orchestration system (agents that write code, manage PRDs, run security audits) | Backend: `sabine-super-agent`. Frontend: `dream-team-strug` |
| 2 | **Sabine 2.0 Frontend** | Web UI for the personal AI agent (chat, memory, observability, skills) | `sabine-super-agent/src/` (Next.js) |
| 3 | **SINC** (Sabine Intelligence Network Core) | Extensible cognitive engine platform -- generalizing Sabine's architecture so Dream Team and future agents run on the same substrate | Does not exist yet. Proposed evolution of `sabine-super-agent` |

**The recommendation:** Track 1 (Dream Team) first, with a focused spike to fix tool reliability. Then Track 2 (Sabine Frontend) in parallel. SINC is an architectural convergence that emerges from the other two -- not a separate build.

---

## 1. Ground Truth: What Exists Today

### 1.1 Sabine Backend (sabine-super-agent)

**85+ API endpoints across 11 FastAPI routers.** Production on Railway.

| System | Status | Key Endpoints |
|--------|--------|---------------|
| Core Agent | Production | `/invoke`, `/invoke/stream`, `/invoke/cached` |
| Memory & Context | Production | `/memory/ingest`, `/memory/query`, `/memory/upload`, `/memory/archived` |
| Entity Graph (MAGMA) | Production | `/api/graph/traverse`, `/api/graph/causal-trace`, `/api/graph/network` |
| Skills Pipeline | Production | `/api/skills/gaps`, `/api/skills/proposals`, `/api/skills/inventory`, `/api/skills/prototype` |
| Salience & Archive | Production | `/api/settings/salience`, `/api/archive/config`, `/api/archive/trigger` |
| Observability | Production | `/health`, `/metrics/*`, `/wal/*`, `/cache/metrics`, `/audit/*`, `/scheduler/*` |
| Dream Team Tasks | Production | `/tasks` (CRUD), `/tasks/dispatch`, `/orchestration/status`, `/roles`, `/repos` |
| Queue (Slow Path) | Production | `/api/queue/health`, `/api/queue/stats` |
| Gmail Integration | Production | `/gmail/handle`, `/gmail/diagnostic`, `/gmail/token-health` |
| User Config | Production | `/api/settings/user-config` |
| SMS (Twilio) | Production | Via Next.js `/api/chat` webhook |

### 1.2 Dream Team (Multi-Agent Orchestration)

**6 agent roles, task queue with dependency tracking, atomic dispatch.** Production API, frontend in separate repo.

| Component | Status | Details |
|-----------|--------|---------|
| Task Queue Service | Production | `backend/services/task_queue.py` -- 35+ methods, dependency DAG, retry with backoff, stuck task detection |
| Task Runner | Production | `lib/agent/task_runner.py` -- role manifest loading, tool scoping, context propagation, tool verification |
| Task Agent | Production | `lib/agent/task_agent.py` -- LangGraph React agent with Dream Team tools |
| 6 Role Manifests | Production | `docs/roles/*.md` -- SABINE_ARCHITECT, backend-architect, frontend-ops, data-ai-engineer, product-manager, qa-security |
| Role-Repo Auth | Production | `lib/agent/shared.py` -- matrix enforced at API + tool level |
| Slack Integration | Production | `lib/agent/slack_manager.py` -- task lifecycle updates |
| Dream Team Frontend | Production | `dream-team-strug` repo on Vercel -- monitoring, task board, event stream |
| Mission Control Form | Not Built | PRD complete (`docs/plans/PRD_Mission_Control_Dispatch.md`) |

### 1.3 Sabine Frontend (Next.js in sabine-super-agent)

**~1,330 LOC.** Next.js 15.1.6, React 19, Tailwind CSS, TypeScript.

| Page | Status | Details |
|------|--------|---------|
| `/` (Home) | Placeholder | Navigation links to other pages |
| `/dashboard/memory` | Working | Entity cards, memory stream, file upload, entity CRUD via Server Actions |
| `/overview` | Placeholder | Mock task data, not connected to real APIs |
| `/api/chat` | Working | Twilio SMS webhook |
| `/api/memory/upload` | Working | File upload proxy |
| `/api/gmail/webhook` | Working | Gmail push notifications |
| `/api/cron/gmail-watch` | Working | Gmail watch renewal |

### 1.4 SINC

**Does not exist.** Zero code, zero documentation under this name. The *concept* exists implicitly in:
- Product Vision "Ecosystem Extensibility" pillar (MCP, skill marketplace, public API)
- Sabine 2.0 PRD's autonomous skill acquisition
- Dream Team's role-based multi-agent framework
- The shared tool registry (`lib/agent/registry.py`) that already unifies local skills, MCP tools, and DB-promoted skills

---

## 2. The Tool Access Problem: Diagnosis

The user identified that **5 of 6 agent roles can't reliably use tools.** This is the single most important blocker. Here is why.

### 2.1 How Tools Are Scoped

```
All Tools (local skills + MCP + DB skills)
    ↓ Filter by AgentRole
    ↓ "coder" → DREAM_TEAM_TOOLS = {github_issues, run_python_sandbox, sync_project_board, send_team_update}
    ↓ Filter by RoleManifest.allowed_tools (wildcard patterns)
    ↓ Final tool set for this agent
```

### 2.2 The Dream Team Tool Set

Dream Team agents get exactly **4 tools:**

| Tool Name | Skill Location | What It Does |
|-----------|---------------|-------------|
| `github_issues` | `lib/skills/github/handler.py` | Create/update files and issues on GitHub |
| `run_python_sandbox` | `lib/skills/e2b_sandbox/handler.py` | Execute Python code in E2B sandbox |
| `sync_project_board` | `lib/skills/project_sync/handler.py` | Sync markdown to GitHub issues |
| `send_team_update` | `lib/skills/slack_ops/handler.py` | Post to Slack channels |

### 2.3 The Reliability Problem

The tools exist in the code. The scoping works. But **the agents don't reliably USE them.** Based on the verification system already built into `task_runner.py` (lines 265-300), the common failure mode is:

```
Task: "Implement the new caching module"
Expected: Agent calls github_issues(action="create_file", ...) to write code
Actual: Agent writes a PLAN describing what it would do, without calling any tools
Result: verification_passed = False, warning = "NO_TOOLS_CALLED"
```

**Root causes (hypothesized -- spike needed to confirm):**

1. **Prompt insufficiency.** Role manifests tell agents *what* tools exist but may not give enough examples of *how* to call them with correct parameters. The SABINE_ARCHITECT manifest (lines 88-148) has detailed tool usage examples -- the other 5 roles may not.

2. **Model capability mismatch.** If using Haiku for task execution (as the implementation plan suggests for cost), smaller models are worse at complex multi-step tool calling. Claude Sonnet or Opus may be needed for implementation tasks.

3. **Tool schema complexity.** The `github_issues` tool has a complex schema (action, owner, repo, path, content, message, branch, labels, etc.). Without clear guidance in the system prompt, agents hallucinate parameters or avoid calling the tool entirely.

4. **Missing feedback loop.** When a tool call fails, the agent doesn't always retry or adjust. The current React agent (LangGraph) may need its iteration limit increased, or a retry strategy injected into the system prompt.

5. **MCP tool loading failures.** If the MCP server for GitHub fails to connect (network, auth), the tool simply doesn't load -- silently. The agent then has no `github_issues` tool available but doesn't know to report this.

### 2.4 The Fix Is a Spike, Not a Rewrite

This is not an architecture problem. The wiring is correct. The problem is in the intersection of: prompts, model selection, and tool call verification. A 3-day spike can diagnose and fix it.

---

## 3. Dependency Analysis

### 3.1 Project Dependency Graph

```
                    ┌─────────────────────┐
                    │  Tool Access Spike   │
                    │  (3 days)            │
                    └──────────┬──────────┘
                               │
                 UNBLOCKS      │      UNBLOCKS
              ┌────────────────┼─────────────────┐
              │                │                  │
              ▼                ▼                  ▼
┌──────────────────┐  ┌───────────────┐  ┌───────────────────┐
│  Track 1:        │  │  Track 1b:    │  │  Track 2:         │
│  Dream Team      │  │  Orchestrator │  │  Sabine Frontend  │
│  Agent Fixes     │  │  Agent        │  │                   │
│  (2 weeks)       │  │  (2 weeks)    │  │  (9 weeks)        │
└────────┬─────────┘  └───────┬───────┘  └───────────────────┘
         │                     │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Track 1c:          │
         │  Mission Control    │
         │  Form (2-3 days)    │
         └─────────────────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  SINC Convergence   │
         │  (Emerges naturally │
         │   from Track 1+2)   │
         └─────────────────────┘
```

### 3.2 Dependency Matrix

| Depends On → | Tool Spike | Dream Team Fixes | Orchestrator | Sabine Frontend | Mission Control |
|:-------------|:----------:|:----------------:|:------------:|:---------------:|:---------------:|
| **Tool Spike** | -- | -- | -- | -- | -- |
| **Dream Team Fixes** | YES | -- | -- | -- | -- |
| **Orchestrator** | YES | Partial | -- | -- | -- |
| **Sabine Frontend** | No | No | No | -- | -- |
| **Mission Control** | No | Helpful | Helpful | No | -- |
| **SINC** | YES | YES | YES | YES | No |

### 3.3 Key Finding: Tracks Are Parallelizable

**Track 1 (Dream Team)** and **Track 2 (Sabine Frontend)** have **zero hard dependencies on each other.** They share the same backend but touch completely different API surfaces:
- Dream Team uses: `/tasks`, `/roles`, `/repos`, `/orchestration/status`
- Sabine Frontend uses: `/invoke/stream`, `/memory/*`, `/api/graph/*`, `/api/skills/*`, `/api/settings/*`, `/health`, `/metrics/*`

The only shared dependency is the **Tool Access Spike**, which is a prerequisite for Track 1 but not Track 2. The Sabine Frontend doesn't use Dream Team tools at all -- it consumes FastAPI endpoints via fetch/SSE.

### 3.4 What About SINC?

SINC is not a project to build. It is an architectural convergence that happens when:

1. **Sabine's substrate** (memory, graph, skills, observability) is exposed through the frontend as a manageable platform.
2. **Dream Team's orchestration** (task queue, role-based dispatch, dependency DAG) is reliable and autonomous.
3. **The two share a common runtime** (they already do -- same FastAPI server, same Supabase, same tool registry).

**SINC = Sabine backend + Dream Team orchestration + Frontend observability/control plane.** It is not a third codebase. It is what you get when Track 1 and Track 2 are both complete and the interfaces between them are formalized (e.g., Dream Team tasks visible in Sabine Frontend observability, Sabine skills usable by Dream Team agents).

The explicit SINC work is:
- Define which Sabine APIs become "platform APIs" (public, documented, versioned)
- Build a plugin/extension SDK for third-party agent types
- Formalize the MCP integration as the extension mechanism

This is Year 2 work (per Product Vision). It should be *designed for* in Track 1 and Track 2, but not *built* yet.

---

## 4. Recommended Sequence

### Phase 0: Tool Access Spike (3 days)

**Goal:** Diagnose and fix tool reliability so Dream Team agents can actually execute tasks.

**Why first:** Nothing else in Track 1 matters if agents can't use tools. This spike determines whether the fix is prompts, model selection, tool schemas, or architecture.

#### Spike Tasks

| # | Task | Method | Expected Output |
|---|------|--------|-----------------|
| 1 | **Instrument tool call success rates** | Add logging to `task_agent.py` at tool call entry/exit. Run 10 test tasks across 3 roles. Measure: % of tasks where tools are called, % where tool calls succeed. | Baseline metrics (e.g., "35% of implementation tasks result in zero tool calls") |
| 2 | **Test model impact** | Run same 10 tasks with Haiku, Sonnet, and Opus. Compare tool call rates. | Model recommendation per task complexity |
| 3 | **Audit role prompts** | Compare SABINE_ARCHITECT manifest (which has detailed tool usage docs) with other 5 roles. Identify gaps. | Gap list per role |
| 4 | **Fix #1: Enhance role manifests** | Add `MANDATORY TOOL USAGE` sections (like SABINE_ARCHITECT has) to all 5 other role manifests with concrete examples. | Updated `docs/roles/*.md` |
| 5 | **Fix #2: Add tool call validation in system prompt** | Inject a post-task self-check: "Before finishing, verify you called tools. If you only wrote plans, you MUST execute them now." | Updated `task_agent.py` system prompt |
| 6 | **Fix #3: Verify tool loading** | Add pre-execution check in `task_agent.py`: if 0 tools loaded, fail immediately with clear error (not silent). | Updated `task_agent.py` |
| 7 | **Retest** | Rerun 10 tasks with fixes. Target: >80% tool call rate on implementation tasks. | Pass/fail report |

#### Spike Deliverables
- Baseline tool reliability metrics
- Model recommendation (which model for which task complexity)
- Updated role manifests with mandatory tool usage docs
- Updated task agent with tool validation
- Post-fix metrics showing improvement

---

### Track 1: Dream Team -- Make It Work (Weeks 1-6)

**Goal:** Dream Team goes from "can dispatch tasks" to "reliably completes multi-step missions with human-adjustable autonomy."

#### Track 1A: Agent Reliability (Weeks 1-2)

Apply spike findings across all agents. Harden the execution loop.

| # | Task | Details |
|---|------|---------|
| 1 | **Role manifest standardization** | Every role manifest gets: mandatory tool usage section, parameter examples, success/failure examples, self-verification checklist. Follow SABINE_ARCHITECT pattern. |
| 2 | **Model routing** | Add `model_preference` to task payload. Analysis tasks (review, plan) → Haiku. Implementation tasks (create file, write code) → Sonnet. Architecture tasks → Opus. Map this in `task_agent.py` using the existing `model_preference` field in RoleManifest. |
| 3 | **Tool loading validation** | Fail fast if tool count is 0. Log which tools loaded vs. expected. Surface in task result. |
| 4 | **Retry-on-no-tools** | If task completes with `NO_TOOLS_CALLED` warning AND task requires tools, automatically retry once with an appended prompt: "Your previous attempt did not use tools. You MUST call tools this time." |
| 5 | **Enhanced error context** | When a tool call fails, include the error in the agent's conversation so it can adjust and retry within the same execution. |
| 6 | **Test suite** | Create `tests/test_dream_team_reliability.py`: 10 standard tasks across 5 roles, assert tool calls occur, assert success rate >80%. |

#### Track 1B: Orchestrator Agent (Weeks 2-4)

**The orchestrator is the SABINE_ARCHITECT role, upgraded to be the dispatch brain.**

The user specified: "The orchestrator agent should be the architect-level agent. This agent should be able to do every other agent's jobs in order to know how to unblock them. The orchestrator agent will take the dispatch from Mission Control, assign out the tasks, assign the order of tasks, and make sure the handoffs occur."

##### Orchestrator Design

**Identity:** SABINE_ARCHITECT becomes the orchestrator. It is not a new role -- it is the existing architect role with expanded capabilities.

**Current state:** SABINE_ARCHITECT already has the right framing (see `docs/roles/SABINE_ARCHITECT.md`): it "sits at the center of a One-Human, Multi-Agent Team" and "translates high-level vision into actionable engineering plans." What it lacks is the *execution machinery* to actually dispatch and monitor tasks.

**What to build:**

| Component | Description | Implementation |
|-----------|-------------|----------------|
| **Mission Decomposition** | Takes a high-level objective and breaks it into tasks with dependencies | New function in `lib/agent/orchestrator.py`: `decompose_mission(objective) -> List[CreateTaskRequest]` |
| **Task Dispatch** | Creates tasks via the task queue, sets dependencies, triggers dispatch | Uses existing `TaskQueueService.create_task_with_validation()` + `dispatch` |
| **Progress Monitoring** | Watches task completion, detects stuck/failed tasks | Uses existing `get_task_queue_health()`, `get_stuck_tasks()`, `get_blocked_tasks()` |
| **Unblock Logic** | When an agent fails, decides: retry, reassign, try different approach, or escalate to human | New function: `handle_blocked_task(task) -> UnblockAction` |
| **Handoff Management** | Ensures context flows from completed tasks to dependent tasks | Already works via `_run_task_agent` context propagation (lines 153-181 in `task_runner.py`) |

##### Unblock Decision Tree

```
Task Failed
    ├─ Is it a tool failure? (MCP down, auth expired)
    │   ├─ YES: Retry with backoff (already built: fail_task_with_retry)
    │   └─ NO: Continue
    ├─ Is it a prompt/model failure? (NO_TOOLS_CALLED, plan-only output)
    │   ├─ YES, attempt 1: Retry with enhanced prompt + model upgrade
    │   ├─ YES, attempt 2: Reassign to different role with same objective
    │   └─ YES, attempt 3: Pause and escalate to human
    ├─ Is it a dependency failure? (parent task failed)
    │   ├─ Can dependency be skipped? → Try without, note degraded output
    │   └─ Cannot skip → Fix parent first, then re-trigger dependent chain
    └─ Unknown error
        └─ Pause and escalate to human with full context
```

##### Autonomy Levels

The user specified: "Autonomy should be adjustable. Semi-autonomous should be the default."

| Level | Name | Behavior |
|-------|------|----------|
| 0 | **Manual** | Every task requires human approval before dispatch. Every result requires human review before marking complete. |
| 1 | **Semi-Autonomous** (default) | Orchestrator decomposes mission and presents plan for approval. After approval, executes autonomously. Pauses on: failures after 2 retries, budget exceeded, scope creep detected. Presents results for review. |
| 2 | **Autonomous** | Orchestrator decomposes and executes without approval. Only pauses on: unrecoverable failures, budget exceeded. Sends notifications on milestones. Human reviews results async. |
| 3 | **Full Auto** | Everything autonomous including retries and alternative approaches. Only escalates on total mission failure. |

**Implementation:** Add `autonomy_level` field to mission dispatch. Default to 1. The orchestrator checks the level at each decision point (decompose, dispatch, retry, escalate).

##### Orchestrator API Extensions

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /missions` | Create | Submit a high-level mission objective. Orchestrator decomposes into tasks. |
| `GET /missions/{id}` | Read | Get mission status, progress, task breakdown. |
| `POST /missions/{id}/approve` | Action | Approve the orchestrator's decomposition plan (required at autonomy level 0-1). |
| `POST /missions/{id}/pause` | Action | Pause all tasks in this mission. |
| `POST /missions/{id}/resume` | Action | Resume a paused mission. |
| `GET /missions/{id}/tasks` | Read | Get all tasks in this mission with status. |

#### Track 1C: Mission Control Form (Week 4-5, 2-3 days)

**Build the Mission Control form in `dream-team-strug` repo.** PRD is already complete (`docs/plans/PRD_Mission_Control_Dispatch.md`).

This is a straightforward frontend feature -- the PRD specifies exactly what to build:
- Mission injection form with role/repo dropdowns
- JSON preview panel
- Dynamic role filtering by repo authorization
- Success/error toast notifications

**Enhancement over PRD:** Instead of just creating individual tasks, the form should also support creating *missions* (via the new `POST /missions` endpoint from Track 1B). The form would have two modes:
1. **Task Mode** (existing PRD): Create a single task for a specific role
2. **Mission Mode** (new): Submit a high-level objective for the orchestrator to decompose

#### Track 1D: Transparency & Observability (Weeks 4-6)

"Transparency and observability is key. The ability for the human operator to quickly approve semi-autonomous work and pass the task to the agent is key."

| # | Feature | Where | Details |
|---|---------|-------|---------|
| 1 | **Real-time task status updates** | `dream-team-strug` | Add SSE endpoint for task events (started, completed, failed, retrying). Replace polling with push. |
| 2 | **Mission progress view** | `dream-team-strug` | Show mission as a task DAG: nodes are tasks, edges are dependencies. Color by status. |
| 3 | **One-click approval** | `dream-team-strug` | For tasks in `awaiting_approval` status: show task output, [Approve] / [Reject] / [Retry] buttons. |
| 4 | **Tool call transparency** | `dream-team-strug` | Expand task detail to show: which tools were called, success/failure, artifacts created. Already stored in `task.result.tool_execution`. |
| 5 | **Orchestrator decision log** | Backend | Log each orchestrator decision (decompose, dispatch, retry, escalate) with reasoning. Expose via `GET /missions/{id}/decisions`. |
| 6 | **Budget tracking** | Backend | Track token usage per task and per mission. Surface in task result and mission summary. |

---

### Track 2: Sabine Frontend (Weeks 1-9, Parallel with Track 1)

**Goal:** Build the full Sabine web experience. This track is fully detailed in `docs/plans/sabine-frontend-architecture.md`.

Track 2 has **zero dependency on Track 1.** It consumes Sabine backend APIs, which are all production-ready. It can start immediately.

#### Summary (details in companion doc)

| Phase | Duration | Focus | Key Deliverables |
|-------|----------|-------|------------------|
| Phase 1 | Weeks 1-3 | Foundation + Chat | shadcn/ui setup, sidebar, chat interface with SSE streaming, debug panel, session management |
| Phase 2 | Weeks 4-6 | Memory + Settings + Observability | Salience controls, archive config, settings page, health dashboard, skills dashboard |
| Phase 3 | Weeks 7-9 | Graph + Polish | Entity graph explorer, causal traces, command palette, responsive design, accessibility |

#### SINC-Relevant Design Decisions in Track 2

While building the frontend, make these decisions with SINC in mind:

1. **API client abstraction.** Build `src/lib/api/client.ts` as a typed API client. This becomes the SDK prototype for third-party developers.
2. **Observability dashboard is generic.** Design the observability page to show *any* agent's health, not just Sabine's. This is the future SINC control plane.
3. **Skills dashboard as marketplace preview.** The skills management UI (gaps, proposals, inventory) is the prototype for the eventual skill marketplace.
4. **Dream Team task view in observability.** Include a read-only task overview at `/observability/tasks` that consumes `GET /tasks` -- this connects the two tracks and shows how SINC would present multi-agent activity.

---

## 5. SINC: The Convergence Plan

SINC is not built. SINC emerges.

### 5.1 What SINC Actually Is

SINC is the realization that Sabine's backend infrastructure is not Sabine-specific -- it is a general-purpose cognitive engine:

| Sabine Component | SINC Generalization |
|------------------|---------------------|
| Memory system (pgvector + MAGMA) | Any agent can store and query contextual memory |
| Skills pipeline (gap detection + E2B sandbox + promotion) | Any agent can learn new capabilities autonomously |
| Tool registry (local + MCP + DB skills) | Any agent can access a unified tool catalog |
| Salience scoring + archival | Any agent can manage long-term knowledge compaction |
| Task queue + orchestration | Any agent team can be dispatched and monitored |
| Observability endpoints | Any agent's health and metrics are trackable |

### 5.2 What Makes Sabine "Sabine" vs. What Is Platform

| Sabine-Specific (Not Platform) | Platform (SINC) |
|--------------------------------|-----------------|
| Custody schedule awareness | Memory ingestion + query APIs |
| Family coordination logic | Entity graph + relationship extraction |
| SMS/Twilio integration | Communication channel abstraction |
| Morning briefing scheduling | Scheduled job framework |
| Personal preferences | User config key-value store |
| Conversational personality | Agent prompt template system |

### 5.3 SINC Milestones (Not Scheduled, Design-For-Now)

| Milestone | Trigger | Work Required |
|-----------|---------|---------------|
| **M1: API Documentation** | Track 2 Phase 1 complete (API client built) | Document all FastAPI endpoints with OpenAPI schema. Publish as reference. |
| **M2: Agent Registration** | Track 1B complete (orchestrator works) | Formalize how new agent types register (role manifest format, tool access patterns, auth). Currently implicit -- make it an explicit `/agents` API. |
| **M3: Shared Memory Space** | Track 2 Phase 2 complete (memory dashboard works) | Define memory isolation: per-agent, per-user, shared. Currently all memory is user-scoped. Add optional `agent_scope` to memory records. |
| **M4: Skill Marketplace** | Track 2 Phase 2 complete (skills dashboard works) | Allow sharing skill proposals across agent types. Currently user-scoped. Add `visibility` field. |
| **M5: Plugin SDK** | M1-M4 complete | Bundle API client + agent registration + memory access + skill management into a developer SDK. Publish docs. Target: Year 2 per Product Vision. |

### 5.4 Dream Team as First SINC Consumer

Dream Team is already the first "non-Sabine agent" running on Sabine's infrastructure:
- Uses the same FastAPI server
- Uses the same Supabase database (task_queue table)
- Uses the same tool registry (filtered to Dream Team tools)
- Uses the same MCP infrastructure

The difference is that Dream Team agents **don't use Sabine's memory or context engine.** This is intentional (coding agents don't need custody schedules). But SINC would allow Dream Team agents to optionally use *their own* memory space -- e.g., remembering past codebase analysis, prior PR review feedback, or common patterns.

**Action item for Track 1:** When building the orchestrator, design the context propagation to support a Dream Team memory space. Don't build it yet, but ensure the task runner can be extended to inject contextual memory per agent type (not just per user).

---

## 6. Orchestrator Architecture (Detailed)

### 6.1 SABINE_ARCHITECT as Orchestrator

The user specified: "The orchestrator should be able to do every other agent's jobs in order to know how to unblock them."

**This means:** SABINE_ARCHITECT's role manifest should include a *summary* of every other role's capabilities, constraints, and common failure modes. It doesn't literally run as every role -- it has the *knowledge* to understand what went wrong and how to fix it.

**Updated SABINE_ARCHITECT manifest additions:**

```markdown
## Agent Team Knowledge Base

### backend-architect-sabine
- **Can do:** Python backend code, FastAPI routes, LangGraph state machines, Supabase migrations
- **Tools:** github_issues (create_file, update_file), run_python_sandbox
- **Common failures:** Forgetting to use github_issues tool (writes plan instead of code), wrong repo targeting
- **Unblock strategy:** Re-prompt with explicit "use github_issues create_file" instruction, escalate model to Sonnet

### frontend-ops-sabine
- **Can do:** TypeScript, Next.js, React components, Tailwind CSS, Vercel deployment
- **Tools:** github_issues (create_file, update_file), run_python_sandbox (for testing logic)
- **Common failures:** Wrong repo (targets sabine-super-agent instead of dream-team-strug)
- **Unblock strategy:** Verify target_repo in payload, re-dispatch with correct repo context

### data-ai-engineer-sabine
- **Can do:** SQL migrations, pgvector operations, prompt engineering, context tuning
- **Tools:** github_issues, run_python_sandbox (SQL testing)
- **Common failures:** SQL syntax errors in migrations, missing pgvector index
- **Unblock strategy:** Run SQL in sandbox first, then create file

### product-manager-sabine
- **Can do:** PRDs, acceptance criteria, scope analysis, backlog management
- **Tools:** github_issues (create issues), send_team_update
- **Common failures:** Creates issues without proper labels/assignees
- **Unblock strategy:** Provide issue template in prompt

### qa-security-sabine
- **Can do:** Security audits, test plans, penetration testing docs, OAuth verification
- **Tools:** github_issues (security reports), run_python_sandbox (test execution)
- **Common failures:** Overly broad scope, doesn't focus on specific attack vectors
- **Unblock strategy:** Narrow scope in prompt, provide specific targets
```

### 6.2 Mission Lifecycle

```
Human Operator
    │
    ▼
POST /missions
{
  "objective": "Implement rate limiting for the /invoke endpoint",
  "autonomy_level": 1,  // semi-autonomous
  "budget": { "max_tasks": 10, "max_tokens": 100000 }
}
    │
    ▼
Orchestrator (SABINE_ARCHITECT)
    │
    ├── 1. DECOMPOSE
    │   Analyze objective → Generate task breakdown
    │   Output: List of tasks with roles, dependencies, priority
    │
    ├── 2. PRESENT PLAN (autonomy_level <= 1)
    │   POST notification to human via Slack + dashboard
    │   Wait for: POST /missions/{id}/approve
    │
    ├── 3. DISPATCH
    │   Create all tasks via TaskQueueService
    │   Set dependencies (DAG)
    │   Trigger dispatch for root tasks (no dependencies)
    │
    ├── 4. MONITOR (async loop)
    │   Every 60s:
    │   - Check task statuses
    │   - Detect stuck tasks (> timeout_seconds)
    │   - Detect failed tasks
    │   - Handle blocked tasks
    │
    ├── 5. UNBLOCK (when needed)
    │   Apply decision tree (Section 4, Track 1B)
    │   Log each decision to mission decisions table
    │
    ├── 6. COMPLETE
    │   All tasks done → Aggregate results
    │   POST notification to human
    │   Status: completed / partially_completed / failed
    │
    └── 7. REVIEW (human)
        Human reviews results via dashboard
        Approves / requests changes / dismisses
```

### 6.3 Data Model

```python
class Mission(BaseModel):
    id: UUID
    objective: str                      # High-level goal
    autonomy_level: int = 1             # 0=manual, 1=semi, 2=auto, 3=full
    status: MissionStatus               # planning, awaiting_approval, executing, paused, completed, failed
    budget: MissionBudget               # max_tasks, max_tokens, max_retries
    task_ids: List[UUID] = []           # Tasks created for this mission
    decisions: List[OrchestratorDecision] = []  # Decision log
    result_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    created_by: str                     # Human operator ID

class OrchestratorDecision(BaseModel):
    timestamp: datetime
    decision_type: str                  # decompose, dispatch, retry, reassign, escalate, complete
    reasoning: str                      # Why this decision was made
    task_id: Optional[UUID] = None      # Which task this applies to
    action_taken: str                   # What was done
```

---

## 7. Timeline & Gantt

```
Week:   0    1    2    3    4    5    6    7    8    9
        │    │    │    │    │    │    │    │    │    │
SPIKE   ████│    │    │    │    │    │    │    │    │  Tool Access (3d)
        │    │    │    │    │    │    │    │    │    │
TRACK 1 │    │    │    │    │    │    │    │    │    │
  1A    │████████ │    │    │    │    │    │    │    │  Agent Reliability (2w)
  1B    │    │████████ │    │    │    │    │    │    │  Orchestrator (2w)
  1C    │    │    │    │████│    │    │    │    │    │  Mission Control (3d)
  1D    │    │    │    │████████ │    │    │    │    │  Transparency (2w)
        │    │    │    │    │    │    │    │    │    │
TRACK 2 │    │    │    │    │    │    │    │    │    │
  P1    │█████████████ │    │    │    │    │    │    │  Foundation+Chat (3w)
  P2    │    │    │    │█████████████ │    │    │    │  Memory+Settings+Obs (3w)
  P3    │    │    │    │    │    │    │█████████████ │  Graph+Polish (3w)
        │    │    │    │    │    │    │    │    │    │
SINC    │    │    │    │    │    │ M1 │    │    │ M2 │  Milestones (design-for)
```

**Total timeline:** ~10 weeks (spike + 9 weeks parallel)
**Track 1 completes:** Week 6
**Track 2 completes:** Week 9
**SINC M1 (API docs):** Week 6 (Track 2 API client built)
**SINC M2 (Agent registration):** Week 9+ (Track 1B orchestrator mature)

---

## 8. Priority Ranking

If resources are constrained and you must choose, here is the priority order:

| Priority | Item | Why |
|----------|------|-----|
| **P0** | Tool Access Spike | Nothing works without reliable tool execution |
| **P1** | Track 1A: Agent Reliability | Core Dream Team value proposition |
| **P1** | Track 2 Phase 1: Chat Interface | Core Sabine user experience |
| **P2** | Track 1B: Orchestrator | Enables autonomous multi-agent execution |
| **P2** | Track 2 Phase 2: Memory + Observability | Makes backend capabilities accessible |
| **P3** | Track 1C: Mission Control | UX improvement (CLI works as interim) |
| **P3** | Track 1D: Transparency | Enables trust for higher autonomy levels |
| **P3** | Track 2 Phase 3: Graph + Polish | Nice-to-have, not critical path |
| **P4** | SINC Milestones | Design-for, not build-now |

---

## 9. Risk Register

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Tool spike reveals architectural problem (not just prompt issue) | High | Low | Spike is time-boxed to 3 days. If architecture change needed, it becomes Track 1A work with revised timeline. |
| Model costs exceed budget for implementation tasks | Medium | Medium | Use Haiku for analysis, Sonnet for implementation. Monitor via `/cache/metrics`. Set per-mission token budgets. |
| Orchestrator over-retries, burning tokens on hopeless tasks | Medium | Medium | Budget limits per mission. Retry cap per task (already exists: max_retries=3). Escalate to human after cap. |
| Track 1 and Track 2 create merge conflicts | Low | Low | Different file paths (backend vs. frontend). Track 1 touches `lib/agent/`, Track 2 touches `src/`. Only shared: `docs/`. |
| Dream Team frontend (`dream-team-strug`) diverges from Sabine frontend patterns | Medium | Medium | Establish shared design system early (shadcn/ui + Tailwind tokens). Document component patterns in `docs/design-system.md`. |

---

## 10. Success Criteria

### Track 1: Dream Team
- [ ] Tool call success rate >80% for implementation tasks (up from current baseline)
- [ ] Orchestrator can decompose a 5-task mission and execute it end-to-end
- [ ] Semi-autonomous mode works: orchestrator pauses for approval, resumes on command
- [ ] Mission Control form replaces CLI for task creation
- [ ] Human can see task progress, tool calls, and artifacts in real-time

### Track 2: Sabine Frontend
- [ ] User can chat with Sabine via web UI with streaming responses
- [ ] Memory dashboard supports viewing, archiving, promoting, and configuring salience
- [ ] Skills lifecycle manageable from UI (view gaps, approve/reject, disable/rollback)
- [ ] System health visible at a glance
- [ ] `npm run build` and `npm run lint` pass with zero errors

### SINC (Design-For)
- [ ] API client (`src/lib/api/client.ts`) covers all backend endpoints with types
- [ ] Observability dashboard shows both Sabine metrics and Dream Team task status
- [ ] No Sabine-specific assumptions baked into reusable components (API client, memory table, skill cards)

---

## 11. Answers to Planning Questions

### Q1: Scope
This document is the **detailed technical implementation plan** for both tracks plus a recommendation.

### Q2: Track recommendation
**Start Track 1 (Dream Team) with the Tool Access Spike AND Track 2 (Sabine Frontend) in parallel.** The spike unblocks Track 1. Track 2 has no dependency on Track 1 and can start immediately.

### Q3: Sabine 2.0 "master frontend"
This refers to the **Next.js frontend in `sabine-super-agent/src/`**. There is no separate project. The frontend architecture plan (`docs/plans/sabine-frontend-architecture.md`) defines it.

### Q4: SINC
SINC is a **proposed extension of Sabine's architecture** to serve as an extensible cognitive engine for multiple agent types. It is not a separate codebase. It is the convergence of Sabine's substrate + Dream Team's orchestration + a formal extension API. See Section 5.

### Q5: Dependencies between projects
**Track 1 and Track 2 are parallelizable.** There is a path to get Dream Team fully functional first (Track 1, 6 weeks), THEN build the Sabine frontend (Track 2, 9 weeks), OR run them in parallel. Running in parallel is faster and does not create conflicts. Dream Team work should NOT block on SINC. Dream Team should be *designed for composability* with SINC (see Section 5.4 action item).

### Q6: Orchestrator design
SABINE_ARCHITECT becomes the orchestrator. It knows every other agent's capabilities and failure modes. It decomposes missions, dispatches tasks, monitors progress, and makes unblock decisions. See Section 6.

### Q7: Unblocking
The orchestrator has a decision tree: retry (with prompt enhancement + optional model upgrade) → reassign to different role → try alternative approach → pause and escalate to human. See Section 6.2 unblock decision tree.

### Q8: Tool access fix
**P0 priority.** The 3-day spike runs first, before any other Track 1 work. The fix is likely in prompts + model selection, not architecture.

### Q9: Autonomy level
Adjustable. Four levels (manual, semi-autonomous, autonomous, full auto). Default: semi-autonomous. Configurable per mission. See Track 1B autonomy levels table.

### Q10: Timeline priority
Tool Spike → Track 1A + Track 2 Phase 1 in parallel → Track 1B + Track 2 Phase 2 → Track 1C+1D + Track 2 Phase 3. See Gantt chart and priority ranking.

---

*End of Document*
