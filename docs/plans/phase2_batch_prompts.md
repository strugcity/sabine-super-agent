# Phase 2: Separate Agent Cores — Batch Prompts for Copilot

Use these 4 prompts sequentially. Complete and verify each batch before starting the next.
Each prompt is self-contained and copy-paste ready.

---

## BATCH A: Define Tool Sets

### Project Overview

Sabine Super Agent — a personal AI agent with a Python/FastAPI backend and Next.js frontend.

- **Backend:** Python 3.11+, FastAPI, Supabase (Postgres + pgvector)
- **AI/Agents:** LangChain/LangGraph, Pydantic v2
- **Coding rules:** All functions must have full type hints. Use Pydantic v2 `BaseModel` for schemas. Never swallow errors silently — use `logging`. Use lazy imports (inside functions) when importing between modules that reference each other to avoid circular dependencies. Run `python -m py_compile <file>` to syntax-check after edits.

### Architecture (Current State)

```
lib/agent/
├── core.py          # Agent orchestration — run_agent() at line ~1326, create_agent(),
│                    #   load_deep_context(), build_static_context(), build_dynamic_context(),
│                    #   load_role_manifest()
├── registry.py      # Tool registry — get_all_tools() loads ALL local skills + MCP tools
│                    #   load_local_skills() scans lib/skills/ for manifest.json + handler.py
│                    #   No scoping mechanism — every agent gets every tool
├── retrieval.py     # Memory retrieval — retrieve_context() at line ~378
│                    #   Calls search_similar_memories() → supabase.rpc("match_memories")
│                    #   No role filtering
├── memory.py        # Memory ingestion — ingest_user_message() at line ~426
│                    #   Stores metadata: {user_id, source, timestamp, domain, original_content}
│                    #   No role field
├── models.py        # RoleManifest model at line ~13: role_id, title, instructions,
│                    #   allowed_tools (list, empty=all), model_preference
├── shared.py        # Shared models, constants, auth dependencies
├── llm_config.py    # LLM configuration
├── model_router.py  # Model selection logic
├── mcp_client.py    # MCP tool client
├── routers/
│   ├── sabine.py        # POST /invoke at line ~35 — calls run_agent() from core.py
│   ├── dream_team.py    # Task CRUD endpoints, role listing
│   ├── gmail.py         # Gmail push notifications
│   ├── memory.py        # Memory ingest/query/upload endpoints
│   └── observability.py # Logging/metrics endpoints
└── ...

server.py            # 726 lines — thin shell with router mounting
                     # Contains _run_task_agent(task) at line ~222
                     #   Calls run_agent() with role=task.role
                     #   Implements context propagation, repo context injection,
                     #   tool execution verification, retry logic, Slack updates
```

**The problem:** One `run_agent()` function serves both Sabine (conversational) and Dream Team (coding) agents. One tool registry gives every agent every tool. Memory retrieval has no role scoping.

### What's Wrong (Detail)

1. **Single run_agent() serves both systems.** `lib/agent/core.py` has one `run_agent()` function called by Sabine's `/invoke` endpoint AND by `_run_task_agent()` for Dream Team coding tasks. Both get the same LangGraph agent, same tool registry, same model router.

2. **Single tool registry with no scoping.** `lib/agent/registry.py` loads ALL 11 skills into one pool:
   - Sabine personal: `get_calendar_events`, `create_calendar_event`, `get_custody_schedule`, `get_weather`, `create_reminder`, `cancel_reminder`, `list_reminders`
   - Dream Team coding: `github_issues`, `run_python_sandbox`, `sync_project_board`, `send_team_update`

3. **Memory retrieval bleeds across systems.** `retrieve_context()` pulls ALL memories for a user_id regardless of which agent created them.

### Phase 2 Target Architecture

```
lib/agent/
├── core.py            # MODIFIED — shared utilities only (LLM client, embedding, helpers)
├── sabine_agent.py    # NEW — Sabine conversational agent (personal tools only)
├── task_agent.py      # NEW — Dream Team task execution agent (coding tools only)
├── tool_sets.py       # NEW — Hard-coded tool set definitions
├── registry.py        # MODIFIED — add get_scoped_tools() for filtered loading
├── memory.py          # MODIFIED — add role parameter to ingest
├── retrieval.py       # MODIFIED — add role filter to retrieval
└── ... (other files unchanged)
```

### Phase 2 Constraints (Apply to ALL Batches)
- **Same response schemas.** Both `run_sabine_agent()` and `run_task_agent()` must return the same dict structure as current `run_agent()`.
- **No new dependencies.** Use existing LangGraph patterns.
- **Graceful deprecation.** `run_agent()` must remain importable and functional as a dispatcher.
- **Don't break the model router.** `model_router.py` should work with both agent types.
- **Memory migration must be backward-compatible.** Existing memories without a `role` field default to `"assistant"` in queries.

---

### Batch A: Objective

This is Batch A of a 4-batch refactor. Create the tool set definitions that will be used to scope tools per agent.

### Task

Create `lib/agent/tool_sets.py` with explicit, hard-coded tool set definitions:

```python
# lib/agent/tool_sets.py
"""
Hard-coded tool set definitions for agent isolation.
Sabine (conversational) and Dream Team (coding) agents get separate tool pools.
"""

from typing import Set

SABINE_PERSONAL_TOOLS: Set[str] = {
    "get_calendar_events",
    "create_calendar_event",
    "get_custody_schedule",
    "get_weather",
    "create_reminder",
    "cancel_reminder",
    "list_reminders",
}

DREAM_TEAM_CODING_TOOLS: Set[str] = {
    "github_issues",
    "run_python_sandbox",
    "sync_project_board",
    "send_team_update",
}

SHARED_TOOLS: Set[str] = set()  # Future: tools both systems need (e.g., web search)


def get_sabine_tools() -> Set[str]:
    """Return the full set of tool names available to Sabine's conversational agent."""
    return SABINE_PERSONAL_TOOLS | SHARED_TOOLS


def get_dream_team_tools() -> Set[str]:
    """Return the full set of tool names available to Dream Team coding agents."""
    return DREAM_TEAM_CODING_TOOLS | SHARED_TOOLS
```

Also modify `lib/agent/registry.py` to support scoped tool loading. Add a new function alongside the existing `get_all_tools()`:

```python
async def get_scoped_tools(allowed_names: set[str]) -> list[StructuredTool]:
    """Load all tools, then filter to only those whose names are in allowed_names."""
    all_tools = await get_all_tools()
    return [t for t in all_tools if t.name in allowed_names]
```

Do NOT modify or remove `get_all_tools()` — it's still used by other code.

### Verification

After completing, run this script to verify:

```python
import sys
sys.path.insert(0, '.')

from lib.agent.tool_sets import get_sabine_tools, get_dream_team_tools

sabine = get_sabine_tools()
dream_team = get_dream_team_tools()
overlap = sabine & dream_team

if overlap:
    print(f"FAIL: Tool overlap detected: {overlap}")
    sys.exit(1)
else:
    print(f"PASS: Zero tool overlap. Sabine: {len(sabine)} tools, Dream Team: {len(dream_team)} tools")

ALL_KNOWN_SKILLS = {
    "get_calendar_events", "create_calendar_event", "get_custody_schedule",
    "get_weather", "create_reminder", "cancel_reminder", "list_reminders",
    "github_issues", "run_python_sandbox", "sync_project_board", "send_team_update",
}
classified = sabine | dream_team
unclassified = ALL_KNOWN_SKILLS - classified
if unclassified:
    print(f"WARN: Unclassified skills: {unclassified}")
else:
    print(f"PASS: All {len(ALL_KNOWN_SKILLS)} skills classified into a tool set")
```

### Definition of Done
- `lib/agent/tool_sets.py` exists with the sets and helper functions
- `lib/agent/registry.py` has a new `get_scoped_tools()` function
- Both files pass `python -m py_compile`
- Verification script prints all PASS
- `get_all_tools()` is unchanged and still works

---

## BATCH B: Create Separate Agent Modules + Wire Routers

### Project Overview

Sabine Super Agent — a personal AI agent with a Python/FastAPI backend and Next.js frontend.

- **Backend:** Python 3.11+, FastAPI, Supabase (Postgres + pgvector)
- **AI/Agents:** LangChain/LangGraph, Pydantic v2
- **Coding rules:** All functions must have full type hints. Use Pydantic v2 `BaseModel` for schemas. Never swallow errors silently — use `logging`. Use lazy imports (inside functions) when importing between modules that reference each other to avoid circular dependencies. Run `python -m py_compile <file>` to syntax-check after edits.

### Architecture (Current State)

```
lib/agent/
├── core.py          # Agent orchestration — run_agent() at line ~1326, create_agent(),
│                    #   load_deep_context(), build_static_context(), build_dynamic_context(),
│                    #   load_role_manifest()
├── registry.py      # Tool registry — get_all_tools() loads ALL local skills + MCP tools
│                    #   load_local_skills() scans lib/skills/ for manifest.json + handler.py
│                    #   Now also has get_scoped_tools(allowed_names) [ADDED IN BATCH A]
├── tool_sets.py     # [ADDED IN BATCH A] — get_sabine_tools(), get_dream_team_tools()
├── retrieval.py     # Memory retrieval — retrieve_context() at line ~378
│                    #   Calls search_similar_memories() → supabase.rpc("match_memories")
│                    #   No role filtering
├── memory.py        # Memory ingestion — ingest_user_message() at line ~426
│                    #   Stores metadata: {user_id, source, timestamp, domain, original_content}
│                    #   No role field
├── models.py        # RoleManifest model at line ~13: role_id, title, instructions,
│                    #   allowed_tools (list, empty=all), model_preference
├── shared.py        # Shared models, constants, auth dependencies
├── llm_config.py    # LLM configuration
├── model_router.py  # Model selection logic
├── mcp_client.py    # MCP tool client
├── routers/
│   ├── sabine.py        # POST /invoke at line ~35 — calls run_agent() from core.py
│   ├── dream_team.py    # Task CRUD endpoints, role listing
│   ├── gmail.py         # Gmail push notifications
│   ├── memory.py        # Memory ingest/query/upload endpoints
│   └── observability.py # Logging/metrics endpoints
└── ...

server.py            # 726 lines — thin shell with router mounting
                     # Contains _run_task_agent(task) at line ~222
                     #   Calls run_agent() with role=task.role
                     #   Implements context propagation, repo context injection,
                     #   tool execution verification, retry logic, Slack updates
```

**The problem:** One `run_agent()` function serves both Sabine (conversational) and Dream Team (coding) agents. One tool registry gives every agent every tool. Memory retrieval has no role scoping.

### What's Wrong (Detail)

1. **Single run_agent() serves both systems.** `lib/agent/core.py` has one `run_agent()` function called by Sabine's `/invoke` endpoint AND by `_run_task_agent()` for Dream Team coding tasks. Both get the same LangGraph agent, same tool registry, same model router.

2. **Single tool registry with no scoping.** `lib/agent/registry.py` loads ALL 11 skills into one pool:
   - Sabine personal: `get_calendar_events`, `create_calendar_event`, `get_custody_schedule`, `get_weather`, `create_reminder`, `cancel_reminder`, `list_reminders`
   - Dream Team coding: `github_issues`, `run_python_sandbox`, `sync_project_board`, `send_team_update`

3. **Memory retrieval bleeds across systems.** `retrieve_context()` pulls ALL memories for a user_id regardless of which agent created them.

### Phase 2 Target Architecture

```
lib/agent/
├── core.py            # MODIFIED — shared utilities only (LLM client, embedding, helpers)
├── sabine_agent.py    # NEW — Sabine conversational agent (personal tools only)
├── task_agent.py      # NEW — Dream Team task execution agent (coding tools only)
├── tool_sets.py       # DONE (Batch A) — Hard-coded tool set definitions
├── registry.py        # DONE (Batch A) — has get_scoped_tools()
├── memory.py          # MODIFIED (Batch C) — add role parameter to ingest
├── retrieval.py       # MODIFIED (Batch C) — add role filter to retrieval
└── ... (other files unchanged)
```

### Phase 2 Constraints (Apply to ALL Batches)
- **Same response schemas.** Both `run_sabine_agent()` and `run_task_agent()` must return the same dict structure as current `run_agent()`.
- **No new dependencies.** Use existing LangGraph patterns.
- **Graceful deprecation.** `run_agent()` must remain importable and functional as a dispatcher.
- **Don't break the model router.** `model_router.py` should work with both agent types.
- **Memory migration must be backward-compatible.** Existing memories without a `role` field default to `"assistant"` in queries.

### What Batch A Completed
- `lib/agent/tool_sets.py` exists with `get_sabine_tools()` and `get_dream_team_tools()`
- `lib/agent/registry.py` has `get_scoped_tools(allowed_names)` for filtered tool loading
- Zero tool overlap verified

---

### Batch B: Objective

Create two separate agent modules and wire the routers to use them.

### Key Reference: Current `run_agent()` Signature and Return Value

```python
# lib/agent/core.py line ~1326
async def run_agent(
    user_id: str,
    session_id: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    use_caching: bool = False,
    role: Optional[str] = None
) -> Dict[str, Any]:
```

Returns:
```python
{
    "success": bool,
    "response": str,
    "user_id": str,
    "session_id": str,
    "timestamp": str,
    "deep_context_loaded": bool,
    "tools_available": int,
    "latency_ms": float,
    "cache_metrics": dict,
    "tool_execution": {"tools_called": list, ...},
    "role": Optional[str],
    "role_title": Optional[str],
}
```

### Tasks

#### Task B1: Extract a shared agent creation helper in `core.py`

Add a new helper function in `core.py` that both new agent modules will import:

```python
async def create_react_agent_with_tools(
    tools: list,
    system_prompt: str,
    model_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> CompiledGraph:
    """Create a LangGraph ReAct agent with the given tools and system prompt.

    This is the shared agent creation helper used by both sabine_agent.py and task_agent.py.
    """
    # Extract the LangGraph agent creation logic from the existing create_agent() function.
    # Use the existing model routing logic (model_router.py / llm_config.py).
    # Return the compiled LangGraph agent.
```

This should extract the LangGraph `create_react_agent` call and model client setup from the existing `create_agent()` function. Do NOT remove `create_agent()` yet — that happens in Batch D.

#### Task B2: Create `lib/agent/sabine_agent.py`

```python
async def run_sabine_agent(
    user_id: str,
    session_id: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    use_caching: bool = False,
) -> Dict[str, Any]:
    """Run the Sabine conversational agent with personal tools only."""
```

This function must:
1. Load ONLY Sabine tools: `await get_scoped_tools(get_sabine_tools())`
2. Load deep context: `await load_deep_context(user_id)` (import from core.py)
3. Build system prompt using `build_static_context()` and `build_dynamic_context()` (import from core.py)
4. Call `retrieve_context()` for memory-augmented context (import from retrieval.py)
5. Create the agent via `create_react_agent_with_tools()`
6. Return the **exact same response dict** as current `run_agent()` — keys: `success`, `response`, `user_id`, `session_id`, `timestamp`, `deep_context_loaded`, `tools_available`, `latency_ms`, `cache_metrics`, `tool_execution`, `role` (always None), `role_title` (always None)

Use lazy imports where needed to avoid circular dependencies (per CLAUDE.md).

#### Task B3: Create `lib/agent/task_agent.py`

```python
async def run_task_agent(
    user_id: str,
    session_id: str,
    user_message: str,
    role: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    use_caching: bool = False,
) -> Dict[str, Any]:
    """Run a Dream Team coding agent with coding tools only."""
```

This function must:
1. `role` parameter is **required** (not Optional)
2. Load the role manifest: `load_role_manifest(role)` (import from core.py)
3. Load ONLY Dream Team tools: `await get_scoped_tools(get_dream_team_tools())`
4. If the RoleManifest has non-empty `allowed_tools`, further filter the tool list (apply wildcard matching — existing RoleManifest supports patterns like `mcp_*`, `github_*`)
5. Does **NOT** call `retrieve_context()` — coding agents don't need Sabine's memories
6. Does **NOT** call `load_deep_context()` — coding agents don't need custody/calendar context. Build a minimal system prompt from the role manifest instructions instead.
7. Create the agent via `create_react_agent_with_tools()`
8. Return the **exact same response dict** as current `run_agent()`

#### Task B4: Update routers to use new agent functions

**`lib/agent/routers/sabine.py`:** Change the `/invoke` endpoint to call `run_sabine_agent()` instead of `run_agent()`. Import from `lib.agent.sabine_agent`. The endpoint currently passes `role` from the request body — for Sabine's `/invoke`, ignore any role parameter and always use `run_sabine_agent()`.

**`server.py` — Move `_run_task_agent()`:** Move the `_run_task_agent(task)` function (lines ~222-530) from `server.py` into `lib/agent/routers/dream_team.py` (or a new `lib/agent/task_runner.py` if the router file is too large). Update it to call `run_task_agent()` instead of `run_agent()`. Keep all existing logic: context propagation, repo context injection, tool execution verification, retry logic, Slack updates, audit logging.

### Verification

```python
import sys
sys.path.insert(0, '.')

# Verify imports work
try:
    from lib.agent.sabine_agent import run_sabine_agent
    from lib.agent.task_agent import run_task_agent
    print("PASS: Both agent modules import successfully")
except ImportError as e:
    print(f"FAIL: Import error: {e}")
    sys.exit(1)

# Verify run_agent backward compat still exists
try:
    from lib.agent.core import run_agent
    print("PASS: run_agent() still importable (backward compat)")
except ImportError:
    print(f"FAIL: run_agent() missing from core.py")
    sys.exit(1)

# Verify shared helper exists
try:
    from lib.agent.core import create_react_agent_with_tools
    print("PASS: create_react_agent_with_tools() importable")
except ImportError as e:
    print(f"FAIL: Shared helper missing: {e}")
    sys.exit(1)

# Verify tool_sets still works
from lib.agent.tool_sets import get_sabine_tools, get_dream_team_tools
sabine = get_sabine_tools()
dream_team = get_dream_team_tools()
overlap = sabine & dream_team
if overlap:
    print(f"FAIL: Tool overlap: {overlap}")
    sys.exit(1)
print(f"PASS: Tool sets intact. Sabine: {len(sabine)}, Dream Team: {len(dream_team)}")
```

Also run: `python run_server.py` and verify it starts without import errors (Ctrl+C after startup).

### Definition of Done
- `lib/agent/sabine_agent.py` exists with `run_sabine_agent()`
- `lib/agent/task_agent.py` exists with `run_task_agent()`
- `lib/agent/core.py` has `create_react_agent_with_tools()` shared helper
- `lib/agent/routers/sabine.py` calls `run_sabine_agent()` instead of `run_agent()`
- `_run_task_agent()` moved out of `server.py` and calls `run_task_agent()`
- All files pass `python -m py_compile`
- Verification script prints all PASS
- Server starts without import errors

---

## BATCH C: Memory Role Tagging + Filtered Retrieval

### Project Overview

Sabine Super Agent — a personal AI agent with a Python/FastAPI backend and Next.js frontend.

- **Backend:** Python 3.11+, FastAPI, Supabase (Postgres + pgvector)
- **AI/Agents:** LangChain/LangGraph, Pydantic v2
- **Coding rules:** All functions must have full type hints. Use Pydantic v2 `BaseModel` for schemas. Never swallow errors silently — use `logging`. Use lazy imports (inside functions) when importing between modules that reference each other to avoid circular dependencies. Run `python -m py_compile <file>` to syntax-check after edits.

### Architecture (Current State After Batches A+B)

```
lib/agent/
├── core.py            # Shared utilities — create_react_agent_with_tools(), load_deep_context(),
│                      #   build_static_context(), build_dynamic_context(), load_role_manifest()
│                      #   Still has run_agent() and create_agent() (to be cleaned up in Batch D)
├── sabine_agent.py    # [ADDED IN BATCH B] — run_sabine_agent() with personal tools only
├── task_agent.py      # [ADDED IN BATCH B] — run_task_agent() with coding tools only
├── tool_sets.py       # [ADDED IN BATCH A] — get_sabine_tools(), get_dream_team_tools()
├── registry.py        # [MODIFIED IN BATCH A] — get_all_tools() + get_scoped_tools()
├── retrieval.py       # Memory retrieval — retrieve_context() at line ~378
│                      #   Calls search_similar_memories() → supabase.rpc("match_memories")
│                      #   NO role filtering yet
├── memory.py          # Memory ingestion — ingest_user_message() at line ~426
│                      #   Stores metadata: {user_id, source, timestamp, domain, original_content}
│                      #   NO role field yet
├── models.py          # RoleManifest model at line ~13
├── shared.py          # Shared models, constants, auth dependencies
├── routers/
│   ├── sabine.py        # POST /invoke — now calls run_sabine_agent() [MODIFIED IN BATCH B]
│   ├── dream_team.py    # Task endpoints, now contains _run_task_agent() [MODIFIED IN BATCH B]
│   ├── gmail.py         # Gmail push notifications
│   ├── memory.py        # Memory ingest/query/upload endpoints
│   └── observability.py # Logging/metrics endpoints
└── ...

server.py              # Thin shell — _run_task_agent() moved out in Batch B
```

**The problem being solved in this batch:** Memory retrieval bleeds across systems. `retrieve_context()` pulls ALL memories for a user_id regardless of which agent created them. Coding agent task messages pollute Sabine's conversational context.

### Phase 2 Constraints (Apply to ALL Batches)
- **Same response schemas.** Both `run_sabine_agent()` and `run_task_agent()` must return the same dict structure as current `run_agent()`.
- **No new dependencies.** Use existing LangGraph patterns.
- **Graceful deprecation.** `run_agent()` must remain importable and functional as a dispatcher.
- **Don't break the model router.** `model_router.py` should work with both agent types.
- **Memory migration must be backward-compatible.** Existing memories without a `role` field default to `"assistant"` in queries.

### What Batches A+B Completed
- `lib/agent/tool_sets.py` — tool set definitions with zero overlap
- `lib/agent/registry.py` — `get_scoped_tools()` for filtered tool loading
- `lib/agent/sabine_agent.py` — `run_sabine_agent()` with personal tools only
- `lib/agent/task_agent.py` — `run_task_agent()` with coding tools only
- Routers updated to call the new agent functions
- `_run_task_agent()` moved from server.py into dream_team router

---

### Batch C: Objective

Add role tagging to memory ingestion and role filtering to memory retrieval, so Sabine's memory stream stays clean of coding agent content.

### Key Reference: Current Function Signatures

```python
# lib/agent/memory.py line ~426
async def ingest_user_message(
    user_id: UUID,
    content: str,
    source: str = "api"
) -> Dict[str, Any]:
    # Metadata stored: {"user_id", "source", "timestamp", "domain", "original_content"}
    # Calls store_memory() at line ~364 which passes metadata through to Supabase

# lib/agent/retrieval.py line ~378
async def retrieve_context(
    user_id: UUID,
    query: str,
    memory_threshold: float = DEFAULT_MEMORY_THRESHOLD,  # 0.6
    memory_limit: int = DEFAULT_MEMORY_COUNT,             # 5
    entity_limit: int = DEFAULT_ENTITY_LIMIT              # 10
) -> str:
    # Calls search_similar_memories() at line ~58
    # Which calls supabase.rpc("match_memories", {
    #     "query_embedding": pgvector_embedding,
    #     "match_threshold": threshold,
    #     "match_count": limit,
    #     "user_id_filter": str(user_id)
    # })
```

### Tasks

#### Task C1: Add role parameter to memory ingestion

Modify `ingest_user_message()` in `lib/agent/memory.py`:

```python
async def ingest_user_message(
    user_id: UUID,
    content: str,
    source: str = "api",
    role: str = "assistant",  # NEW PARAMETER
) -> Dict[str, Any]:
```

Add `role` to the metadata dict that gets stored: `metadata["role"] = role`

This is the only change needed in memory.py. The `store_memory()` function (line ~364) already passes metadata through to Supabase — it will include the new field automatically.

#### Task C2: Update callers to pass role

**`lib/agent/routers/sabine.py`:** The `/invoke` endpoint already calls `ingest_user_message()`. Add `role="assistant"` explicitly to the call (even though it's the default — be explicit).

**Dream Team task path:** In the moved `_run_task_agent()` function (now in `routers/dream_team.py` or `task_runner.py`), either:
- **Option A (preferred):** Skip memory ingestion entirely for coding agents. If `ingest_user_message()` is called during task execution, don't call it. Coding agent task content should NOT enter the memory stream.
- **Option B:** If memory ingestion is called, pass `role=task.role` (e.g., `role="backend-architect-sabine"`).

Check if `run_task_agent()` or any code in the task execution path calls `ingest_user_message()`. If it does, apply Option A or B. If it doesn't, no changes needed here.

#### Task C3: Add role filter to memory retrieval

Modify `retrieve_context()` in `lib/agent/retrieval.py`:

```python
async def retrieve_context(
    user_id: UUID,
    query: str,
    memory_threshold: float = DEFAULT_MEMORY_THRESHOLD,
    memory_limit: int = DEFAULT_MEMORY_COUNT,
    entity_limit: int = DEFAULT_ENTITY_LIMIT,
    role_filter: Optional[str] = "assistant",  # NEW PARAMETER
) -> str:
```

Modify `search_similar_memories()` to accept and pass `role_filter` to the `match_memories` RPC call.

#### Task C4: Create SQL migration for `match_memories` RPC

Create a new SQL migration file at `supabase/migrations/YYYYMMDD_add_role_filter_to_match_memories.sql`.

The migration must:
1. Add an optional `role_filter` parameter to the `match_memories` function
2. When `role_filter` is NOT NULL, filter results to only memories where `metadata->>'role' = role_filter` OR `metadata->>'role' IS NULL` (backward compat — old memories without a role field should still be returned for Sabine)
3. When `role_filter` IS NULL, return all memories (no filtering — backward compat for any other callers)

Example SQL pattern:
```sql
CREATE OR REPLACE FUNCTION match_memories(
    query_embedding vector(1536),
    match_threshold float,
    match_count int,
    user_id_filter uuid DEFAULT NULL,
    role_filter text DEFAULT NULL  -- NEW
)
RETURNS TABLE(...) AS $$
BEGIN
    RETURN QUERY
    SELECT ...
    FROM memories
    WHERE ...
        AND (role_filter IS NULL OR metadata->>'role' = role_filter OR metadata->>'role' IS NULL)
    ORDER BY similarity DESC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;
```

**Important:** Look at the existing `match_memories` function signature (check `supabase/migrations/` for the original) to get the exact column list and return type. Don't guess.

### Verification

```python
import sys, inspect
sys.path.insert(0, '.')

# Verify ingest_user_message accepts role parameter
from lib.agent.memory import ingest_user_message
sig = inspect.signature(ingest_user_message)
if 'role' in sig.parameters:
    default = sig.parameters['role'].default
    if default == "assistant":
        print(f"PASS: ingest_user_message() has role param with default='assistant'")
    else:
        print(f"FAIL: role default is '{default}', expected 'assistant'")
        sys.exit(1)
else:
    print("FAIL: ingest_user_message() missing role parameter")
    sys.exit(1)

# Verify retrieve_context accepts role_filter parameter
from lib.agent.retrieval import retrieve_context
sig = inspect.signature(retrieve_context)
if 'role_filter' in sig.parameters:
    default = sig.parameters['role_filter'].default
    if default == "assistant":
        print(f"PASS: retrieve_context() has role_filter param with default='assistant'")
    else:
        print(f"FAIL: role_filter default is '{default}', expected 'assistant'")
        sys.exit(1)
else:
    print("FAIL: retrieve_context() missing role_filter parameter")
    sys.exit(1)

# Verify SQL migration exists
import glob
migrations = glob.glob("supabase/migrations/*role_filter*")
if migrations:
    print(f"PASS: SQL migration found: {migrations[0]}")
else:
    print("FAIL: No SQL migration for role_filter found")
    sys.exit(1)
```

Also verify: `python -m py_compile lib/agent/memory.py && python -m py_compile lib/agent/retrieval.py`

### Definition of Done
- `ingest_user_message()` accepts `role` parameter (default `"assistant"`)
- `role` is stored in memory metadata
- `retrieve_context()` accepts `role_filter` parameter (default `"assistant"`)
- `search_similar_memories()` passes role filter to `match_memories` RPC
- SQL migration exists and is backward-compatible
- Coding agent task output does not enter Sabine's memory stream
- All files pass `python -m py_compile`
- Verification script prints all PASS

---

## BATCH D: Clean Up core.py + Full Verification

### Project Overview

Sabine Super Agent — a personal AI agent with a Python/FastAPI backend and Next.js frontend.

- **Backend:** Python 3.11+, FastAPI, Supabase (Postgres + pgvector)
- **AI/Agents:** LangChain/LangGraph, Pydantic v2
- **Coding rules:** All functions must have full type hints. Use Pydantic v2 `BaseModel` for schemas. Never swallow errors silently — use `logging`. Use lazy imports (inside functions) when importing between modules that reference each other to avoid circular dependencies. Run `python -m py_compile <file>` to syntax-check after edits.

### Architecture (Current State After Batches A+B+C)

```
lib/agent/
├── core.py            # Shared utilities — create_react_agent_with_tools(), load_deep_context(),
│                      #   build_static_context(), build_dynamic_context(), load_role_manifest()
│                      #   STILL HAS old run_agent() body and create_agent() — to be cleaned up now
├── sabine_agent.py    # [BATCH B] — run_sabine_agent() with personal tools only
├── task_agent.py      # [BATCH B] — run_task_agent() with coding tools only
├── tool_sets.py       # [BATCH A] — get_sabine_tools(), get_dream_team_tools()
├── registry.py        # [BATCH A] — get_all_tools() + get_scoped_tools()
├── retrieval.py       # [BATCH C] — retrieve_context() now has role_filter param
├── memory.py          # [BATCH C] — ingest_user_message() now has role param
├── models.py          # RoleManifest model at line ~13
├── shared.py          # Shared models, constants, auth dependencies
├── routers/
│   ├── sabine.py        # POST /invoke — calls run_sabine_agent()
│   ├── dream_team.py    # Task endpoints + _run_task_agent() — calls run_task_agent()
│   ├── gmail.py         # Gmail push notifications
│   ├── memory.py        # Memory ingest/query/upload endpoints
│   └── observability.py # Logging/metrics endpoints
└── ...

server.py              # Thin shell — routers mounted, startup/shutdown events
```

### Phase 2 Constraints (Apply to ALL Batches)
- **Same response schemas.** Both `run_sabine_agent()` and `run_task_agent()` must return the same dict structure as current `run_agent()`.
- **No new dependencies.** Use existing LangGraph patterns.
- **Graceful deprecation.** `run_agent()` must remain importable and functional as a dispatcher.
- **Don't break the model router.** `model_router.py` should work with both agent types.
- **Memory migration must be backward-compatible.** Existing memories without a `role` field default to `"assistant"` in queries.

### What Batches A+B+C Completed
- `lib/agent/tool_sets.py` — tool set definitions with zero overlap
- `lib/agent/registry.py` — `get_scoped_tools()` for filtered tool loading
- `lib/agent/sabine_agent.py` — `run_sabine_agent()` with personal tools only
- `lib/agent/task_agent.py` — `run_task_agent()` with coding tools only
- Routers updated to call the new agent functions
- `_run_task_agent()` moved from server.py into dream_team router
- Memory ingestion has `role` parameter (default `"assistant"`)
- Memory retrieval has `role_filter` parameter (default `"assistant"`)
- SQL migration for `match_memories` role filter

---

### Batch D: Objective

Clean up `core.py` by replacing the monolithic `run_agent()` with a thin deprecation dispatcher, and run full verification of the entire Phase 2 refactor.

### Tasks

#### Task D1: Deprecate `run_agent()` as a thin dispatcher

Do NOT delete `run_agent()`. Convert it to a thin dispatcher that routes to the correct new function:

```python
async def run_agent(
    user_id: str,
    session_id: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    use_caching: bool = False,
    role: Optional[str] = None
) -> Dict[str, Any]:
    """DEPRECATED: Use run_sabine_agent() or run_task_agent() directly.

    Dispatches to the appropriate agent based on the role parameter.
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(
        "run_agent() is deprecated. Use run_sabine_agent() or run_task_agent() directly. "
        "Called with role=%s", role
    )

    if role:
        from lib.agent.task_agent import run_task_agent
        return await run_task_agent(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            role=role,
            conversation_history=conversation_history,
            use_caching=use_caching,
        )
    else:
        from lib.agent.sabine_agent import run_sabine_agent
        return await run_sabine_agent(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            conversation_history=conversation_history,
            use_caching=use_caching,
        )
```

#### Task D2: Clean up `core.py`

- Remove the old body of `run_agent()` (replaced by dispatcher above)
- Remove `create_agent()` if nothing else imports it (check all imports across the codebase first with `grep -r "create_agent" lib/`). If other code uses it, leave it but add a deprecation warning.
- Keep all shared helpers: `create_react_agent_with_tools()`, `load_deep_context()`, `build_static_context()`, `build_dynamic_context()`, `load_role_manifest()`, `get_available_roles()`
- Keep all other utilities (embedding, model routing, etc.)
- The goal is to make `core.py` a library of shared utilities, not an agent execution engine.

#### Task D3: Verify no remaining direct callers

Search the entire codebase for any remaining callers of `run_agent()` that should be updated:
```
grep -rn "run_agent(" lib/ server.py src/
```

Any callers found should either:
- Be updated to call `run_sabine_agent()` or `run_task_agent()` directly
- Or be left as-is if they're edge cases that the dispatcher handles correctly

#### Task D4: Run full verification suite

Create `verify_agent_separation.py` in the project root:

```python
"""Full verification of Phase 2: Agent Separation."""
import sys, asyncio, inspect
sys.path.insert(0, '.')

errors = []

# 1. Tool set isolation
from lib.agent.tool_sets import get_sabine_tools, get_dream_team_tools
sabine = get_sabine_tools()
dream_team = get_dream_team_tools()
overlap = sabine & dream_team
if overlap:
    errors.append(f"Tool overlap detected: {overlap}")
    print(f"FAIL: Tool overlap: {overlap}")
else:
    print(f"PASS: Zero tool overlap. Sabine: {len(sabine)}, Dream Team: {len(dream_team)}")

ALL_KNOWN_SKILLS = {
    "get_calendar_events", "create_calendar_event", "get_custody_schedule",
    "get_weather", "create_reminder", "cancel_reminder", "list_reminders",
    "github_issues", "run_python_sandbox", "sync_project_board", "send_team_update",
}
unclassified = ALL_KNOWN_SKILLS - (sabine | dream_team)
if unclassified:
    print(f"WARN: Unclassified skills: {unclassified}")
else:
    print(f"PASS: All {len(ALL_KNOWN_SKILLS)} skills classified")

# 2. Agent module imports
try:
    from lib.agent.sabine_agent import run_sabine_agent
    from lib.agent.task_agent import run_task_agent
    print("PASS: Both agent modules import successfully")
except ImportError as e:
    errors.append(f"Import error: {e}")
    print(f"FAIL: Import error: {e}")

# 3. Backward compat
try:
    from lib.agent.core import run_agent
    print("PASS: run_agent() still importable (backward compat)")
except ImportError:
    print("WARN: run_agent() removed — check all callers are updated")

# 4. Shared helper exists
try:
    from lib.agent.core import create_react_agent_with_tools
    print("PASS: create_react_agent_with_tools() importable")
except ImportError as e:
    errors.append(f"Shared helper missing: {e}")
    print(f"FAIL: Shared helper missing: {e}")

# 5. Memory role parameter
from lib.agent.memory import ingest_user_message
sig = inspect.signature(ingest_user_message)
if 'role' in sig.parameters and sig.parameters['role'].default == "assistant":
    print("PASS: ingest_user_message() has role param (default='assistant')")
else:
    errors.append("ingest_user_message() missing or bad role param")
    print("FAIL: ingest_user_message() role param issue")

# 6. Retrieval role filter
from lib.agent.retrieval import retrieve_context
sig = inspect.signature(retrieve_context)
if 'role_filter' in sig.parameters and sig.parameters['role_filter'].default == "assistant":
    print("PASS: retrieve_context() has role_filter param (default='assistant')")
else:
    errors.append("retrieve_context() missing or bad role_filter param")
    print("FAIL: retrieve_context() role_filter param issue")

# 7. SQL migration
import glob
migrations = glob.glob("supabase/migrations/*role_filter*")
if migrations:
    print(f"PASS: SQL migration found: {migrations[0]}")
else:
    errors.append("No SQL migration for role_filter")
    print("FAIL: No SQL migration found")

# 8. Function signatures match expected contract
sabine_sig = inspect.signature(run_sabine_agent)
task_sig = inspect.signature(run_task_agent)

sabine_params = set(sabine_sig.parameters.keys())
task_params = set(task_sig.parameters.keys())

expected_sabine = {"user_id", "session_id", "user_message", "conversation_history", "use_caching"}
expected_task = {"user_id", "session_id", "user_message", "role", "conversation_history", "use_caching"}

if sabine_params >= expected_sabine:
    print(f"PASS: run_sabine_agent() has expected parameters")
else:
    missing = expected_sabine - sabine_params
    errors.append(f"run_sabine_agent() missing params: {missing}")
    print(f"FAIL: run_sabine_agent() missing: {missing}")

if task_params >= expected_task:
    print(f"PASS: run_task_agent() has expected parameters")
else:
    missing = expected_task - task_params
    errors.append(f"run_task_agent() missing params: {missing}")
    print(f"FAIL: run_task_agent() missing: {missing}")

# Verify 'role' is required in run_task_agent (no default)
role_param = task_sig.parameters.get('role')
if role_param and role_param.default is inspect.Parameter.empty:
    print("PASS: run_task_agent() role param is required (no default)")
else:
    errors.append("run_task_agent() role should be required")
    print("FAIL: run_task_agent() role should be required (no default)")

# Summary
print("\n" + "=" * 50)
if errors:
    print(f"FAILED: {len(errors)} error(s)")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED - Phase 2 agent separation verified!")
    sys.exit(0)
```

### Definition of Done (Full Phase 2)
- [ ] Verification script (`verify_agent_separation.py`) prints ALL PASS
- [ ] `python run_server.py` starts without errors
- [ ] `POST /invoke` works with Sabine-only tools
- [ ] Task dispatch works with Dream Team-only tools
- [ ] `run_agent()` still works as a backward-compatible dispatcher
- [ ] Memory ingestion tags role correctly
- [ ] Sabine memory retrieval excludes coding agent memories
- [ ] No Python import errors anywhere in the codebase
- [ ] All modified files pass `python -m py_compile`

---

## Quick Reference

| Batch | Files Created/Modified | Risk Level | Estimated Scope |
|-------|----------------------|------------|-----------------|
| A | `tool_sets.py` (new), `registry.py` (minor add) | Low | Small |
| B | `sabine_agent.py` (new), `task_agent.py` (new), `core.py` (add helper), `routers/sabine.py`, `server.py` or `routers/dream_team.py` | Medium | Large |
| C | `memory.py`, `retrieval.py`, `routers/sabine.py`, SQL migration | Medium | Medium |
| D | `core.py` (cleanup), `verify_agent_separation.py` (new) | High | Medium |
