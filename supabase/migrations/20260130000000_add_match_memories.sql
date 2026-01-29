-- =============================================================================
-- Context Engine Phase 3 - Memory Retrieval Function
-- =============================================================================
-- This migration adds the match_memories function for vector similarity search.
-- It enables the retrieval system to find semantically similar memories based
-- on query embeddings.
--
-- Owner: @backend-architect-sabine
-- Created: 2026-01-30
-- =============================================================================

-- Function: match_memories
-- Purpose: Find memories similar to a query embedding using cosine similarity
-- Returns: Matching memories with similarity scores, ordered by relevance

CREATE OR REPLACE FUNCTION match_memories(
    query_embedding vector(1536),
    match_threshold float DEFAULT 0.5,
    match_count int DEFAULT 10,
    user_id_filter uuid DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    content text,
    embedding vector(1536),
    entity_links uuid[],
    metadata jsonb,
    importance_score float,
    created_at timestamptz,
    updated_at timestamptz,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.id,
        m.content,
        m.embedding,
        m.entity_links,
        m.metadata,
        m.importance_score,
        m.created_at,
        m.updated_at,
        1 - (m.embedding <=> query_embedding) as similarity
    FROM memories m
    WHERE 
        m.embedding IS NOT NULL
        AND 1 - (m.embedding <=> query_embedding) > match_threshold
        -- Optional user_id filtering (for future multi-tenancy)
        AND (user_id_filter IS NULL OR (m.metadata->>'user_id')::uuid = user_id_filter)
    ORDER BY m.embedding <=> query_embedding ASC
    LIMIT match_count;
END;
$$;

COMMENT ON FUNCTION match_memories IS 
'Find memories similar to query embedding using cosine distance. 
Returns memories with similarity score above threshold, ordered by relevance.
Supports optional user_id filtering for multi-tenancy.';

-- =============================================================================
-- Performance Optimization
-- =============================================================================
-- The ivfflat index on memories(embedding) created in the initial migration
-- will accelerate these queries. For production, consider tuning the lists
-- parameter based on the size of your dataset:
-- - Small dataset (<100K): lists = 100
-- - Medium dataset (100K-1M): lists = 1000
-- - Large dataset (>1M): lists = 2000

-- =============================================================================
-- Usage Examples
-- =============================================================================

-- Example 1: Basic similarity search
-- SELECT * FROM match_memories(
--     query_embedding := '[0.1, 0.2, ...]'::vector(1536),
--     match_threshold := 0.7,
--     match_count := 5
-- );

-- Example 2: Search with user filtering
-- SELECT * FROM match_memories(
--     query_embedding := '[0.1, 0.2, ...]'::vector(1536),
--     match_threshold := 0.6,
--     match_count := 10,
--     user_id_filter := '00000000-0000-0000-0000-000000000001'::uuid
-- );

-- Example 3: Get top result with metadata
-- SELECT 
--     content,
--     similarity,
--     metadata->>'source' as source,
--     created_at
-- FROM match_memories(
--     query_embedding := '[0.1, 0.2, ...]'::vector(1536),
--     match_threshold := 0.5,
--     match_count := 1
-- );
