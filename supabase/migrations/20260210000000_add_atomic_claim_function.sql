-- Add atomic task claiming function to prevent race conditions
-- Uses FOR UPDATE SKIP LOCKED to ensure only one worker can claim a task
--
-- This prevents the race condition where:
-- 1. Worker A fetches unblocked tasks (sees Task X)
-- 2. Worker B fetches unblocked tasks (also sees Task X)
-- 3. Both try to claim Task X
-- 4. Task X could be executed twice

-- Function to atomically claim the next available task for a role
-- Returns the claimed task or NULL if none available
-- Uses FOR UPDATE SKIP LOCKED to prevent race conditions
CREATE OR REPLACE FUNCTION claim_next_task_for_role(
    target_role TEXT,
    claim_timeout_seconds INTEGER DEFAULT 1800
)
RETURNS SETOF task_queue AS $$
DECLARE
    claimed_task task_queue%ROWTYPE;
    now_ts TIMESTAMPTZ := NOW();
BEGIN
    -- Atomically select and update in one transaction
    -- FOR UPDATE SKIP LOCKED ensures only one worker gets each task
    SELECT * INTO claimed_task
    FROM task_queue t
    WHERE t.role = target_role
      AND t.status = 'queued'
      AND task_dependencies_met(t.id)
    ORDER BY t.priority DESC, t.created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    -- If no task found, return empty
    IF claimed_task.id IS NULL THEN
        RETURN;
    END IF;

    -- Update the task to in_progress
    UPDATE task_queue
    SET status = 'in_progress',
        started_at = now_ts,
        last_heartbeat_at = now_ts,
        updated_at = now_ts
    WHERE id = claimed_task.id;

    -- Return the updated task
    claimed_task.status := 'in_progress';
    claimed_task.started_at := now_ts;
    claimed_task.last_heartbeat_at := now_ts;
    claimed_task.updated_at := now_ts;

    RETURN NEXT claimed_task;
    RETURN;
END;
$$ LANGUAGE plpgsql;

-- Function to atomically claim the next available task (any role)
-- Returns the claimed task or NULL if none available
CREATE OR REPLACE FUNCTION claim_next_unblocked_task(
    claim_timeout_seconds INTEGER DEFAULT 1800
)
RETURNS SETOF task_queue AS $$
DECLARE
    claimed_task task_queue%ROWTYPE;
    now_ts TIMESTAMPTZ := NOW();
BEGIN
    -- Atomically select and update in one transaction
    -- FOR UPDATE SKIP LOCKED ensures only one worker gets each task
    SELECT * INTO claimed_task
    FROM task_queue t
    WHERE t.status = 'queued'
      AND task_dependencies_met(t.id)
    ORDER BY t.priority DESC, t.created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    -- If no task found, return empty
    IF claimed_task.id IS NULL THEN
        RETURN;
    END IF;

    -- Update the task to in_progress
    UPDATE task_queue
    SET status = 'in_progress',
        started_at = now_ts,
        last_heartbeat_at = now_ts,
        updated_at = now_ts
    WHERE id = claimed_task.id;

    -- Return the updated task
    claimed_task.status := 'in_progress';
    claimed_task.started_at := now_ts;
    claimed_task.last_heartbeat_at := now_ts;
    claimed_task.updated_at := now_ts;

    RETURN NEXT claimed_task;
    RETURN;
END;
$$ LANGUAGE plpgsql;

-- Function to atomically claim multiple unblocked tasks
-- Returns up to max_tasks claimed tasks
-- Each task is locked individually with SKIP LOCKED
CREATE OR REPLACE FUNCTION claim_unblocked_tasks(
    max_tasks INTEGER DEFAULT 5
)
RETURNS SETOF task_queue AS $$
DECLARE
    task_record task_queue%ROWTYPE;
    now_ts TIMESTAMPTZ := NOW();
    claimed_count INTEGER := 0;
BEGIN
    -- Loop through available tasks and claim them one by one
    FOR task_record IN
        SELECT *
        FROM task_queue t
        WHERE t.status = 'queued'
          AND task_dependencies_met(t.id)
        ORDER BY t.priority DESC, t.created_at ASC
        FOR UPDATE SKIP LOCKED
    LOOP
        -- Update the task to in_progress
        UPDATE task_queue
        SET status = 'in_progress',
            started_at = now_ts,
            last_heartbeat_at = now_ts,
            updated_at = now_ts
        WHERE id = task_record.id;

        -- Update the record to return
        task_record.status := 'in_progress';
        task_record.started_at := now_ts;
        task_record.last_heartbeat_at := now_ts;
        task_record.updated_at := now_ts;

        RETURN NEXT task_record;

        claimed_count := claimed_count + 1;
        EXIT WHEN claimed_count >= max_tasks;
    END LOOP;

    RETURN;
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON FUNCTION claim_next_task_for_role(TEXT, INTEGER) IS
    'Atomically claim the next available task for a specific role. Uses FOR UPDATE SKIP LOCKED to prevent race conditions.';
COMMENT ON FUNCTION claim_next_unblocked_task(INTEGER) IS
    'Atomically claim the next available unblocked task (any role). Uses FOR UPDATE SKIP LOCKED to prevent race conditions.';
COMMENT ON FUNCTION claim_unblocked_tasks(INTEGER) IS
    'Atomically claim up to N unblocked tasks. Each task is individually locked with SKIP LOCKED.';
