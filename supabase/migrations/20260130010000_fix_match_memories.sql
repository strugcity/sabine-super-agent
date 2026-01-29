-- =============================================================================
-- Fix: match_memories function with TEXT to VECTOR casting
-- =============================================================================
-- The embeddings are stored as TEXT (JSON array format) but need to be
-- cast to vector(1536) for cosine similarity calculations.
-- =============================================================================

-- Drop existing function first
DROP FUNCTION IF EXISTS match_memories(vector(1536), float, int, uuid);

-- Recreate with text input (more flexible for RPC calls)
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
    -- Cast the input text to vector
    query_vec := query_embedding::vector(1536);

    RETURN QUERY
    SELECT
        m.id,
        m.content,
        m.embedding::text,
        m.entity_links,
        m.metadata,
        m.importance_score,
        m.created_at,
        m.updated_at,
        (1 - (m.embedding::vector(1536) <=> query_vec))::float as similarity
    FROM memories m
    WHERE
        m.embedding IS NOT NULL
        AND (1 - (m.embedding::vector(1536) <=> query_vec)) > match_threshold
        AND (user_id_filter IS NULL OR (m.metadata->>'user_id')::uuid = user_id_filter)
    ORDER BY m.embedding::vector(1536) <=> query_vec ASC
    LIMIT match_count;
END;
$$;

COMMENT ON FUNCTION match_memories IS
'Find memories similar to query embedding using cosine distance.
Handles TEXT-stored embeddings by casting to vector(1536).
Returns memories with similarity score above threshold, ordered by relevance.';
