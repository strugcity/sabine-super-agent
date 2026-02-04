-- Add blocked task detection functionality
-- This enables proactive alerting for tasks blocked by failed dependencies
-- and tasks that have been queued for too long
--
-- Features:
-- - get_blocked_tasks(): Find tasks blocked by failed dependencies
-- - get_stale_queued_tasks(): Find tasks queued longer than threshold
-- - get_orphaned_tasks(): Find tasks with ALL dependencies failed

-- Function to get tasks blocked by failed dependencies
-- A task is "blocked" if ANY of its dependencies are FAILED
-- These tasks will never run without manual intervention
CREATE OR REPLACE FUNCTION get_blocked_tasks(max_results INTEGER DEFAULT 50)
RETURNS TABLE (
    task_id UUID,
    task_role TEXT,
    task_prompt TEXT,
    created_at TIMESTAMPTZ,
    failed_dependency_id UUID,
    failed_dependency_role TEXT,
    failed_dependency_error TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.id AS task_id,
        t.role AS task_role,
        LEFT(t.prompt, 200) AS task_prompt,
        t.created_at,
        dep.id AS failed_dependency_id,
        dep.role AS failed_dependency_role,
        LEFT(dep.error, 200) AS failed_dependency_error
    FROM task_queue t
    CROSS JOIN LATERAL unnest(t.depends_on) AS dep_id
    JOIN task_queue dep ON dep.id = dep_id
    WHERE t.status = 'queued'
      AND dep.status = 'failed'
    ORDER BY t.created_at ASC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Function to get tasks that have been queued for too long
-- threshold_minutes: how long is "too long" (default: 60 minutes)
CREATE OR REPLACE FUNCTION get_stale_queued_tasks(
    threshold_minutes INTEGER DEFAULT 60,
    max_results INTEGER DEFAULT 50
)
RETURNS TABLE (
    task_id UUID,
    task_role TEXT,
    task_prompt TEXT,
    created_at TIMESTAMPTZ,
    queued_minutes DOUBLE PRECISION,
    dependency_count INTEGER,
    pending_dependencies INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.id AS task_id,
        t.role AS task_role,
        LEFT(t.prompt, 200) AS task_prompt,
        t.created_at,
        EXTRACT(EPOCH FROM (NOW() - t.created_at)) / 60.0 AS queued_minutes,
        COALESCE(array_length(t.depends_on, 1), 0) AS dependency_count,
        (
            SELECT COUNT(*)::INTEGER
            FROM unnest(t.depends_on) AS dep_id
            JOIN task_queue dep ON dep.id = dep_id
            WHERE dep.status NOT IN ('completed')
        ) AS pending_dependencies
    FROM task_queue t
    WHERE t.status = 'queued'
      AND t.created_at < NOW() - (threshold_minutes || ' minutes')::INTERVAL
    ORDER BY t.created_at ASC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Function to get completely orphaned tasks
-- These are tasks where ALL dependencies have failed (not just some)
-- They have zero chance of ever running
CREATE OR REPLACE FUNCTION get_orphaned_tasks(max_results INTEGER DEFAULT 50)
RETURNS TABLE (
    task_id UUID,
    task_role TEXT,
    task_prompt TEXT,
    created_at TIMESTAMPTZ,
    total_dependencies INTEGER,
    failed_dependencies INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.id AS task_id,
        t.role AS task_role,
        LEFT(t.prompt, 200) AS task_prompt,
        t.created_at,
        COALESCE(array_length(t.depends_on, 1), 0) AS total_dependencies,
        (
            SELECT COUNT(*)::INTEGER
            FROM unnest(t.depends_on) AS dep_id
            JOIN task_queue dep ON dep.id = dep_id
            WHERE dep.status = 'failed'
        ) AS failed_dependencies
    FROM task_queue t
    WHERE t.status = 'queued'
      AND COALESCE(array_length(t.depends_on, 1), 0) > 0
      AND NOT EXISTS (
          -- No dependencies that are NOT failed (all must be failed)
          SELECT 1
          FROM unnest(t.depends_on) AS dep_id
          JOIN task_queue dep ON dep.id = dep_id
          WHERE dep.status != 'failed'
      )
    ORDER BY t.created_at ASC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

-- Function to get a health summary of the task queue
CREATE OR REPLACE FUNCTION get_task_queue_health()
RETURNS TABLE (
    total_queued INTEGER,
    total_in_progress INTEGER,
    blocked_by_failed_deps INTEGER,
    stale_queued_1h INTEGER,
    stale_queued_24h INTEGER,
    stuck_tasks INTEGER,
    pending_retries INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        -- Total queued
        (SELECT COUNT(*)::INTEGER FROM task_queue WHERE status = 'queued'),
        -- Total in progress
        (SELECT COUNT(*)::INTEGER FROM task_queue WHERE status = 'in_progress'),
        -- Blocked by failed dependencies
        (SELECT COUNT(DISTINCT t.id)::INTEGER
         FROM task_queue t
         CROSS JOIN LATERAL unnest(t.depends_on) AS dep_id
         JOIN task_queue dep ON dep.id = dep_id
         WHERE t.status = 'queued' AND dep.status = 'failed'),
        -- Stale queued > 1 hour
        (SELECT COUNT(*)::INTEGER
         FROM task_queue
         WHERE status = 'queued'
           AND created_at < NOW() - INTERVAL '1 hour'),
        -- Stale queued > 24 hours
        (SELECT COUNT(*)::INTEGER
         FROM task_queue
         WHERE status = 'queued'
           AND created_at < NOW() - INTERVAL '24 hours'),
        -- Stuck in_progress (past timeout)
        (SELECT COUNT(*)::INTEGER
         FROM task_queue
         WHERE status = 'in_progress'
           AND started_at IS NOT NULL
           AND started_at + (timeout_seconds || ' seconds')::INTERVAL < NOW()),
        -- Pending retries (failed but retryable)
        (SELECT COUNT(*)::INTEGER
         FROM task_queue
         WHERE status = 'failed'
           AND is_retryable = TRUE
           AND next_retry_at IS NOT NULL
           AND next_retry_at <= NOW());
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON FUNCTION get_blocked_tasks(INTEGER) IS
    'Get tasks blocked by failed dependencies (will never run without intervention)';
COMMENT ON FUNCTION get_stale_queued_tasks(INTEGER, INTEGER) IS
    'Get tasks that have been queued longer than the threshold';
COMMENT ON FUNCTION get_orphaned_tasks(INTEGER) IS
    'Get tasks where ALL dependencies have failed';
COMMENT ON FUNCTION get_task_queue_health() IS
    'Get overall health metrics for the task queue';
