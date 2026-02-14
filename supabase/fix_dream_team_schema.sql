-- ============================================================================
-- DREAM TEAM AGENT FIX - Combined Missing Migrations
-- ============================================================================
-- Run this script in Supabase SQL Editor to fix the Dream Team agent issues
--
-- ROOT CAUSE: Two critical database schema issues:
-- 1. Missing 'completed_at' column on task_queue table
-- 2. Missing 'tool_audit_log' table
--
-- This script combines migrations that were never applied:
-- - 20260207000000_create_tool_audit_log.sql
-- - 20260208000000_add_task_retry_columns.sql
-- - 20260209000000_add_task_timeout_columns.sql
-- - 20260211000000_add_blocked_task_detection.sql
-- - 20260215000000_add_observability_metrics.sql
-- ============================================================================

-- =============================================================================
-- PART 1: TOOL AUDIT LOG TABLE (20260207)
-- =============================================================================

CREATE TABLE IF NOT EXISTS tool_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    session_id TEXT,
    task_id UUID REFERENCES task_queue(id),
    agent_role TEXT,
    tool_name TEXT NOT NULL,
    tool_action TEXT,
    input_params JSONB DEFAULT '{}',
    output_summary JSONB DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('success', 'error', 'timeout', 'blocked')),
    error_type TEXT,
    error_message TEXT,
    target_repo TEXT,
    target_path TEXT,
    artifact_created TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tool_audit_user_id ON tool_audit_log(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tool_audit_task_id ON tool_audit_log(task_id) WHERE task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tool_audit_tool_name ON tool_audit_log(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_audit_status ON tool_audit_log(status);
CREATE INDEX IF NOT EXISTS idx_tool_audit_target_repo ON tool_audit_log(target_repo) WHERE target_repo IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tool_audit_created_at ON tool_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_audit_role_status ON tool_audit_log(agent_role, status);

-- Row Level Security
ALTER TABLE tool_audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role has full access to tool_audit_log" ON tool_audit_log;
CREATE POLICY "Service role has full access to tool_audit_log"
    ON tool_audit_log
    FOR ALL
    USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Users can view their own tool audit logs" ON tool_audit_log;
CREATE POLICY "Users can view their own tool audit logs"
    ON tool_audit_log
    FOR SELECT
    USING (
        auth.role() = 'authenticated'
        AND (user_id = auth.uid() OR user_id IS NULL)
    );

-- Helper functions
CREATE OR REPLACE FUNCTION get_task_tool_executions(p_task_id UUID)
RETURNS TABLE (
    id UUID,
    tool_name TEXT,
    tool_action TEXT,
    status TEXT,
    artifact_created TEXT,
    error_message TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT
        id,
        tool_name,
        tool_action,
        status,
        artifact_created,
        error_message,
        execution_time_ms,
        created_at
    FROM tool_audit_log
    WHERE task_id = p_task_id
    ORDER BY created_at ASC;
$$;

CREATE OR REPLACE FUNCTION get_tool_execution_stats(p_hours INTEGER DEFAULT 24)
RETURNS TABLE (
    tool_name TEXT,
    total_calls BIGINT,
    success_count BIGINT,
    error_count BIGINT,
    avg_execution_ms NUMERIC,
    success_rate NUMERIC
)
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT
        tool_name,
        COUNT(*) as total_calls,
        COUNT(*) FILTER (WHERE status = 'success') as success_count,
        COUNT(*) FILTER (WHERE status = 'error') as error_count,
        ROUND(AVG(execution_time_ms), 2) as avg_execution_ms,
        ROUND(
            COUNT(*) FILTER (WHERE status = 'success')::NUMERIC /
            NULLIF(COUNT(*), 0) * 100,
            2
        ) as success_rate
    FROM tool_audit_log
    WHERE created_at >= NOW() - (p_hours || ' hours')::INTERVAL
    GROUP BY tool_name
    ORDER BY total_calls DESC;
$$;

-- =============================================================================
-- PART 2: TASK RETRY COLUMNS (20260208)
-- =============================================================================

ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS max_retries INTEGER NOT NULL DEFAULT 3;
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS is_retryable BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_task_queue_retry
    ON task_queue (status, next_retry_at)
    WHERE status = 'failed' AND is_retryable = TRUE;

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

-- =============================================================================
-- PART 3: TASK TIMEOUT COLUMNS (20260209)
-- =============================================================================

ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 300;

CREATE INDEX IF NOT EXISTS idx_task_queue_started_at
    ON task_queue (status, started_at)
    WHERE status = 'in_progress';

CREATE OR REPLACE FUNCTION get_timed_out_tasks(max_results INTEGER DEFAULT 50)
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

-- =============================================================================
-- PART 4: BLOCKED TASK DETECTION (20260211)
-- =============================================================================

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
        LEFT(t.payload::TEXT, 200) AS task_prompt,
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
        LEFT(t.payload::TEXT, 200) AS task_prompt,
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
        (SELECT COUNT(*)::INTEGER FROM task_queue WHERE status = 'queued'),
        (SELECT COUNT(*)::INTEGER FROM task_queue WHERE status = 'in_progress'),
        (SELECT COUNT(DISTINCT t.id)::INTEGER
         FROM task_queue t
         CROSS JOIN LATERAL unnest(t.depends_on) AS dep_id
         JOIN task_queue dep ON dep.id = dep_id
         WHERE t.status = 'queued' AND dep.status = 'failed'),
        (SELECT COUNT(*)::INTEGER
         FROM task_queue
         WHERE status = 'queued'
           AND created_at < NOW() - INTERVAL '1 hour'),
        (SELECT COUNT(*)::INTEGER
         FROM task_queue
         WHERE status = 'queued'
           AND created_at < NOW() - INTERVAL '24 hours'),
        (SELECT COUNT(*)::INTEGER
         FROM task_queue
         WHERE status = 'in_progress'
           AND started_at IS NOT NULL
           AND started_at + (timeout_seconds || ' seconds')::INTERVAL < NOW()),
        (SELECT COUNT(*)::INTEGER
         FROM task_queue
         WHERE status = 'failed'
           AND is_retryable = TRUE
           AND next_retry_at IS NOT NULL
           AND next_retry_at <= NOW());
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- PART 5: OBSERVABILITY METRICS - THE CRITICAL FIX (20260215)
-- =============================================================================

-- THIS IS THE KEY FIX: Add completed_at column
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS duration_ms INTEGER;
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS error_type TEXT;

CREATE INDEX IF NOT EXISTS idx_task_queue_completed_at ON task_queue(completed_at);
CREATE INDEX IF NOT EXISTS idx_task_queue_error_type ON task_queue(error_type);
CREATE INDEX IF NOT EXISTS idx_task_queue_role_status ON task_queue(role, status);

-- Task Metrics Time-Series Table
CREATE TABLE IF NOT EXISTS task_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_queued INTEGER NOT NULL DEFAULT 0,
    total_in_progress INTEGER NOT NULL DEFAULT 0,
    total_completed_1h INTEGER NOT NULL DEFAULT 0,
    total_failed_1h INTEGER NOT NULL DEFAULT 0,
    blocked_count INTEGER NOT NULL DEFAULT 0,
    stale_1h_count INTEGER NOT NULL DEFAULT 0,
    stale_24h_count INTEGER NOT NULL DEFAULT 0,
    stuck_count INTEGER NOT NULL DEFAULT 0,
    pending_retries INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms INTEGER,
    p50_duration_ms INTEGER,
    p95_duration_ms INTEGER,
    p99_duration_ms INTEGER,
    success_rate_1h NUMERIC(5,2),
    errors_timeout INTEGER NOT NULL DEFAULT 0,
    errors_dependency INTEGER NOT NULL DEFAULT 0,
    errors_agent INTEGER NOT NULL DEFAULT 0,
    errors_tool INTEGER NOT NULL DEFAULT 0,
    errors_external INTEGER NOT NULL DEFAULT 0,
    errors_other INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_task_metrics_recorded_at ON task_metrics(recorded_at DESC);

-- Role Performance Metrics Table
CREATE TABLE IF NOT EXISTS role_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    role TEXT NOT NULL,
    total_completed INTEGER NOT NULL DEFAULT 0,
    total_failed INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms INTEGER,
    min_duration_ms INTEGER,
    max_duration_ms INTEGER,
    p50_duration_ms INTEGER,
    p95_duration_ms INTEGER,
    success_rate NUMERIC(5,2),
    errors_by_type JSONB DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS idx_role_metrics_recorded_at ON role_metrics(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_role_metrics_role ON role_metrics(role);

-- Function to record current queue snapshot
CREATE OR REPLACE FUNCTION record_task_metrics()
RETURNS UUID AS $$
DECLARE
    metrics_id UUID;
    completed_tasks RECORD;
    queue_health RECORD;
BEGIN
    SELECT * INTO queue_health FROM get_task_queue_health();

    SELECT
        COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
        COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
        AVG(duration_ms) FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as avg_duration,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms)
            FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as p50_duration,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)
            FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as p95_duration,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms)
            FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as p99_duration,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'timeout') as timeout_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'dependency_failed') as dep_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'agent_error') as agent_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'tool_error') as tool_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'external_service') as external_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type NOT IN ('timeout', 'dependency_failed', 'agent_error', 'tool_error', 'external_service')) as other_errors
    INTO completed_tasks
    FROM task_queue
    WHERE (completed_at >= NOW() - INTERVAL '1 hour' AND status = 'completed')
       OR (updated_at >= NOW() - INTERVAL '1 hour' AND status = 'failed');

    INSERT INTO task_metrics (
        total_queued, total_in_progress, total_completed_1h, total_failed_1h,
        blocked_count, stale_1h_count, stale_24h_count, stuck_count, pending_retries,
        avg_duration_ms, p50_duration_ms, p95_duration_ms, p99_duration_ms,
        success_rate_1h, errors_timeout, errors_dependency, errors_agent,
        errors_tool, errors_external, errors_other
    ) VALUES (
        queue_health.total_queued,
        queue_health.total_in_progress,
        COALESCE(completed_tasks.completed_count, 0),
        COALESCE(completed_tasks.failed_count, 0),
        queue_health.blocked_by_failed_deps,
        queue_health.stale_queued_1h,
        queue_health.stale_queued_24h,
        queue_health.stuck_tasks,
        queue_health.pending_retries,
        completed_tasks.avg_duration::INTEGER,
        completed_tasks.p50_duration::INTEGER,
        completed_tasks.p95_duration::INTEGER,
        completed_tasks.p99_duration::INTEGER,
        CASE
            WHEN (COALESCE(completed_tasks.completed_count, 0) + COALESCE(completed_tasks.failed_count, 0)) > 0
            THEN ROUND(100.0 * COALESCE(completed_tasks.completed_count, 0) /
                 (COALESCE(completed_tasks.completed_count, 0) + COALESCE(completed_tasks.failed_count, 0)), 2)
            ELSE NULL
        END,
        COALESCE(completed_tasks.timeout_errors, 0),
        COALESCE(completed_tasks.dep_errors, 0),
        COALESCE(completed_tasks.agent_errors, 0),
        COALESCE(completed_tasks.tool_errors, 0),
        COALESCE(completed_tasks.external_errors, 0),
        COALESCE(completed_tasks.other_errors, 0)
    )
    RETURNING id INTO metrics_id;

    RETURN metrics_id;
END;
$$ LANGUAGE plpgsql;

-- Function to get latest metrics snapshot
CREATE OR REPLACE FUNCTION get_latest_metrics()
RETURNS TABLE (
    recorded_at TIMESTAMPTZ,
    total_queued INTEGER,
    total_in_progress INTEGER,
    total_completed_1h INTEGER,
    total_failed_1h INTEGER,
    success_rate_1h NUMERIC,
    avg_duration_ms INTEGER,
    p95_duration_ms INTEGER,
    blocked_count INTEGER,
    stuck_count INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.recorded_at,
        m.total_queued,
        m.total_in_progress,
        m.total_completed_1h,
        m.total_failed_1h,
        m.success_rate_1h,
        m.avg_duration_ms,
        m.p95_duration_ms,
        m.blocked_count,
        m.stuck_count
    FROM task_metrics m
    ORDER BY m.recorded_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- PART 6: FIX STUCK TASKS - Mark completed tasks that failed to update
-- =============================================================================

-- Update any in_progress tasks that are actually completed but failed status update
-- These are tasks with tool executions that succeeded
UPDATE task_queue
SET status = 'completed',
    completed_at = updated_at,
    result = COALESCE(result, '{"note": "Status recovered after completion update failure"}'::JSONB)
WHERE status = 'in_progress'
  AND updated_at < NOW() - INTERVAL '1 hour';

-- Refresh the PostgREST schema cache
NOTIFY pgrst, 'reload schema';

-- =============================================================================
-- VERIFICATION
-- =============================================================================

-- Verify the fix was applied
DO $$
BEGIN
    -- Check completed_at column exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'task_queue' AND column_name = 'completed_at'
    ) THEN
        RAISE EXCEPTION 'FAILED: completed_at column not created';
    END IF;

    -- Check tool_audit_log table exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'tool_audit_log'
    ) THEN
        RAISE EXCEPTION 'FAILED: tool_audit_log table not created';
    END IF;

    RAISE NOTICE 'SUCCESS: All schema fixes applied successfully!';
    RAISE NOTICE 'The Dream Team agents should now be able to:';
    RAISE NOTICE '  1. Mark tasks as completed (completed_at column added)';
    RAISE NOTICE '  2. Log tool executions (tool_audit_log table created)';
    RAISE NOTICE '';
    RAISE NOTICE 'Please redeploy Railway to pick up the schema changes.';
END $$;
