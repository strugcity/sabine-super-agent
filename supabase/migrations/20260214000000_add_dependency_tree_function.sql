-- Add dependency tree fetching function using recursive CTE
-- This eliminates the N+1 query pattern in circular dependency checking
--
-- Features:
-- - get_dependency_tree(): Fetches entire dependency tree in a single query
-- - Uses recursive CTE for efficient traversal
-- - Includes depth limit to prevent infinite loops on corrupted data

-- Function to fetch the complete dependency tree from a set of root tasks
-- Returns all tasks reachable by following depends_on relationships
CREATE OR REPLACE FUNCTION get_dependency_tree(
    start_task_ids UUID[],
    max_depth INTEGER DEFAULT 100
)
RETURNS TABLE (
    task_id UUID,
    status TEXT,
    depends_on UUID[],
    error TEXT,
    depth INTEGER
) AS $$
WITH RECURSIVE dep_tree AS (
    -- Base case: start with provided task IDs
    SELECT
        t.id AS task_id,
        t.status,
        t.depends_on,
        t.error,
        0 AS depth
    FROM task_queue t
    WHERE t.id = ANY(start_task_ids)

    UNION

    -- Recursive case: follow dependencies
    SELECT
        t.id AS task_id,
        t.status,
        t.depends_on,
        t.error,
        dt.depth + 1
    FROM dep_tree dt
    CROSS JOIN LATERAL unnest(dt.depends_on) AS dep_id
    JOIN task_queue t ON t.id = dep_id
    WHERE dt.depth < max_depth
      AND dt.depends_on IS NOT NULL
      AND array_length(dt.depends_on, 1) > 0
)
SELECT DISTINCT ON (dep_tree.task_id)
    dep_tree.task_id,
    dep_tree.status,
    dep_tree.depends_on,
    dep_tree.error,
    dep_tree.depth
FROM dep_tree
ORDER BY dep_tree.task_id, dep_tree.depth;
$$ LANGUAGE sql;

-- Add comment for documentation
COMMENT ON FUNCTION get_dependency_tree(UUID[], INTEGER) IS
    'Fetch complete dependency tree from root tasks using recursive CTE. Returns all reachable tasks with their depth in the tree.';
