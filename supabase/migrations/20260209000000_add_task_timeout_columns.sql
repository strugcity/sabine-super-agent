-- Add timeout detection columns to task_queue table
-- This enables detection and recovery of stuck/hung tasks
--
-- Columns added:
-- - started_at: Timestamp when task was claimed and started execution
-- - timeout_seconds: Maximum execution time before task is considered stuck (default: 30 minutes)
-- - last_heartbeat_at: Optional heartbeat timestamp for long-running tasks

-- Add started_at column (set when task is claimed)
ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

-- Add configurable timeout in seconds (default: 30 minutes = 1800 seconds)
ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 1800;

-- Add optional heartbeat timestamp for long-running tasks
ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;

-- Index for finding stuck tasks efficiently
-- Used by the watchdog to find tasks that have been IN_PROGRESS too long
CREATE INDEX IF NOT EXISTS idx_task_queue_stuck_detection
    ON task_queue (status, started_at)
    WHERE status = 'in_progress';

-- Function to get stuck tasks (IN_PROGRESS longer than timeout)
-- Returns tasks where: status='in_progress' AND started_at + timeout < NOW()
CREATE OR REPLACE FUNCTION get_stuck_tasks(max_results INTEGER DEFAULT 10)
RETURNS SETOF task_queue AS $$
BEGIN
    RETURN QUERY
    SELECT t.*
    FROM task_queue t
    WHERE t.status = 'in_progress'
      AND t.started_at IS NOT NULL
      AND t.started_at + (t.timeout_seconds || ' seconds')::INTERVAL < NOW()
    ORDER BY t.started_at ASC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Function to update heartbeat for a running task
-- Used by long-running tasks to signal they are still alive
CREATE OR REPLACE FUNCTION update_task_heartbeat(target_task_id UUID)
RETURNS BOOLEAN AS $$
DECLARE
    updated_count INTEGER;
BEGIN
    UPDATE task_queue
    SET last_heartbeat_at = NOW(),
        updated_at = NOW()
    WHERE id = target_task_id
      AND status = 'in_progress';

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count > 0;
END;
$$ LANGUAGE plpgsql;

-- Function to requeue a stuck task
-- Resets status to 'queued', increments retry_count, clears started_at
CREATE OR REPLACE FUNCTION requeue_stuck_task(target_task_id UUID, timeout_error TEXT DEFAULT 'Task timed out')
RETURNS BOOLEAN AS $$
DECLARE
    updated_count INTEGER;
    task_record task_queue%ROWTYPE;
BEGIN
    -- Get current task state
    SELECT * INTO task_record FROM task_queue WHERE id = target_task_id;

    IF task_record IS NULL THEN
        RETURN FALSE;
    END IF;

    -- Only requeue if still in_progress and retryable
    IF task_record.status != 'in_progress' THEN
        RETURN FALSE;
    END IF;

    -- Check if we can retry
    IF task_record.retry_count >= task_record.max_retries THEN
        -- Mark as permanently failed
        UPDATE task_queue
        SET status = 'failed',
            error = '[TIMEOUT - MAX RETRIES EXCEEDED] ' || timeout_error,
            is_retryable = FALSE,
            updated_at = NOW()
        WHERE id = target_task_id;
    ELSE
        -- Requeue for retry
        UPDATE task_queue
        SET status = 'queued',
            retry_count = retry_count + 1,
            started_at = NULL,
            last_heartbeat_at = NULL,
            error = timeout_error,
            updated_at = NOW()
        WHERE id = target_task_id;
    END IF;

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count > 0;
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON COLUMN task_queue.started_at IS 'Timestamp when task execution started (set on claim)';
COMMENT ON COLUMN task_queue.timeout_seconds IS 'Maximum execution time in seconds before task is considered stuck (default: 1800 = 30 min)';
COMMENT ON COLUMN task_queue.last_heartbeat_at IS 'Last heartbeat timestamp for long-running tasks';
COMMENT ON FUNCTION get_stuck_tasks(INTEGER) IS 'Get tasks that have been IN_PROGRESS longer than their timeout';
COMMENT ON FUNCTION update_task_heartbeat(UUID) IS 'Update heartbeat timestamp for a running task';
COMMENT ON FUNCTION requeue_stuck_task(UUID, TEXT) IS 'Requeue a stuck task or mark as failed if max retries exceeded';
