-- =============================================================================
-- MAGMA Graph Layer: entity_relationships Table
-- =============================================================================
-- Creates the entity_relationships table for persisting extracted
-- relationship triples (subject, predicate, object) between entities.
--
-- Part of the Four-Layer Graph Architecture (PRD 11.2):
--   - entity:   Direct entity-to-entity structural relations
--   - semantic: Meaning/topic relationships
--   - temporal: Time-based sequential relations
--   - causal:   Cause-effect reasoning chains
--
-- Depends on:
--   - 20260129170000_init_context_engine.sql  (entities table)
--
-- Owner: @backend-architect-sabine
-- PRD Reference: Phase 1 - MAGMA Relationship Taxonomy (PRD 11.2)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. CREATE entity_relationships TABLE
-- -----------------------------------------------------------------------------

CREATE TABLE entity_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- ON DELETE SET NULL: if an entity is removed, relationships are preserved
    -- with a NULL reference rather than silently cascade-deleted.
    -- Application code handles cleanup via the entity status column.
    source_entity_id UUID REFERENCES entities(id) ON DELETE SET NULL,
    target_entity_id UUID REFERENCES entities(id) ON DELETE SET NULL,
    relationship_type TEXT NOT NULL,              -- snake_case predicate
    graph_layer TEXT NOT NULL DEFAULT 'entity',   -- entity|semantic|temporal|causal
    confidence FLOAT NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    source_wal_id UUID,                          -- Provenance: which WAL entry created this
    metadata JSONB DEFAULT '{}',                 -- Flexible extra data
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Prevent exact duplicate relationships
    UNIQUE(source_entity_id, target_entity_id, relationship_type)
);

COMMENT ON TABLE entity_relationships IS 'MAGMA graph layer: stores relationship triples between entities';
COMMENT ON COLUMN entity_relationships.source_entity_id IS 'Subject entity UUID (FK to entities.id)';
COMMENT ON COLUMN entity_relationships.target_entity_id IS 'Object entity UUID (FK to entities.id)';
COMMENT ON COLUMN entity_relationships.relationship_type IS 'Snake_case predicate (e.g. works_at, lives_in)';
COMMENT ON COLUMN entity_relationships.graph_layer IS 'Graph layer: entity, semantic, temporal, or causal';
COMMENT ON COLUMN entity_relationships.confidence IS 'Confidence score (0.0 - 1.0) from extraction';
COMMENT ON COLUMN entity_relationships.source_wal_id IS 'WAL entry that produced this relationship (provenance)';
COMMENT ON COLUMN entity_relationships.metadata IS 'Flexible JSONB for extra relationship data';


-- -----------------------------------------------------------------------------
-- 2. PERFORMANCE INDEXES for graph traversal
-- -----------------------------------------------------------------------------

-- Single-column indexes for filtered lookups
CREATE INDEX idx_er_source ON entity_relationships(source_entity_id);
CREATE INDEX idx_er_target ON entity_relationships(target_entity_id);
CREATE INDEX idx_er_type ON entity_relationships(relationship_type);
CREATE INDEX idx_er_layer ON entity_relationships(graph_layer);
CREATE INDEX idx_er_confidence ON entity_relationships(confidence DESC);

-- Composite indexes for traversal queries
CREATE INDEX idx_er_source_type ON entity_relationships(source_entity_id, relationship_type);
CREATE INDEX idx_er_target_type ON entity_relationships(target_entity_id, relationship_type);


-- -----------------------------------------------------------------------------
-- 3. CHECK CONSTRAINT for valid graph layers
-- -----------------------------------------------------------------------------

ALTER TABLE entity_relationships
    ADD CONSTRAINT chk_graph_layer
    CHECK (graph_layer IN ('entity', 'semantic', 'temporal', 'causal'));


-- -----------------------------------------------------------------------------
-- 4. ROW LEVEL SECURITY
-- -----------------------------------------------------------------------------
-- Service role has full access; no public access to relationship data.

ALTER TABLE entity_relationships ENABLE ROW LEVEL SECURITY;

-- Drop legacy permissive policies if they exist
DROP POLICY IF EXISTS "Allow public read access on entity_relationships" ON entity_relationships;
DROP POLICY IF EXISTS "Allow public insert access on entity_relationships" ON entity_relationships;
DROP POLICY IF EXISTS "Allow public update access on entity_relationships" ON entity_relationships;
DROP POLICY IF EXISTS "Allow public delete access on entity_relationships" ON entity_relationships;

-- Service role: full CRUD access
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'entity_relationships'
          AND policyname = 'er_service_role_all'
    ) THEN
        CREATE POLICY er_service_role_all
            ON entity_relationships
            FOR ALL
            TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END;
$$;


-- -----------------------------------------------------------------------------
-- 5. updated_at TRIGGER
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION update_entity_relationships_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_entity_relationships_updated'
    ) THEN
        CREATE TRIGGER trg_entity_relationships_updated
            BEFORE UPDATE ON entity_relationships
            FOR EACH ROW
            EXECUTE FUNCTION update_entity_relationships_timestamp();
    END IF;
END;
$$;

COMMENT ON FUNCTION update_entity_relationships_timestamp()
    IS 'Auto-updates entity_relationships.updated_at on row modification';


-- =============================================================================
-- End of Migration
-- =============================================================================
