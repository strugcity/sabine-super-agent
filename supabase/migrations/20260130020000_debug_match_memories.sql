-- Debug version of match_memories - returns ALL memories with calculated similarity
-- This version removes the WHERE clause to see all results

CREATE OR REPLACE FUNCTION match_memories_debug(
    query_embedding text,
    match_count int DEFAULT 10
)
RETURNS TABLE (
    id uuid,
    content text,
    similarity float,
    cast_success boolean
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
        CASE
            WHEN m.embedding IS NOT NULL THEN
                (1 - (m.embedding::vector(1536) <=> query_vec))::float
            ELSE
                NULL::float
        END as similarity,
        m.embedding IS NOT NULL as cast_success
    FROM memories m
    ORDER BY
        CASE
            WHEN m.embedding IS NOT NULL THEN m.embedding::vector(1536) <=> query_vec
            ELSE 999999
        END ASC
    LIMIT match_count;
END;
$$;
