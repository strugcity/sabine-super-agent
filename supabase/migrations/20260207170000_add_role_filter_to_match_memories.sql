-- =============================================================================
-- Add role_filter parameter to match_memories function
-- =============================================================================
-- This migration adds role-based filtering to memory retrieval to prevent
-- memory bleed across different agent types (Sabine vs. Dream Team coding agents).
--
-- Key features:
-- 1. Adds optional role_filter parameter (defaults to NULL for backward compat)
-- 2. When role_filter IS NOT NULL, filters to:
--    - Memories where metadata->'role' = role_filter OR
--    - Memories where metadata->'role' IS NULL (legacy memories)
-- 3. When role_filter IS NULL, returns all memories (backward compatible)
--
-- TODO: After migration window, consider backfilling all NULL role memories with
-- role="assistant" and removing the NULL clause to prevent future leak paths.
-- =============================================================================

-- Drop both old and new function signatures to ensure clean replacement
DROP FUNCTION IF EXISTS match_memories(text, float, int, uuid);
DROP FUNCTION IF EXISTS match_memories(text, float, int, uuid, text);

CREATE OR REPLACE FUNCTION match_memories(
    query_embedding text,
    match_threshold float DEFAULT 0.5,
    match_count int DEFAULT 10,
    user_id_filter uuid DEFAULT NULL,
    role_filter text DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    content text,
    embedding text,
    entity_links uuid[],
    metadata jsonb,
    importance_score float,
    created_at timestamptz,
    updated_at timestamptz,
    similarity float
)
LANGUAGE plpgsql
AS $$
DECLARE
    query_vec vector(1536);
BEGIN
    -- Cast the input text to vector once
    query_vec := query_embedding::vector(1536);

    RETURN QUERY
    WITH scored_memories AS (
        SELECT
            m.id,
            m.content,
            m.embedding,
            m.entity_links,
            m.metadata,
            m.importance_score,
            m.created_at,
            m.updated_at,
            (1.0 - (m.embedding::vector(1536) <=> query_vec)) as sim_score
        FROM memories m
        WHERE m.embedding IS NOT NULL
    )
    SELECT
        sm.id,
        sm.content,
        sm.embedding::text,
        sm.entity_links,
        sm.metadata,
        sm.importance_score,
        sm.created_at,
        sm.updated_at,
        sm.sim_score::float as similarity
    FROM scored_memories sm
    WHERE sm.sim_score > match_threshold
        AND (user_id_filter IS NULL OR (sm.metadata->>'user_id')::uuid = user_id_filter)
        -- Role filtering: if role_filter is provided, only return memories
        -- that match the role OR have no role set (backward compatibility)
        AND (
            role_filter IS NULL OR
            (sm.metadata->>'role' = role_filter) OR
            (sm.metadata->>'role' IS NULL)
        )
    ORDER BY sm.sim_score DESC
    LIMIT match_count;
END;
$$;

COMMENT ON FUNCTION match_memories IS
'Find memories similar to query embedding using cosine similarity.
Uses CTE for reliable per-row vector casting.
Supports optional role filtering to prevent memory bleed across agent types.
When role_filter is provided, returns only memories matching that role or legacy memories with no role.
Returns memories with similarity > threshold, ordered by relevance (descending).';
