# Task Execution Flow - Quick Reference

**Date:** 2026-02-06  
**Issue:** Tasks stalling after acknowledgment - Root Cause Identified ✅

## 🔴 Critical Finding: NO AUTOMATIC TASK DISPATCH

Tasks created via `POST /tasks` sit in `queued` status **forever** until something explicitly calls `POST /tasks/dispatch`.

**Currently:** Nothing automatically calls `/tasks/dispatch`
- ❌ No background worker
- ❌ No cron job  
- ❌ No frontend auto-dispatch
- ❌ No startup dispatcher

**Result:** Tasks never transition from `queued` → `in_progress` without manual intervention.

## How It Works (As-Is)

```
1. POST /tasks           → Task created, status = "queued"
                           ⬇
                           Sits forever...
                           ⬇
2. POST /tasks/dispatch  → Manually called (by who?)
                           ⬇
3. Task claimed          → Status = "in_progress"  
                           ⬇
4. Agent executes        → SABINE_ARCHITECT runs
                           ⬇
5. Task completes        → Status = "completed"
                           ⬇
6. Auto-dispatch         → Triggers dependent tasks (if any)
```

## Key Code Locations

| Component | File | Line |
|-----------|------|------|
| Dispatch Endpoint | `lib/agent/server.py` | 1742 |
| Agent Runner | `lib/agent/server.py` | 2031 |
| Claim Task | `backend/services/task_queue.py` | 293 |
| Auto-Dispatch | `backend/services/task_queue.py` | 972 |

## 🔥 Immediate Fix Required

Add this to `lib/agent/server.py` in `startup_event()`:

```python
# Start automatic task dispatcher
asyncio.create_task(task_dispatcher_loop())

async def task_dispatcher_loop():
    """Auto-dispatch queued tasks every 30 seconds."""
    await asyncio.sleep(10)  # Wait for server startup
    
    while True:
        try:
            service = get_task_queue_service()
            if not service._dispatch_callback:
                service.set_dispatch_callback(_dispatch_task)
            
            claimed = await service.claim_unblocked_tasks_atomic(max_tasks=5)
            
            for task in claimed:
                asyncio.create_task(_run_task_agent(task))
                
        except Exception as e:
            logger.error(f"Task dispatcher error: {e}")
        
        await asyncio.sleep(30)
```

**This will:**
- ✅ Automatically pick up queued tasks within 30 seconds
- ✅ Fix the "tasks stalling forever" issue
- ✅ No code changes needed elsewhere

## Why Did Task 562c4fe8 Fail?

Looking at the event timeline:
1. **19:15:38** - Task started (dispatched somehow)
2. **19:15:44** - Task failed after 6 seconds
3. **19:18:18** - Task restarted (retry mechanism)
4. **No further events** - Task likely stuck

**Next Steps:**
1. Check Railway logs for errors at 19:15:44
2. Query database for task status:
   ```sql
   SELECT status, error, retry_count 
   FROM task_queue 
   WHERE id = '562c4fe8-fef0-4695-af5b-87f6eea02c85';
   ```
3. Check tool_audit_logs for what tools were executed

## See Full Documentation

For complete analysis, code examples, and architectural details:
👉 **[TASK_EXECUTION_FLOW.md](./TASK_EXECUTION_FLOW.md)**
