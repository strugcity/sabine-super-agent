-- Phase 3: The Pulse - Task Queue for Multi-Agent Orchestration
-- This table enables the "Agent Handshake" pattern where tasks can depend on
-- other tasks and automatically dispatch when dependencies are met.

-- Create the task_queue table
CREATE TABLE IF NOT EXISTS task_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Role assignment: which agent should handle this task
    role TEXT NOT NULL,

    -- Task status with constrained values
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'in_progress', 'completed', 'failed')),

    -- Priority (higher = more important, processed first)
    priority INTEGER NOT NULL DEFAULT 0,

    -- Instructions/context for the agent (flexible JSON payload)
    payload JSONB NOT NULL DEFAULT '{}',

    -- Dependency tracking: array of task IDs that must complete first
    -- Task stays "queued" until ALL depends_on tasks are "completed"
    depends_on UUID[] DEFAULT '{}',

    -- Result from agent execution (populated on completion)
    result JSONB,

    -- Error details (populated on failure)
    error TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Optional: who/what created this task
    created_by TEXT,

    -- Optional: track which session/conversation spawned this task
    session_id TEXT
);

-- Index for fast task lookup by role and status
-- Used by get_next_task() to find ready tasks for a specific agent
CREATE INDEX IF NOT EXISTS idx_task_queue_role_status
    ON task_queue (role, status);

-- Index for finding queued tasks by priority
-- Used when selecting the highest priority task to process
CREATE INDEX IF NOT EXISTS idx_task_queue_status_priority
    ON task_queue (status, priority DESC);

-- Index for dependency lookups
-- Used when checking if all dependencies are complete
CREATE INDEX IF NOT EXISTS idx_task_queue_depends_on
    ON task_queue USING GIN (depends_on);

-- Trigger to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_task_queue_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER task_queue_updated_at
    BEFORE UPDATE ON task_queue
    FOR EACH ROW
    EXECUTE FUNCTION update_task_queue_updated_at();

-- Function to check if a task's dependencies are all completed
-- Returns TRUE if task is ready to be dispatched
CREATE OR REPLACE FUNCTION task_dependencies_met(task_id UUID)
RETURNS BOOLEAN AS $$
DECLARE
    dep_ids UUID[];
    incomplete_count INTEGER;
BEGIN
    -- Get the depends_on array for this task
    SELECT depends_on INTO dep_ids
    FROM task_queue
    WHERE id = task_id;

    -- If no dependencies, return true
    IF dep_ids IS NULL OR array_length(dep_ids, 1) IS NULL THEN
        RETURN TRUE;
    END IF;

    -- Count dependencies that are NOT completed
    SELECT COUNT(*) INTO incomplete_count
    FROM task_queue
    WHERE id = ANY(dep_ids)
      AND status != 'completed';

    RETURN incomplete_count = 0;
END;
$$ LANGUAGE plpgsql;

-- Function to get next available task for a role
-- Returns the highest priority queued task with all dependencies met
CREATE OR REPLACE FUNCTION get_next_task_for_role(target_role TEXT)
RETURNS SETOF task_queue AS $$
BEGIN
    RETURN QUERY
    SELECT t.*
    FROM task_queue t
    WHERE t.role = target_role
      AND t.status = 'queued'
      AND task_dependencies_met(t.id)
    ORDER BY t.priority DESC, t.created_at ASC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to get all unblocked tasks (any role)
-- Used by the dispatch endpoint to find tasks ready for processing
CREATE OR REPLACE FUNCTION get_unblocked_tasks()
RETURNS SETOF task_queue AS $$
BEGIN
    RETURN QUERY
    SELECT t.*
    FROM task_queue t
    WHERE t.status = 'queued'
      AND task_dependencies_met(t.id)
    ORDER BY t.priority DESC, t.created_at ASC;
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON TABLE task_queue IS 'Multi-agent task orchestration queue with dependency tracking';
COMMENT ON COLUMN task_queue.role IS 'Agent role to handle this task (e.g., backend-architect-sabine)';
COMMENT ON COLUMN task_queue.depends_on IS 'Array of task IDs that must complete before this task can start';
COMMENT ON COLUMN task_queue.payload IS 'JSON instructions/context for the agent';
COMMENT ON COLUMN task_queue.result IS 'JSON result from successful task completion';
COMMENT ON FUNCTION task_dependencies_met(UUID) IS 'Check if all dependencies for a task are completed';
COMMENT ON FUNCTION get_next_task_for_role(TEXT) IS 'Get highest priority ready task for a specific role';
COMMENT ON FUNCTION get_unblocked_tasks() IS 'Get all tasks ready for dispatch (dependencies met)';
