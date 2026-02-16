# Self-Improvement Loop — Implementation Spec

## Overview

Three independent work items that close the remaining gaps in Sabine's autonomy pipeline. Each can be dispatched to a separate agent (Copilot, Claude subagent, etc.) with zero cross-dependencies.

---

## Work Item 1: Skill Effectiveness Tracker

**Files to create:** `backend/services/skill_effectiveness.py`
**Files to modify:** `backend/services/skill_promotion.py`, `backend/worker/jobs.py`, `backend/worker/main.py`
**Migration:** `supabase/migrations/YYYYMMDD_skill_effectiveness.sql`

### What it does

After a skill is promoted, track whether it *actually helps*. Every time a promoted skill executes via the agent, record whether the interaction was successful. Weekly, compute a **dopamine score** per skill and auto-disable skills that consistently underperform.

### Database migration

```sql
-- Skill execution telemetry: one row per invocation of a promoted skill
CREATE TABLE IF NOT EXISTS skill_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_version_id UUID NOT NULL REFERENCES skill_versions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id TEXT,
    -- Outcome signals
    execution_status TEXT NOT NULL CHECK (execution_status IN ('success', 'error', 'timeout')),
    user_edited_output BOOLEAN DEFAULT false,     -- true if user significantly changed the result
    user_sent_thank_you BOOLEAN DEFAULT false,     -- true if next message was gratitude
    user_repeated_request BOOLEAN DEFAULT false,   -- true if user rephrased same ask
    conversation_turns INT,                        -- how many turns this task took
    -- Metadata
    execution_time_ms INT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_skill_executions_version ON skill_executions(skill_version_id, created_at DESC);
CREATE INDEX idx_skill_executions_user ON skill_executions(user_id, created_at DESC);

-- Add effectiveness score column to skill_versions
ALTER TABLE skill_versions ADD COLUMN IF NOT EXISTS effectiveness_score FLOAT DEFAULT NULL;
ALTER TABLE skill_versions ADD COLUMN IF NOT EXISTS total_executions INT DEFAULT 0;
ALTER TABLE skill_versions ADD COLUMN IF NOT EXISTS last_scored_at TIMESTAMPTZ DEFAULT NULL;
```

### New file: `backend/services/skill_effectiveness.py`

Follow the exact patterns from `backend/services/gap_detection.py`:
- Use `_get_supabase_client()` lazy client pattern
- All functions async with full type hints
- Use `logging` module, never print()

```python
"""
Skill Effectiveness Tracker
=============================

Tracks how well promoted skills perform in real usage.
Computes a "dopamine score" (0.0-1.0) from implicit reward signals
and auto-disables consistently underperforming skills.

PRD Requirements: TRAIN-001, TRAIN-002, TRAIN-003
"""
```

**Functions to implement:**

#### `async def record_skill_execution(skill_version_id: str, user_id: str, ...) -> Optional[str]`
- Insert one row into `skill_executions`
- Parameters match the table columns
- Returns the UUID of the inserted row, or None on error
- Called from the agent tool execution path (see wiring below)

#### `async def compute_effectiveness(skill_version_id: str, lookback_days: int = 30) -> Dict[str, Any]`
- Query `skill_executions` for this skill in the lookback window
- Compute the dopamine score:

```
dopamine = (
    0.40 * success_rate              # % of executions with status='success'
  + 0.25 * (1.0 - edit_rate)         # % where user did NOT edit output
  + 0.20 * (1.0 - repeat_rate)       # % where user did NOT repeat request
  + 0.15 * gratitude_rate            # % where user sent thank you
)
```

- Return: `{"score": float, "total_executions": int, "success_rate": float, "edit_rate": float, "repeat_rate": float, "gratitude_rate": float}`
- If total_executions < 5, return `{"score": None, "reason": "insufficient_data", "total_executions": N}`

#### `async def score_all_skills(user_id: str, lookback_days: int = 30) -> List[Dict]`
- Fetch all active skill_versions for user
- Call `compute_effectiveness()` for each
- Update `skill_versions.effectiveness_score`, `total_executions`, `last_scored_at`
- Return list of `{"skill_name": ..., "version": ..., "score": ..., "total_executions": ...}`

#### `async def auto_disable_underperformers(user_id: str, threshold: float = 0.3, min_executions: int = 10) -> List[Dict]`
- Find active skills where `effectiveness_score < threshold` AND `total_executions >= min_executions`
- Call `disable_skill(version_id)` from `skill_promotion.py` for each
- Log to audit via `log_tool_execution(tool_name="skill_effectiveness", tool_action="auto_disable", ...)`
- Return list of disabled skills

### Modify: `backend/worker/jobs.py`

Add a new job function after `run_weekly_digest`:

```python
@memory_profiled_job()
def run_skill_effectiveness_scoring() -> Dict[str, Any]:
    """
    Score all promoted skills and auto-disable underperformers.
    Runs weekly after gap detection and digest.
    """
    logger.info("run_skill_effectiveness_scoring START")
    start = time.monotonic()
    try:
        from backend.services.skill_effectiveness import score_all_skills, auto_disable_underperformers
        import os
        user_id = os.getenv("DEFAULT_USER_ID", "")
        if not user_id:
            return {"status": "skipped", "reason": "no DEFAULT_USER_ID"}

        scores = asyncio.run(score_all_skills(user_id))
        disabled = asyncio.run(auto_disable_underperformers(user_id))
        elapsed_ms = (time.monotonic() - start) * 1000.0

        result = {
            "status": "completed",
            "skills_scored": len(scores),
            "skills_disabled": len(disabled),
            "disabled_names": [d["skill_name"] for d in disabled],
            "elapsed_ms": round(elapsed_ms, 1),
        }
        logger.info("run_skill_effectiveness_scoring DONE  scored=%d disabled=%d elapsed=%.0fms",
                     len(scores), len(disabled), elapsed_ms)
        return result
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.error("run_skill_effectiveness_scoring FAILED  elapsed=%.0fms error=%s",
                      elapsed_ms, exc, exc_info=True)
        return {"status": "failed", "error": str(exc), "elapsed_ms": round(elapsed_ms, 1)}
```

Update the job catalog docstring at the top of the file to include this new job.

### Modify: `backend/worker/main.py`

Add scheduling for `run_skill_effectiveness_scoring` — schedule it weekly (Sunday 04:00 UTC), after gap detection (03:00) and digest (03:30). Follow the exact pattern used for `run_salience_recalculation` scheduling.

### Modify: `backend/services/skill_promotion.py`

At the end of `promote_skill()`, after the audit log call (line ~131), add:

```python
# Refresh the tool registry so the new skill is immediately available
try:
    from lib.agent.registry import refresh_skill_registry
    await refresh_skill_registry(proposal["user_id"])
    logger.info("Registry refreshed after promoting %s", proposal["skill_name"])
except Exception as e:
    logger.warning("Failed to refresh registry after promotion: %s", e)
```

Do the same at the end of `disable_skill()` and `rollback_skill()`.

### Tests

Create `tests/test_skill_effectiveness.py` following the exact pattern of `tests/test_gap_detection.py`:
- BDD-style test classes
- Full mocking of Supabase client
- `@pytest.mark.asyncio` on all async tests
- No `sys.path` hacks
- Test: score computation with various signal combinations
- Test: auto-disable threshold logic
- Test: insufficient data returns None score

---

## Work Item 2: Auto Gap-to-Proposal Pipeline

**Files to modify:** `backend/worker/jobs.py`, `backend/worker/main.py`
**No new files needed** — the functions already exist, they just aren't wired together.

### What it does

Currently, gap detection runs weekly and creates `skill_gaps` rows. But nobody calls `generate_and_test_skill(gap_id)` automatically. The user has to manually trigger `/api/skills/prototype`. This work item adds a scheduled job that converts open gaps into proposals.

### Modify: `backend/worker/jobs.py`

Add after `run_gap_detection`:

```python
@memory_profiled_job()
def run_skill_generation_batch() -> Dict[str, Any]:
    """
    Generate skill proposals for all open gaps.

    Runs after gap detection. For each gap with status='open',
    calls generate_and_test_skill() to create a proposal.
    Limits to 3 gaps per run to avoid Haiku API cost spikes.

    Returns
    -------
    dict
        Summary with keys: gaps_processed, proposals_created, failures, elapsed_ms.
    """
    logger.info("run_skill_generation_batch START")
    start = time.monotonic()

    try:
        from backend.services.gap_detection import get_open_gaps
        from backend.services.skill_generator import generate_and_test_skill
        import os

        user_id = os.getenv("DEFAULT_USER_ID", "")
        if not user_id:
            return {"status": "skipped", "reason": "no DEFAULT_USER_ID"}

        # Fetch open gaps (limit to 3 per batch to control costs)
        gaps = asyncio.run(get_open_gaps(user_id))
        gaps_to_process = gaps[:3]

        proposals_created = 0
        failures = 0

        for gap in gaps_to_process:
            try:
                result = asyncio.run(generate_and_test_skill(gap["id"]))
                if result.get("status") == "proposed":
                    proposals_created += 1
                else:
                    failures += 1
            except Exception as e:
                logger.error("Failed to generate skill for gap %s: %s", gap["id"], e)
                failures += 1

        elapsed_ms = (time.monotonic() - start) * 1000.0
        result = {
            "status": "completed",
            "gaps_found": len(gaps),
            "gaps_processed": len(gaps_to_process),
            "proposals_created": proposals_created,
            "failures": failures,
            "elapsed_ms": round(elapsed_ms, 1),
        }
        logger.info(
            "run_skill_generation_batch DONE  found=%d processed=%d proposals=%d failures=%d elapsed=%.0fms",
            len(gaps), len(gaps_to_process), proposals_created, failures, elapsed_ms,
        )
        return result

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        logger.error("run_skill_generation_batch FAILED  elapsed=%.0fms error=%s",
                      elapsed_ms, exc, exc_info=True)
        return {"status": "failed", "error": str(exc), "elapsed_ms": round(elapsed_ms, 1)}
```

Update the job catalog docstring to include this new job.

### Modify: `backend/worker/main.py`

Schedule `run_skill_generation_batch` for Sunday 03:15 UTC — 15 minutes after gap detection (03:00), giving gaps time to be created before the generator runs. Follow the existing scheduling pattern.

### Modify: `docs/runbook.md`

Add two rows to the Scheduled Jobs Reference table (Section 4):

| Job | Schedule | Function | Description | Priority |
|-----|----------|----------|-------------|----------|
| Skill Generation | Sunday 03:15 UTC | `run_skill_generation_batch()` (via rq) | Generates proposals for up to 3 open gaps per run | Medium |
| Skill Scoring | Sunday 04:00 UTC | `run_skill_effectiveness_scoring()` (via rq) | Scores promoted skills and auto-disables underperformers | Low |

### Tests

Add tests to `tests/test_skill_generator.py` (append new test class):

```python
class TestSkillGenerationBatch:
    """Tests for the batch gap→proposal pipeline."""

    @pytest.mark.asyncio
    async def test_batch_processes_open_gaps(self, ...):
        """Should call generate_and_test_skill for each open gap."""

    @pytest.mark.asyncio
    async def test_batch_limits_to_three(self, ...):
        """Should process at most 3 gaps even if more are open."""

    @pytest.mark.asyncio
    async def test_batch_skips_without_user_id(self, ...):
        """Should return skipped if DEFAULT_USER_ID not set."""
```

---

## Work Item 3: Implicit Signal Classifier

**Files to create:** `backend/services/signal_classifier.py`
**Files to modify:** `lib/agent/core.py` (wiring only — 1 call site)

### What it does

After each agent response, classify the user's *next* message for implicit reward/punishment signals. This feeds into the `skill_executions` table from Work Item 1.

The PRD defines these signals (section 4.7.1):

**Positive:** user uses output directly (no edits), says "thank you", proceeds to logical next step, task completed in fewer turns than average.

**Negative:** user significantly edits output (>30%), repeats command with different wording, abandons conversation, explicitly expresses frustration.

### New file: `backend/services/signal_classifier.py`

```python
"""
Implicit Signal Classifier
============================

Classifies user messages for implicit reward/punishment signals
after an agent response. These signals feed into the skill
effectiveness scoring system.

PRD Requirements: TRAIN-001, TRAIN-004

Note: This uses keyword/pattern matching, NOT LLM calls.
TRAIN-004 explicitly says "no direct model fine-tuning" —
we optimize retrieval and prompts, not weights.
"""
```

**Functions to implement:**

#### `def classify_gratitude(message: str) -> bool`
- Returns True if the message is a "thank you" or equivalent
- Pattern match against: "thank", "thanks", "thx", "ty", "perfect", "great job", "awesome", "exactly what i needed", "love it", "nice"
- Case-insensitive
- Must NOT false-positive on "no thanks" or "thanks but" — check for negation prefixes

#### `def classify_repetition(current_message: str, previous_message: str) -> bool`
- Returns True if `current_message` appears to be a rephrased version of `previous_message`
- Use Jaccard similarity on word sets (lowercase, stripped of stopwords)
- Threshold: > 0.5 similarity = repetition
- Stopwords: {"the", "a", "an", "is", "was", "are", "were", "do", "does", "did", "can", "could", "would", "should", "please", "just", "me", "my", "i"}
- This is a cheap heuristic — no LLM calls

#### `def classify_frustration(message: str) -> bool`
- Returns True if the message contains frustration signals
- Patterns: "that's wrong", "no that's not", "you misunderstood", "try again", "not what i asked", "still wrong", "ugh", "come on", "wtf", "seriously?"
- Case-insensitive
- Do NOT flag polite corrections like "actually I meant..." — only clear frustration

#### `def classify_signals(current_message: str, previous_user_message: Optional[str] = None, agent_used_skill: Optional[str] = None) -> Dict[str, Any]`
- Orchestrator function that calls the above classifiers
- Returns:
```python
{
    "gratitude": bool,
    "repetition": bool,       # only if previous_user_message provided
    "frustration": bool,
    "skill_version_id": str or None,  # passthrough from agent_used_skill
}
```

### Wiring into `lib/agent/core.py`

Find the location where the agent returns a response to the user (the `run_agent` or `run_agent_with_caching` function). After the response is generated, if the agent used a promoted skill during this turn, record the execution:

```python
# At the end of run_agent, after getting the response:
try:
    from backend.services.signal_classifier import classify_signals
    from backend.services.skill_effectiveness import record_skill_execution

    # Check if any promoted (DB) skill was used in this turn
    # The tool execution results are in the agent's intermediate steps
    for step in agent_result.get("intermediate_steps", []):
        tool_name = step[0].tool if hasattr(step[0], 'tool') else ""
        # DB skills are prefixed with "skill_" in the registry
        if tool_name.startswith("skill_"):
            # Record the execution (fire-and-forget, don't block response)
            asyncio.create_task(record_skill_execution(
                skill_version_id=...,  # look up from registry
                user_id=user_id,
                execution_status="success" if not step[1].get("error") else "error",
                execution_time_ms=...,
            ))
except Exception:
    pass  # Never let telemetry break the response path
```

**IMPORTANT constraints on wiring:**
- This must be fire-and-forget (`asyncio.create_task`) — never block the response
- Wrap in try/except that passes — telemetry must never break the user experience
- The signal classification for the *next* message (gratitude, repetition, etc.) should be done at the *start* of the next `run_agent` call, updating the previous execution's record
- This is the trickiest part — the implementer should study how `core.py` structures its response flow before writing the wiring code

### Tests

Create `tests/test_signal_classifier.py`:

```python
class TestGratitudeClassifier:
    def test_thank_you(self):
        assert classify_gratitude("Thank you!") is True

    def test_thanks_but(self):
        assert classify_gratitude("Thanks but that's not right") is False

    def test_no_thanks(self):
        assert classify_gratitude("No thanks") is False

    def test_perfect(self):
        assert classify_gratitude("Perfect, exactly what I needed") is True

    def test_neutral(self):
        assert classify_gratitude("Can you also check the weather?") is False


class TestRepetitionClassifier:
    def test_rephrased_question(self):
        assert classify_repetition("what's the weather today", "tell me today's weather") is True

    def test_different_question(self):
        assert classify_repetition("what's for dinner", "what's the weather") is False

    def test_identical(self):
        assert classify_repetition("check my calendar", "check my calendar") is True


class TestFrustrationClassifier:
    def test_explicit_frustration(self):
        assert classify_frustration("That's wrong, try again") is True

    def test_polite_correction(self):
        assert classify_frustration("Actually I meant next Tuesday") is False

    def test_neutral(self):
        assert classify_frustration("Okay, now send it to John") is False
```

No `sys.path` hacks. No `@pytest.mark.asyncio` needed — these are all sync functions.

---

## Dispatch Order

All three work items are **independent** and can run concurrently:

| Item | Scope | Estimated Files | Dependencies |
|------|-------|----------------|--------------|
| 1. Skill Effectiveness Tracker | 1 new file + 1 migration + 3 modifications + 1 test file | 6 files | None |
| 2. Auto Gap-to-Proposal Pipeline | 0 new files + 2 modifications + 1 test addition + 1 doc update | 4 files | None |
| 3. Implicit Signal Classifier | 1 new file + 1 modification + 1 test file | 3 files | None |

**Item 2** is smallest and can merge first. **Item 1** provides the table that **Item 3** writes to, but they can be developed in parallel — just merge Item 1 first so the migration runs before Item 3's code tries to insert.

## Code Conventions (apply to all items)

- Python 3.11+, full type hints on every function
- Pydantic v2 `BaseModel` for any new schemas
- Use `logging` module, never `print()`
- Lazy imports inside functions to avoid circular dependencies
- Follow `_get_supabase_client()` pattern from `gap_detection.py`
- Worker jobs are sync, use `asyncio.run()` internally (rq workers are sync)
- Worker jobs use `@memory_profiled_job()` decorator
- Tests: pytest, BDD-style classes, `@pytest.mark.asyncio` for async, no `sys.path` hacks
- Run `python -m py_compile <file>` after writing each file
