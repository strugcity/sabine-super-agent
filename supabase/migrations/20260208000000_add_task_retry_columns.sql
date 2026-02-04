-- Add retry mechanism columns to task_queue table
-- This enables automatic retry with exponential backoff for failed tasks
--
-- Columns added:
-- - retry_count: Number of times this task has been retried
-- - max_retries: Maximum retry attempts before permanent failure (default: 3)
-- - next_retry_at: Timestamp when this task can be retried (for backoff scheduling)
-- - last_error: Most recent error message (preserves history across retries)
-- - is_retryable: Whether the failure is retryable (false = permanent failure)

-- Add retry_count column
ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;

-- Add max_retries column (configurable per task, default 3)
ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 3;

-- Add next_retry_at for scheduling retries with backoff
ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;

-- Add is_retryable flag to distinguish retryable vs permanent failures
ALTER TABLE task_queue
ADD COLUMN IF NOT EXISTS is_retryable BOOLEAN NOT NULL DEFAULT TRUE;

-- Index for finding tasks ready for retry
-- Used by the retry worker to find failed tasks that can be retried
CREATE INDEX IF NOT EXISTS idx_task_queue_retry
    ON task_queue (status, next_retry_at)
    WHERE status = 'failed' AND is_retryable = TRUE;

-- Function to get tasks ready for retry
-- Returns failed tasks where next_retry_at has passed and retry_count < max_retries
CREATE OR REPLACE FUNCTION get_retryable_tasks()
RETURNS SETOF task_queue AS $$
BEGIN
    RETURN QUERY
    SELECT t.*
    FROM task_queue t
    WHERE t.status = 'failed'
      AND t.is_retryable = TRUE
      AND t.retry_count < t.max_retries
      AND (t.next_retry_at IS NULL OR t.next_retry_at <= NOW())
    ORDER BY t.priority DESC, t.next_retry_at ASC NULLS FIRST
    LIMIT 10;
END;
$$ LANGUAGE plpgsql;

-- Function to retry a failed task
-- Resets status to 'queued', increments retry_count, clears next_retry_at
CREATE OR REPLACE FUNCTION retry_task(target_task_id UUID)
RETURNS BOOLEAN AS $$
DECLARE
    updated_count INTEGER;
BEGIN
    UPDATE task_queue
    SET status = 'queued',
        retry_count = retry_count + 1,
        next_retry_at = NULL,
        updated_at = NOW()
    WHERE id = target_task_id
      AND status = 'failed'
      AND is_retryable = TRUE
      AND retry_count < max_retries;

    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RETURN updated_count > 0;
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON COLUMN task_queue.retry_count IS 'Number of times this task has been retried after failure';
COMMENT ON COLUMN task_queue.max_retries IS 'Maximum retry attempts before permanent failure (default: 3)';
COMMENT ON COLUMN task_queue.next_retry_at IS 'Earliest time this task can be retried (for exponential backoff)';
COMMENT ON COLUMN task_queue.is_retryable IS 'Whether this failure can be retried (false = permanent failure like validation error)';
COMMENT ON FUNCTION get_retryable_tasks() IS 'Get failed tasks that are eligible for retry';
COMMENT ON FUNCTION retry_task(UUID) IS 'Retry a failed task by resetting its status to queued';
