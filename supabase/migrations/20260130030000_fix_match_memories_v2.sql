-- =============================================================================
-- Fix v2: match_memories function with proper vector handling
-- =============================================================================
-- Previous version had issues with per-row vector casting.
-- This version uses a CTE to pre-compute similarities.
-- =============================================================================

DROP FUNCTION IF EXISTS match_memories(text, float, int, uuid);

CREATE OR REPLACE FUNCTION match_memories(
    query_embedding text,
    match_threshold float DEFAULT 0.5,
    match_count int DEFAULT 10,
    user_id_filter uuid DEFAULT NULL
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
    ORDER BY sm.sim_score DESC
    LIMIT match_count;
END;
$$;

COMMENT ON FUNCTION match_memories IS
'Find memories similar to query embedding using cosine similarity.
Uses CTE for reliable per-row vector casting.
Returns memories with similarity > threshold, ordered by relevance (descending).';
