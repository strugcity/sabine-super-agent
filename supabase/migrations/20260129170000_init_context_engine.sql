-- =============================================================================
-- Context Engine V1 - Initial Schema
-- =============================================================================
-- This migration creates the "Monolithic Brain" architecture for Sabine:
-- - Domains: Work, Family, Personal, Logistics
-- - Entities: The "Nouns" (Projects, People, Events)
-- - Memories: Unstructured vector-based context
-- - Tasks: Action items linked to Entities
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Extensions (Ensure Required Extensions are Available)
-- -----------------------------------------------------------------------------

-- Enable pgvector for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- Domains Enum
-- -----------------------------------------------------------------------------
-- Defines the four core context domains for Sabine

CREATE TYPE domain_enum AS ENUM ('work', 'family', 'personal', 'logistics');

COMMENT ON TYPE domain_enum IS 'Core context domains: work, family, personal, logistics';

-- -----------------------------------------------------------------------------
-- Entities Table
-- -----------------------------------------------------------------------------
-- The "Nouns" - Projects, People, Events
-- These are the concrete objects Sabine tracks

CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    type TEXT NOT NULL, -- 'project', 'person', 'event', 'location', etc.
    domain domain_enum NOT NULL,
    attributes JSONB DEFAULT '{}', -- Flexible JSON for entity-specific data
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'archived', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE entities IS 'The Nouns: Projects, People, Events, and other tracked objects';
COMMENT ON COLUMN entities.type IS 'Entity type: project, person, event, location, etc.';
COMMENT ON COLUMN entities.domain IS 'Which domain this entity belongs to';
COMMENT ON COLUMN entities.attributes IS 'Flexible JSONB for entity-specific data (deadlines, relationships, etc.)';
COMMENT ON COLUMN entities.status IS 'Entity lifecycle: active, archived, or deleted';

-- Indexes for efficient queries
CREATE INDEX idx_entities_domain ON entities(domain);
CREATE INDEX idx_entities_type ON entities(type);
CREATE INDEX idx_entities_status ON entities(status);
CREATE INDEX idx_entities_name ON entities(name);
CREATE INDEX idx_entities_attributes ON entities USING gin(attributes);

-- -----------------------------------------------------------------------------
-- Memories Table
-- -----------------------------------------------------------------------------
-- Unstructured context with vector embeddings
-- The "fuzzy" side of the hybrid graph

CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content TEXT NOT NULL,
    embedding vector(1536), -- OpenAI text-embedding-3-small dimension
    entity_links UUID[] DEFAULT '{}', -- Array of entity IDs this memory references
    metadata JSONB DEFAULT '{}', -- Additional context (source, timestamp, etc.)
    importance_score FLOAT DEFAULT 0.5 CHECK (importance_score >= 0 AND importance_score <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE memories IS 'Unstructured context with vector embeddings for semantic search';
COMMENT ON COLUMN memories.embedding IS 'Vector embedding for semantic similarity search (1536 dimensions)';
COMMENT ON COLUMN memories.entity_links IS 'Array of entity UUIDs this memory references';
COMMENT ON COLUMN memories.importance_score IS 'Memory importance (0-1) for retrieval ranking';

-- Index for vector similarity search (using cosine distance)
CREATE INDEX idx_memories_embedding 
    ON memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Index for entity links (using GIN for array containment queries)
CREATE INDEX idx_memories_entity_links ON memories USING gin(entity_links);

-- Index for metadata queries
CREATE INDEX idx_memories_metadata ON memories USING gin(metadata);

-- Index for time-based queries
CREATE INDEX idx_memories_created_at ON memories(created_at DESC);

-- -----------------------------------------------------------------------------
-- Tasks Table
-- -----------------------------------------------------------------------------
-- Action items linked to Entities
-- Part of the structured "knowledge graph" layer

CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    description TEXT,
    entity_id UUID REFERENCES entities(id) ON DELETE SET NULL, -- Optional link to entity
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    priority TEXT DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    due_date TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}', -- Additional task context
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tasks IS 'Action items linked to entities';
COMMENT ON COLUMN tasks.entity_id IS 'Optional link to an entity (project, person, etc.)';
COMMENT ON COLUMN tasks.status IS 'Task lifecycle: pending, in_progress, completed, cancelled';
COMMENT ON COLUMN tasks.priority IS 'Task priority: low, medium, high, urgent';

-- Indexes for efficient queries
CREATE INDEX idx_tasks_entity_id ON tasks(entity_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_due_date ON tasks(due_date) WHERE due_date IS NOT NULL;
CREATE INDEX idx_tasks_priority ON tasks(priority);
CREATE INDEX idx_tasks_metadata ON tasks USING gin(metadata);

-- -----------------------------------------------------------------------------
-- Row Level Security (RLS) Policies
-- -----------------------------------------------------------------------------
-- Supabase requires RLS policies for all tables
-- For now, allowing public access (to be refined in future phases)

-- Enable RLS on all tables
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;

-- Public access policies (permissive for MVP)
-- TODO: Refine these policies with user-based access control in Phase 2

CREATE POLICY "Allow public read access on entities"
    ON entities FOR SELECT
    USING (true);

CREATE POLICY "Allow public insert access on entities"
    ON entities FOR INSERT
    WITH CHECK (true);

CREATE POLICY "Allow public update access on entities"
    ON entities FOR UPDATE
    USING (true);

CREATE POLICY "Allow public delete access on entities"
    ON entities FOR DELETE
    USING (true);

CREATE POLICY "Allow public read access on memories"
    ON memories FOR SELECT
    USING (true);

CREATE POLICY "Allow public insert access on memories"
    ON memories FOR INSERT
    WITH CHECK (true);

CREATE POLICY "Allow public update access on memories"
    ON memories FOR UPDATE
    USING (true);

CREATE POLICY "Allow public delete access on memories"
    ON memories FOR DELETE
    USING (true);

CREATE POLICY "Allow public read access on tasks"
    ON tasks FOR SELECT
    USING (true);

CREATE POLICY "Allow public insert access on tasks"
    ON tasks FOR INSERT
    WITH CHECK (true);

CREATE POLICY "Allow public update access on tasks"
    ON tasks FOR UPDATE
    USING (true);

CREATE POLICY "Allow public delete access on tasks"
    ON tasks FOR DELETE
    USING (true);

-- =============================================================================
-- End of Migration
-- =============================================================================
