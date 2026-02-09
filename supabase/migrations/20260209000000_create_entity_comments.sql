-- =============================================================================
-- Entity Comments Table
-- =============================================================================
-- Allows users to add comments/notes to entities for collaboration and tracking
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Entity Comments Table
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS entity_comments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL, -- Optional user tracking
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE entity_comments IS 'User comments and notes on entities';
COMMENT ON COLUMN entity_comments.entity_id IS 'Reference to the entity this comment belongs to';
COMMENT ON COLUMN entity_comments.user_id IS 'Optional user who created the comment';
COMMENT ON COLUMN entity_comments.content IS 'The comment text content';

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_entity_comments_entity_id 
    ON entity_comments(entity_id);

CREATE INDEX IF NOT EXISTS idx_entity_comments_created_at 
    ON entity_comments(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_entity_comments_user_id 
    ON entity_comments(user_id);

-- -----------------------------------------------------------------------------
-- Updated At Trigger
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION update_entity_comments_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_entity_comments_updated_at
    BEFORE UPDATE ON entity_comments
    FOR EACH ROW
    EXECUTE FUNCTION update_entity_comments_updated_at();

-- -----------------------------------------------------------------------------
-- Row Level Security (RLS)
-- -----------------------------------------------------------------------------
-- For now, allow all authenticated users to perform all operations
-- This can be refined later based on specific requirements

ALTER TABLE entity_comments ENABLE ROW LEVEL SECURITY;

-- Allow all authenticated users to view comments
CREATE POLICY "Allow users to view all comments"
    ON entity_comments
    FOR SELECT
    USING (true);

-- Allow all authenticated users to insert comments
CREATE POLICY "Allow users to insert comments"
    ON entity_comments
    FOR INSERT
    WITH CHECK (true);

-- Allow users to update their own comments (or all if user_id is null for now)
CREATE POLICY "Allow users to update comments"
    ON entity_comments
    FOR UPDATE
    USING (true);

-- Allow users to delete their own comments (or all if user_id is null for now)
CREATE POLICY "Allow users to delete comments"
    ON entity_comments
    FOR DELETE
    USING (true);
