-- =============================================================================
-- Add trigram index for entity name fuzzy search (Phase 2D performance fix)
-- =============================================================================
-- Addresses DoS vector in entity name resolution by enabling efficient
-- fuzzy text search without full table scans.
--
-- Security: Prevents wildcard DoS attacks (e.g., '%%%%') from causing
--           full table scans on the entities table.
-- Performance: Enables fast ILIKE queries with leading wildcards.
-- =============================================================================

-- Add GIN trigram index for efficient fuzzy text search on entity names
-- Note: pg_trgm extension is already enabled in migration 20260216000001
CREATE INDEX IF NOT EXISTS idx_entities_name_trigram
    ON entities USING gin(name gin_trgm_ops);

COMMENT ON INDEX idx_entities_name_trigram IS 'GIN trigram index for efficient fuzzy text search on entity names (prevents wildcard DoS)';
