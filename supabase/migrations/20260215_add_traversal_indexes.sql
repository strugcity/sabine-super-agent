-- =============================================================================
-- Add composite indexes for traverse_graph() performance
-- =============================================================================
-- The traverse_graph() CTE filters on (entity_id, graph_layer, confidence)
-- simultaneously. The existing single-column indexes don't cover this pattern.
-- These composite indexes allow index-only scans for the traversal WHERE clause.
--
-- Owner: @backend-architect-sabine
-- =============================================================================

-- Composite indexes matching the traversal CTE WHERE clause pattern
CREATE INDEX IF NOT EXISTS idx_er_source_traverse
    ON entity_relationships(source_entity_id, graph_layer, confidence DESC);

CREATE INDEX IF NOT EXISTS idx_er_target_traverse
    ON entity_relationships(target_entity_id, graph_layer, confidence DESC);

-- Drop the now-redundant single-column indexes that are covered by composites
-- (source_entity_id is the leading column of idx_er_source_traverse)
-- NOTE: Keep idx_er_source and idx_er_target as they serve simple FK lookups.
-- Only drop the low-selectivity standalone indexes.
DROP INDEX IF EXISTS idx_er_type;
DROP INDEX IF EXISTS idx_er_layer;
DROP INDEX IF EXISTS idx_er_confidence;
