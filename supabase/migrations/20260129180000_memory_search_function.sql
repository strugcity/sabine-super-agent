-- =============================================================================
-- Memory Vector Search Function
-- =============================================================================
-- This migration adds a PostgreSQL function for semantic memory search using
-- pgvector cosine similarity. This enables the search_memories_by_similarity
-- function in lib/agent/memory.py.
--
-- Owner: @backend-architect-sabine
-- Created: 2026-01-29
-- =============================================================================

-- Function: search_memories
-- Purpose: Find memories similar to a query embedding using cosine distance
-- Returns: Matching memories ordered by similarity (most similar first)

CREATE OR REPLACE FUNCTION search_memories(
    query_embedding vector(1536),
    match_threshold float DEFAULT 0.3,
    match_count int DEFAULT 5
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
    WHERE m.embedding IS NOT NULL
        AND 1 - (m.embedding <=> query_embedding) > match_threshold
    ORDER BY m.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

COMMENT ON FUNCTION search_memories IS 
'Search memories by vector similarity using cosine distance. Returns memories with similarity score above threshold.';

-- =============================================================================
-- Example Usage
-- =============================================================================
-- SELECT * FROM search_memories(
--     query_embedding := '[0.1, 0.2, ...]'::vector(1536),
--     match_threshold := 0.7,
--     match_count := 10
-- );
