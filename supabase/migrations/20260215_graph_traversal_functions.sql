-- =============================================================================
-- Graph Traversal Functions for MAGMA-005 (v2 - Bidirectional + Cycle Prevention)
-- =============================================================================
-- This migration replaces the traverse_graph() function with an improved version
-- that supports:
--
-- 1. Bidirectional traversal (follow edges in both directions)
-- 2. Cycle prevention via visited-node tracking (UUID array)
-- 3. Filtering by relationship_type, graph_layer, and min confidence
-- 4. Performance target: <200ms for 3-hop traversals on 10k relationships
--
-- Depends on:
--   - entity_relationships table (from p2-magma-taxonomy session)
--   - entities table (from 20260129170000_init_context_engine.sql)
--
-- Owner: @backend-architect-sabine
-- PRD Reference: MAGMA-005 - Cross-Graph Traversal API
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. traverse_graph() - Bidirectional recursive multi-hop graph traversal
-- -----------------------------------------------------------------------------
-- Traverses the entity_relationships table starting from a given entity,
-- following edges in BOTH directions up to max_depth hops.
-- Uses a visited UUID array to prevent cycles.
--
-- Parameters:
--   start_entity_id         UUID    - The entity to start traversal from
--   max_depth               INT     - Maximum number of hops (default: 3)
--   relationship_type_filter TEXT   - Filter by relationship type (NULL = all)
--   layer_filter            TEXT    - Filter by graph layer (NULL = all)
--   min_confidence          FLOAT   - Minimum confidence threshold (default: 0.0)
--   max_results             INT     - Maximum number of rows returned (default: 500)
--
-- Returns:
--   source_id, target_id, source_name, target_name,
--   relationship_type, graph_layer, confidence, hop

CREATE OR REPLACE FUNCTION traverse_graph(
    start_entity_id UUID,
    max_depth INT DEFAULT 3,
    relationship_type_filter TEXT DEFAULT NULL,
    layer_filter TEXT DEFAULT NULL,
    min_confidence FLOAT DEFAULT 0.0,
    max_results INT DEFAULT 500
)
RETURNS TABLE (
    source_id UUID,
    target_id UUID,
    source_name TEXT,
    target_name TEXT,
    relationship_type TEXT,
    graph_layer TEXT,
    confidence FLOAT,
    hop INT
) AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE traverse AS (
        -- Base case: direct OUTGOING relationships from start entity
        SELECT
            er.source_entity_id AS src_id,
            er.target_entity_id AS tgt_id,
            e1.name AS src_name,
            e2.name AS tgt_name,
            er.relationship_type AS rel_type,
            er.graph_layer AS g_layer,
            er.confidence AS conf,
            1 AS depth,
            ARRAY[start_entity_id, er.target_entity_id] AS visited
        FROM entity_relationships er
        JOIN entities e1 ON er.source_entity_id = e1.id
        JOIN entities e2 ON er.target_entity_id = e2.id
        WHERE er.source_entity_id = start_entity_id
            AND er.confidence >= min_confidence
            AND (relationship_type_filter IS NULL OR er.relationship_type = relationship_type_filter)
            AND (layer_filter IS NULL OR er.graph_layer = layer_filter)

        UNION ALL

        -- Base case: direct INCOMING relationships to start entity
        SELECT
            er.source_entity_id AS src_id,
            er.target_entity_id AS tgt_id,
            e1.name AS src_name,
            e2.name AS tgt_name,
            er.relationship_type AS rel_type,
            er.graph_layer AS g_layer,
            er.confidence AS conf,
            1 AS depth,
            ARRAY[start_entity_id, er.source_entity_id] AS visited
        FROM entity_relationships er
        JOIN entities e1 ON er.source_entity_id = e1.id
        JOIN entities e2 ON er.target_entity_id = e2.id
        WHERE er.target_entity_id = start_entity_id
            AND er.confidence >= min_confidence
            AND (relationship_type_filter IS NULL OR er.relationship_type = relationship_type_filter)
            AND (layer_filter IS NULL OR er.graph_layer = layer_filter)

        UNION ALL

        -- Recursive case: follow OUTGOING edges from discovered targets
        -- Cycle prevention: only visit nodes not already in the visited array
        SELECT
            er.source_entity_id AS src_id,
            er.target_entity_id AS tgt_id,
            e1.name,
            e2.name,
            er.relationship_type,
            er.graph_layer,
            er.confidence,
            t.depth + 1,
            t.visited || er.target_entity_id
        FROM entity_relationships er
        JOIN traverse t ON er.source_entity_id = t.tgt_id
        JOIN entities e1 ON er.source_entity_id = e1.id
        JOIN entities e2 ON er.target_entity_id = e2.id
        WHERE t.depth < max_depth
            AND er.confidence >= min_confidence
            AND NOT (er.target_entity_id = ANY(t.visited))
            AND (relationship_type_filter IS NULL OR er.relationship_type = relationship_type_filter)
            AND (layer_filter IS NULL OR er.graph_layer = layer_filter)

        UNION ALL

        -- Recursive case: follow INCOMING edges from discovered sources
        -- Cycle prevention: only visit nodes not already in the visited array
        SELECT
            er.source_entity_id AS src_id,
            er.target_entity_id AS tgt_id,
            e1.name,
            e2.name,
            er.relationship_type,
            er.graph_layer,
            er.confidence,
            t.depth + 1,
            t.visited || er.source_entity_id
        FROM entity_relationships er
        JOIN traverse t ON er.target_entity_id = t.src_id
        JOIN entities e1 ON er.source_entity_id = e1.id
        JOIN entities e2 ON er.target_entity_id = e2.id
        WHERE t.depth < max_depth
            AND er.confidence >= min_confidence
            AND NOT (er.source_entity_id = ANY(t.visited))
            AND (relationship_type_filter IS NULL OR er.relationship_type = relationship_type_filter)
            AND (layer_filter IS NULL OR er.graph_layer = layer_filter)
    )
    SELECT DISTINCT
        traverse.src_id,
        traverse.tgt_id,
        traverse.src_name,
        traverse.tgt_name,
        traverse.rel_type,
        traverse.g_layer,
        traverse.conf,
        traverse.depth
    FROM traverse
    ORDER BY traverse.depth, traverse.conf DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION traverse_graph(UUID, INT, TEXT, TEXT, FLOAT, INT) IS
    'Bidirectional recursive multi-hop graph traversal with cycle prevention, optional filters for relationship type, layer, and confidence, and max_results limit';


-- =============================================================================
-- End of Graph Traversal Functions Migration (v2)
-- =============================================================================
