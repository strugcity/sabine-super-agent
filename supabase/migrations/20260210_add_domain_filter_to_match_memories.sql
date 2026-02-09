-- =============================================================================
-- Add domain_filter parameter to match_memories function
-- =============================================================================
-- This migration adds domain-based filtering to memory retrieval to enable
-- compartmentalization of work vs personal knowledge in Sabine's memory system.
--
-- Key features:
-- 1. Adds optional domain_filter parameter (defaults to NULL for backward compat)
-- 2. When domain_filter IS NOT NULL, filters to:
--    - Memories where metadata->'domain' = domain_filter OR
--    - Memories where metadata->'domain' IS NULL (legacy memories)
-- 3. When domain_filter IS NULL, returns all memories (backward compatible)
--
-- Domain values: work, family, personal, logistics (defined in DomainEnum)
-- =============================================================================

-- Drop both old and new function signatures to ensure clean replacement
DROP FUNCTION IF EXISTS match_memories(text, float, int, uuid, text);
DROP FUNCTION IF EXISTS match_memories(text, float, int, uuid, text, text);

CREATE OR REPLACE FUNCTION match_memories(
    query_embedding text,
    match_threshold float DEFAULT 0.5,
    match_count int DEFAULT 10,
    user_id_filter uuid DEFAULT NULL,
    role_filter text DEFAULT NULL,
    domain_filter text DEFAULT NULL
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
        -- Domain filtering: if domain_filter is provided, only return memories
        -- that match the domain OR have no domain set (backward compatibility)
        AND (
            domain_filter IS NULL OR
            (sm.metadata->>'domain' = domain_filter) OR
            (sm.metadata->>'domain' IS NULL)
        )
    ORDER BY sm.sim_score DESC
    LIMIT match_count;
END;
$$;

COMMENT ON FUNCTION match_memories IS
'Find memories similar to query embedding using cosine similarity.
Uses CTE for reliable per-row vector casting.
Supports optional role filtering to prevent memory bleed across agent types.
Supports optional domain filtering to compartmentalize work vs personal knowledge.
When domain_filter is provided, returns only memories matching that domain or legacy memories with no domain.
Returns memories with similarity > threshold, ordered by relevance (descending).';
