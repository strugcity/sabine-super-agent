# Task Execution Flow Investigation

**Date:** 2026-02-06  
**Issue:** Find where `in_progress` tasks are actually executed  
**Purpose:** Diagnose why tasks stall after being acknowledged but don't complete

## Executive Summary

Tasks in Sabine Super Agent follow an **event-driven auto-dispatch** model where:
- Tasks are **NOT** automatically picked up by a background worker
- Tasks transition to `in_progress` only when **explicitly dispatched**
- Execution happens in the **FastAPI server process** via background tasks
- The initial dispatch **MUST** be triggered manually via `/tasks/dispatch` endpoint

**Critical Finding:** There is NO automatic polling or worker process that picks up newly created tasks. Tasks sit in `queued` status until someone/something calls the `/tasks/dispatch` endpoint.

## Answers to Key Questions

### 1. How does a task get picked up and executed?

Tasks are picked up through a **manual dispatch** process:

1. **Task Creation** (`POST /tasks`)
   - Creates task with status `queued`
   - Stores in `task_queue` table in Supabase
   - Returns immediately - **does not execute task**

2. **Manual Dispatch Required** (`POST /tasks/dispatch`)
   - Must be explicitly called by an external system (Mission Control, cron job, etc.)
   - Claims unblocked tasks atomically using PostgreSQL `FOR UPDATE SKIP LOCKED`
   - Transitions tasks from `queued` → `in_progress`
   - Schedules execution in FastAPI background tasks

3. **Task Execution**
   - Runs in FastAPI process via `BackgroundTasks`
   - Calls `_run_task_agent()` which invokes the appropriate agent
   - Agent executes the task with the specified role

4. **Auto-Dispatch Chain** (ONLY after completion)
   - When a task completes, it triggers `_auto_dispatch()`
   - Finds dependent tasks whose dependencies are now met
   - Automatically dispatches those dependent tasks
   - Creates a chain reaction for dependent task execution

**Key Insight:** The **first task** in a chain will NOT execute automatically. Something external must call `/tasks/dispatch` to start the chain.

### 2. Is there a separate worker process, or does the FastAPI server execute tasks?

**Answer:** The **FastAPI server executes tasks** in its own process.

- **No separate worker process** (no Celery, no background daemon)
- Uses FastAPI's `BackgroundTasks` for async execution
- Tasks run in the same Python process as the web server
- Execution happens via: `background_tasks.add_task(_run_task_agent, task)`

**Implications:**
- If the FastAPI server is not running, tasks cannot execute
- Server restart interrupts in-progress tasks (no persistence of execution state)
- Concurrent task execution limited by server resources

### 3. Where does the orchestration actually *call* the SABINE_ARCHITECT agent?

The call stack for SABINE_ARCHITECT execution:

```
1. POST /tasks/dispatch (lib/agent/server.py:1742)
   ├─> claim_unblocked_tasks_atomic() (backend/services/task_queue.py)
   │   └─> Claims tasks with status=queued, no blocking dependencies
   │       Changes status: queued → in_progress
   │
   └─> background_tasks.add_task(_run_task_agent, task)
       │
       ├─> _run_task_agent(task) (lib/agent/server.py:2031)
       │   ├─> Extract message from task.payload
       │   ├─> Fetch parent task context (dependencies)
       │   ├─> Inject repository targeting context
       │   ├─> send_task_update() to Slack ("task_started")
       │   │
       │   └─> run_agent() (lib/agent/core.py)
       │       └─> Executes agent with role="SABINE_ARCHITECT"
       │           └─> Agent performs actual work
       │
       └─> On completion:
           └─> complete_task() (backend/services/task_queue.py)
               └─> _auto_dispatch() triggers dependent tasks
```

**File Locations:**
- **Dispatch Endpoint:** `lib/agent/server.py:1742` (`POST /tasks/dispatch`)
- **Agent Runner:** `lib/agent/server.py:2031` (`_run_task_agent`)
- **Agent Core:** `lib/agent/core.py` (`run_agent` function)
- **Task Queue Service:** `backend/services/task_queue.py` (`TaskQueueService`)

## Task Lifecycle State Transitions

```
                    ┌─────────────────────────────────────┐
                    │   POST /tasks (create_task)         │
                    │   Creates task in Supabase          │
                    └──────────────┬──────────────────────┘
                                   │
                                   v
                            ┌─────────────┐
                            │   queued    │
                            └──────┬──────┘
                                   │
                                   │ ⚠️  MANUAL TRIGGER REQUIRED ⚠️
                                   │  
                                   │  WHO SHOULD CALL /tasks/dispatch?
                                   │  Currently: NOTHING AUTOMATIC
                                   │
                                   v
                    ┌──────────────────────────────────────┐
                    │  POST /tasks/dispatch                 │
                    │  - claim_unblocked_tasks_atomic()     │
                    │  - Claims with FOR UPDATE SKIP LOCKED │
                    └──────────────┬───────────────────────┘
                                   │
                                   v
                            ┌──────────────┐
                            │ in_progress  │ ← Task is now CLAIMED
                            └──────┬───────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    v                             v
            ┌──────────────┐            ┌──────────────┐
            │  completed   │            │   failed     │
            └──────┬───────┘            └──────┬───────┘
                   │                           │
                   │ Triggers _auto_dispatch() │
                   │ (for dependent tasks)     │
                   └───────────┬───────────────┘
                               │
                               v
                    ┌──────────────────────────┐
                    │ Find dependent tasks     │
                    │ whose dependencies met   │
                    │ → Auto-dispatch them     │
                    └──────────────────────────┘
```

**Key Problem:** The transition from `queued` → `in_progress` requires external intervention.
Tasks will sit in `queued` status indefinitely until something calls `/tasks/dispatch`.

## Task Execution Flow Diagram

```
  ┌─────────────┐
  │ Mission     │  ⚠️ Should exist but NOT FOUND
  │ Control UI  │  Should call /tasks/dispatch
  └──────┬──────┘  when user creates task
         │
         │ ❌ Missing automatic dispatch
         │
         v
  ┌──────────────────────────────────────────────────┐
  │ FastAPI Server (lib/agent/server.py)             │
  │                                                   │
  │  POST /tasks/dispatch                            │
  │  ├─> claim_unblocked_tasks_atomic()              │
  │  │   └─> SELECT ... FOR UPDATE SKIP LOCKED       │
  │  │       (Atomic claim in PostgreSQL)            │
  │  │                                                │
  │  └─> background_tasks.add_task(_run_task_agent)  │
  │      ├─> Extract message from payload            │
  │      ├─> Fetch parent task context               │
  │      ├─> Send task_started to Slack              │
  │      │                                            │
  │      └─> run_agent(role="SABINE_ARCHITECT")      │
  │          ├─> Build context with tools            │
  │          ├─> Stream to Anthropic Claude API      │
  │          └─> Execute tool calls                  │
  │              (github_issues, file ops, etc.)     │
  │                                                   │
  │  On Success:                                     │
  │  └─> complete_task()                             │
  │      └─> _auto_dispatch()                        │
  │          └─> Find & dispatch dependent tasks     │
  │                                                   │
  └───────────────────────────────────────────────────┘
```

## Critical Code Locations

### 1. Task Claiming (queued → in_progress)

**File:** `backend/services/task_queue.py`

```python
async def claim_task(self, task_id: UUID) -> bool:
    """
    Claim a task by setting its status to 'in_progress'.
    Line ~293
    """
```

**Atomic Claiming** (prevents race conditions):
```python
async def claim_unblocked_tasks_atomic(self, max_tasks: int = 10):
    """
    Atomically claim unblocked tasks using FOR UPDATE SKIP LOCKED.
    Line ~360
    """
```

### 2. Task Dispatch Endpoint

**File:** `lib/agent/server.py`

```python
@app.post("/tasks/dispatch")
async def dispatch_tasks(
    background_tasks: BackgroundTasks,
    max_tasks: int = 10,
    _: bool = Depends(verify_api_key)
):
    """
    Manually trigger dispatch of all unblocked tasks.
    Line 1742
    """
    claimed_tasks = await service.claim_unblocked_tasks_atomic(max_tasks=max_tasks)
    
    for task in claimed_tasks:
        background_tasks.add_task(_run_task_agent, task)
```

### 3. Agent Execution

**File:** `lib/agent/server.py`

```python
async def _run_task_agent(task: Task):
    """
    Run the agent for a task.
    
    Extracts the message from payload and runs the appropriate agent.
    Sends real-time updates to Slack (threaded by task).
    
    Line 2031
    """
    # Extract message and context
    message = task.payload.get("message") or task.payload.get("objective") or ...
    
    # Fetch parent task results for context
    if task.depends_on:
        # Build parent_context from completed dependencies
    
    # Run the agent
    result = await run_agent(
        user_id=user_id,
        session_id=f"task-{task.id}",
        user_message=full_message,
        role=task.role  # e.g., "SABINE_ARCHITECT"
    )
```

### 4. Auto-Dispatch Mechanism

**File:** `backend/services/task_queue.py`

```python
async def _auto_dispatch(self):
    """
    Automatically dispatch tasks whose dependencies are now met.
    
    This is called after a task completes to trigger the "Agent Handshake".
    
    Line 972
    """
    if not self._dispatch_callback:
        logger.debug("No dispatch callback set, skipping auto-dispatch")
        return
    
    unblocked = await self.get_unblocked_tasks()
    
    for task in unblocked:
        await self._dispatch_callback(task)  # Calls _dispatch_task
```

**Callback Setup:**
```python
# In lib/agent/server.py
service.set_dispatch_callback(_dispatch_task)

async def _dispatch_task(task: Task):
    """
    Dispatch callback for auto-dispatch after task completion.
    Line 2003
    """
    claim_result = await service.claim_task_result(task.id)
    
    if claim_result.success:
        await _run_task_agent(task)
```

## The Missing Link: Who Calls `/tasks/dispatch`?

This is the **critical question** for debugging the stalled task issue.

### Current State: NO AUTOMATIC DISPATCH FOUND ⚠️

After thorough investigation:
- ❌ No background worker process
- ❌ No cron job in Railway configuration
- ❌ No scheduled task in `startup_event()`
- ❌ No frontend auto-dispatch polling
- ✅ Only manual script exists: `trigger_dispatch.py` (for manual testing)

### Expected Callers:

1. **Mission Control UI** ⚠️ NOT FOUND
   - Should have a button or automatic trigger to dispatch tasks
   - No frontend code found that calls `/tasks/dispatch`
   - **This is likely the root cause of the issue**

2. **Scheduled Job (Cron/Railway)** ⚠️ NOT FOUND
   - No cron configuration found in `railway.json` or deployment files
   - No scheduled task in server startup

3. **Manual Script** ✅ EXISTS
   - `trigger_dispatch.py` can be run manually
   - Hardcoded API key (should be in env var)
   - Only for testing, not production use

4. **Watchdog Service** ⚠️ LIMITED
   - There is a `/tasks/watchdog` endpoint (line 1273) that handles stuck tasks
   - Requeues stuck `in_progress` tasks but does NOT dispatch `queued` tasks
   - Must also be called manually

### Investigating the Stalled Task (562c4fe8-fef0-4695-af5b-87f6eea02c85)

Based on the image showing task events:

```
Event 1: task_started - 2026-02-06 19:15:38.722614+00
Event 2: task_failed  - 2026-02-06 19:15:44.111533+00  
         "Task permanently failed: Err..."
Event 3: task_started - 2026-02-06 19:18:18.941342+00
```

**Analysis:**

1. **First Attempt (19:15:38)**: Task was dispatched and started
   - Status changed: `queued` → `in_progress`
   - Agent began execution
   - `task_started` event sent to Slack

2. **First Failure (19:15:44)**: Task failed after 6 seconds
   - `task_failed` event sent
   - Something went wrong during execution
   - Error message truncated in image

3. **Second Attempt (19:18:18)**: Task restarted
   - Retry mechanism kicked in (3 minutes later)
   - Task dispatched again
   - `task_started` event sent
   - **No completion or failure event after this** → Task likely still stuck

**Root Causes to Investigate:**

1. **Why did the first attempt fail so quickly?**
   - Check error logs in Railway for timestamp 19:15:44
   - Look for exception traces in task execution
   - Could be: Tool execution error, API timeout, permission issue

2. **Why did the second attempt appear to stall?**
   - No `task_completed` or `task_failed` event
   - Task might still be `in_progress` in database
   - Agent process may have:
     - Crashed without logging error
     - Hit infinite loop
     - Waiting for tool response that never came
     - Lost connection to Slack (no status updates)

3. **Who triggered the dispatch?**
   - Was `/tasks/dispatch` called manually?
   - Was this from a dependency chain (auto-dispatch)?
   - Check if task had parent dependencies

**To Debug:**

```sql
-- Check final task status
SELECT 
  id, role, status, created_at, started_at, completed_at,
  error, retry_count, max_retries,
  extract(epoch from (completed_at - started_at)) as duration_seconds
FROM task_queue
WHERE id = '562c4fe8-fef0-4695-af5b-87f6eea02c85';

-- Check if task had dependencies
SELECT depends_on, payload
FROM task_queue
WHERE id = '562c4fe8-fef0-4695-af5b-87f6eea02c85';

-- Check tool execution audit logs
SELECT created_at, tool_name, status, error_message
FROM tool_audit_logs
WHERE task_id = '562c4fe8-fef0-4695-af5b-87f6eea02c85'
ORDER BY created_at;
```

**Likely Scenario:**

Based on the pattern (quick failure, then retry, then silence), the most likely cause is:
- First attempt: Agent tried to execute but encountered an error (possibly tool execution failure)
- Retry mechanism kicked in automatically
- Second attempt: Same error occurred, but this time the error handling failed to log it properly
- Task stuck in `in_progress` state with no completion signal

**Prevention:**
- Add timeout enforcement on agent execution
- Improve error handling to always log failures
- Add heartbeat mechanism during long-running operations
- Implement automatic task dispatch (see recommendations below)

## Recommendations

### 🔥 URGENT: Fix #1 - Add Automatic Task Polling (CRITICAL)

**Problem:** Tasks sit in `queued` status forever because nothing automatically calls `/tasks/dispatch`.

**Solution:** Add a background polling loop that periodically dispatches tasks.

**Implementation Option A - Simple Async Loop (Recommended for MVP):**

```python
# In lib/agent/server.py, modify @app.on_event("startup")

@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    # ... existing startup code ...
    
    # Start automatic task dispatcher
    try:
        asyncio.create_task(task_dispatcher_loop())
        logger.info("✓ Automatic task dispatcher started (polling every 30s)")
    except Exception as e:
        logger.error(f"Failed to start task dispatcher: {e}")


async def task_dispatcher_loop():
    """
    Background loop to automatically dispatch queued tasks.
    
    Runs every 30 seconds to check for unblocked tasks and dispatch them.
    This ensures tasks don't sit in 'queued' status forever.
    """
    await asyncio.sleep(10)  # Wait for server to fully start
    
    while True:
        try:
            service = get_task_queue_service()
            
            # Set up dispatch callback if not already set
            if not service._dispatch_callback:
                service.set_dispatch_callback(_dispatch_task)
            
            # Claim and dispatch up to 5 unblocked tasks
            claimed_tasks = await service.claim_unblocked_tasks_atomic(max_tasks=5)
            
            if claimed_tasks:
                logger.info(f"Auto-dispatch: Dispatched {len(claimed_tasks)} tasks")
                
                for task in claimed_tasks:
                    # Create async task to run agent (don't block the loop)
                    asyncio.create_task(_run_task_agent(task))
            
        except Exception as e:
            logger.error(f"Error in task dispatcher loop: {e}")
        
        # Check every 30 seconds
        await asyncio.sleep(30)
```

**Implementation Option B - Using APScheduler (More Robust):**

```python
# In lib/agent/server.py startup_event()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# In startup_event(), add:
try:
    task_scheduler = AsyncIOScheduler()
    task_scheduler.add_job(
        dispatch_queued_tasks,
        trigger=IntervalTrigger(seconds=30),
        id='auto_task_dispatcher',
        name='Automatic Task Dispatcher',
        replace_existing=True
    )
    task_scheduler.start()
    logger.info("✓ Automatic task dispatcher started (APScheduler)")
except Exception as e:
    logger.error(f"Failed to start task dispatcher: {e}")


async def dispatch_queued_tasks():
    """Scheduled job to dispatch queued tasks."""
    try:
        service = get_task_queue_service()
        
        if not service._dispatch_callback:
            service.set_dispatch_callback(_dispatch_task)
        
        claimed_tasks = await service.claim_unblocked_tasks_atomic(max_tasks=5)
        
        for task in claimed_tasks:
            asyncio.create_task(_run_task_agent(task))
            
        if claimed_tasks:
            logger.info(f"Auto-dispatch: {len(claimed_tasks)} tasks")
            
    except Exception as e:
        logger.error(f"Error in scheduled task dispatch: {e}")
```

**Why This Fixes the Issue:**
- ✅ Tasks automatically picked up within 30 seconds of being created
- ✅ No manual `/tasks/dispatch` call needed
- ✅ Handles server restarts gracefully (picks up queued tasks on startup)
- ✅ Works with dependency chains (auto-dispatch still triggers after completion)

### 2. Improve Task Monitoring & Observability

**Add Metrics to Track:**
```python
# Add to lib/agent/server.py

@app.get("/metrics/tasks")
async def get_task_metrics(_: bool = Depends(verify_api_key)):
    """Get task queue health metrics."""
    service = get_task_queue_service()
    
    # Get status counts
    counts = await service.get_status_counts()
    
    # Get stale queued tasks (sitting for >5 minutes)
    stale_tasks = await service.get_stale_queued_tasks(threshold_minutes=5)
    
    # Get stuck in_progress tasks (no heartbeat in 10 minutes)
    stuck_tasks = await service.get_stuck_tasks(threshold_minutes=10)
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "health": {
            "stale_queued_count": len(stale_tasks),
            "stuck_in_progress_count": len(stuck_tasks),
            "stale_tasks": [
                {
                    "id": str(t.id),
                    "role": t.role,
                    "queued_duration_minutes": (datetime.now(timezone.utc) - t.created_at).total_seconds() / 60
                }
                for t in stale_tasks[:5]  # Show top 5
            ]
        }
    }
```

**Add Dashboard Widget:**
```typescript
// In src/components/TaskQueueDashboard.tsx

async function fetchTaskMetrics() {
  const response = await fetch('/api/metrics/tasks', {
    headers: { 'X-API-Key': apiKey }
  });
  return response.json();
}

// Display alerts for:
// - Tasks queued for >10 minutes
// - Tasks in_progress with no heartbeat for >15 minutes
// - Failed tasks in last hour
```

### 3. Add Task Timeout Enforcement

Ensure tasks are automatically failed if they exceed timeout:

```python
# Enhance the watchdog to check timeouts

@app.post("/tasks/watchdog")
async def run_watchdog(...):
    """Enhanced watchdog that handles both stuck and timed-out tasks."""
    service = get_task_queue_service()
    
    # Handle stuck in_progress tasks (existing logic)
    requeue_result = await service.requeue_stuck_tasks(...)
    
    # NEW: Handle timed-out tasks
    timeout_result = await service.fail_timed_out_tasks()
    
    return {
        "requeued": requeue_result.get("requeued", []),
        "failed": requeue_result.get("failed", []),
        "timed_out": timeout_result.get("failed", [])
    }
```

### 4. Improve Error Handling in Agent Execution

Wrap agent execution in comprehensive error handling:

```python
# In _run_task_agent(), enhance error handling

async def _run_task_agent(task: Task):
    """Run the agent for a task with robust error handling."""
    service = get_task_queue_service()
    
    try:
        # ... existing execution code ...
        
    except asyncio.TimeoutError:
        logger.error(f"Task {task.id} timed out after {task.timeout_seconds}s")
        await service.fail_task(
            task.id,
            error="Task execution timed out",
            cascade=False  # Don't fail dependents on timeout
        )
        
    except Exception as e:
        logger.error(f"Task {task.id} failed with exception: {e}", exc_info=True)
        
        # Log to Slack
        await send_task_update(
            task_id=task.id,
            role=task.role,
            event_type="task_failed",
            message=f"Task failed: {str(e)[:200]}",
            details=traceback.format_exc()
        )
        
        # Mark as failed in database
        await service.fail_task(task.id, error=str(e))
    
    finally:
        # Always ensure task is no longer in_progress
        current_task = await service.get_task(task.id)
        if current_task and current_task.status == TaskStatus.IN_PROGRESS:
            logger.warning(f"Task {task.id} still in_progress after execution - force failing")
            await service.fail_task(task.id, error="Task ended without completion")
```

### 5. Add Mission Control Integration (Optional)

The current architecture uses FastAPI background tasks instead of a separate worker process (like Celery). This is:

**Advantages:**
- Simpler deployment (one process)
- No need for message broker (Redis/RabbitMQ)
- Easier debugging (everything in one place)

**Disadvantages:**
- Tasks don't execute if server is down
- No automatic retry on server restart
- Scaling limited by single process
- Tasks compete with HTTP request handling for resources

**For production use at scale, consider:**
- Celery + Redis for distributed task queue
- Separate worker dyno/container on Railway
- Better fault tolerance and scalability

## Conclusion

The task execution flow requires **manual intervention** to start. The SABINE_ARCHITECT agent will only run when:

1. `/tasks/dispatch` is explicitly called, OR
2. The task is a dependency of another task that just completed (auto-dispatch)

To fix the stalled task issue, we need to:
1. Ensure something is calling `/tasks/dispatch` regularly
2. Add automatic task polling (recommended)
3. Improve monitoring to catch stuck tasks early
