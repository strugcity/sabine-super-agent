-- Add pre-dispatch dependency validation functionality
-- This enables checking if a task's dependencies have failed before dispatch
--
-- Features:
-- - check_task_dependencies(): Returns detailed status of a task's dependencies
-- - Distinguishes between: unblocked, has_failed_deps, still_pending

-- Function to check task dependencies with detailed status
-- Returns:
--   is_unblocked: TRUE if all dependencies are completed (task can run)
--   has_failed_deps: TRUE if any dependency has failed (task should be failed)
--   failed_dep_ids: Array of failed dependency IDs (for error messages)
--   pending_dep_count: Number of dependencies still pending
CREATE OR REPLACE FUNCTION check_task_dependencies(target_task_id UUID)
RETURNS TABLE (
    is_unblocked BOOLEAN,
    has_failed_deps BOOLEAN,
    failed_dep_ids UUID[],
    pending_dep_count INTEGER
) AS $$
DECLARE
    dep_ids UUID[];
    completed_count INTEGER;
    failed_count INTEGER;
    total_count INTEGER;
    failed_ids UUID[];
BEGIN
    -- Get the depends_on array for this task
    SELECT depends_on INTO dep_ids
    FROM task_queue
    WHERE id = target_task_id;

    -- If no dependencies, task is unblocked
    IF dep_ids IS NULL OR array_length(dep_ids, 1) IS NULL THEN
        RETURN QUERY SELECT TRUE, FALSE, ARRAY[]::UUID[], 0;
        RETURN;
    END IF;

    total_count := array_length(dep_ids, 1);

    -- Count completed dependencies
    SELECT COUNT(*) INTO completed_count
    FROM task_queue
    WHERE id = ANY(dep_ids)
      AND status = 'completed';

    -- Count and collect failed dependencies
    SELECT COUNT(*), ARRAY_AGG(id) INTO failed_count, failed_ids
    FROM task_queue
    WHERE id = ANY(dep_ids)
      AND status = 'failed';

    -- Handle NULL from ARRAY_AGG when no failed deps
    IF failed_ids IS NULL THEN
        failed_ids := ARRAY[]::UUID[];
    END IF;

    -- Return results
    -- is_unblocked: all deps completed
    -- has_failed_deps: any dep failed
    -- failed_dep_ids: list of failed dep IDs
    -- pending_dep_count: deps that are neither completed nor failed
    RETURN QUERY SELECT
        completed_count = total_count,           -- is_unblocked
        failed_count > 0,                        -- has_failed_deps
        failed_ids,                              -- failed_dep_ids
        total_count - completed_count - failed_count;  -- pending_dep_count
END;
$$ LANGUAGE plpgsql;

-- Function to validate and potentially fail a task before dispatch
-- If any dependencies are failed, this returns FALSE and the task should be failed
-- Returns: TRUE if task is valid for dispatch, FALSE if it should be failed
CREATE OR REPLACE FUNCTION validate_task_for_dispatch(target_task_id UUID)
RETURNS TABLE (
    is_valid BOOLEAN,
    should_fail BOOLEAN,
    failed_dep_id UUID,
    failed_dep_role TEXT,
    failed_dep_error TEXT
) AS $$
DECLARE
    dep_ids UUID[];
    failed_dep RECORD;
BEGIN
    -- Get the depends_on array for this task
    SELECT depends_on INTO dep_ids
    FROM task_queue
    WHERE id = target_task_id;

    -- If no dependencies, task is valid
    IF dep_ids IS NULL OR array_length(dep_ids, 1) IS NULL THEN
        RETURN QUERY SELECT TRUE, FALSE, NULL::UUID, NULL::TEXT, NULL::TEXT;
        RETURN;
    END IF;

    -- Check for any failed dependencies
    SELECT t.id, t.role, LEFT(t.error, 200)
    INTO failed_dep
    FROM task_queue t
    WHERE t.id = ANY(dep_ids)
      AND t.status = 'failed'
    LIMIT 1;

    IF FOUND THEN
        -- Task has a failed dependency - should be failed
        RETURN QUERY SELECT
            FALSE,                          -- is_valid
            TRUE,                           -- should_fail
            failed_dep.id,                  -- failed_dep_id
            failed_dep.role,                -- failed_dep_role
            failed_dep.left;                -- failed_dep_error
    ELSE
        -- No failed dependencies - task is valid
        RETURN QUERY SELECT TRUE, FALSE, NULL::UUID, NULL::TEXT, NULL::TEXT;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON FUNCTION check_task_dependencies(UUID) IS
    'Check detailed dependency status for a task (unblocked, failed deps, pending count)';
COMMENT ON FUNCTION validate_task_for_dispatch(UUID) IS
    'Validate a task before dispatch - returns FALSE if any dependency has failed';
