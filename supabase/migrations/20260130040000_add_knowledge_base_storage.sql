-- ============================================================================
-- Migration: Add Knowledge Base Storage Bucket
-- Context Engine - File Ingestion Pipeline
-- ============================================================================

-- Insert a Storage Bucket named "knowledge_base" for file uploads
-- Note: This migration uses the storage schema which Supabase provides

-- Create the knowledge_base bucket
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'knowledge_base',
    'knowledge_base',
    false,  -- Private bucket (requires auth)
    52428800,  -- 50MB max file size
    ARRAY[
        'application/pdf',
        'text/csv',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'text/plain',
        'application/json'
    ]::text[]
)
ON CONFLICT (id) DO UPDATE SET
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

-- ============================================================================
-- Storage Policies - Allow authenticated access
-- ============================================================================

-- Policy: Allow authenticated users to upload files
CREATE POLICY "Allow authenticated uploads to knowledge_base"
ON storage.objects
FOR INSERT
TO authenticated
WITH CHECK (bucket_id = 'knowledge_base');

-- Policy: Allow authenticated users to read files
CREATE POLICY "Allow authenticated reads from knowledge_base"
ON storage.objects
FOR SELECT
TO authenticated
USING (bucket_id = 'knowledge_base');

-- Policy: Allow authenticated users to update files
CREATE POLICY "Allow authenticated updates to knowledge_base"
ON storage.objects
FOR UPDATE
TO authenticated
USING (bucket_id = 'knowledge_base');

-- Policy: Allow authenticated users to delete files
CREATE POLICY "Allow authenticated deletes from knowledge_base"
ON storage.objects
FOR DELETE
TO authenticated
USING (bucket_id = 'knowledge_base');

-- ============================================================================
-- Service Role Access (for backend API)
-- ============================================================================

-- Policy: Allow service role full access (for backend processing)
CREATE POLICY "Allow service role full access to knowledge_base"
ON storage.objects
FOR ALL
TO service_role
USING (bucket_id = 'knowledge_base')
WITH CHECK (bucket_id = 'knowledge_base');

-- ============================================================================
-- Metadata Table for Uploaded Files
-- ============================================================================

-- Track uploaded files and their processing status
CREATE TABLE IF NOT EXISTS knowledge_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- File information
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,  -- Path in storage bucket
    file_size BIGINT NOT NULL,
    mime_type TEXT NOT NULL,

    -- Processing status
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    error_message TEXT,

    -- Extracted content
    extracted_text TEXT,
    extracted_at TIMESTAMP WITH TIME ZONE,

    -- Memory linkage (which memory was created from this file)
    memory_id UUID REFERENCES memories(id) ON DELETE SET NULL,

    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for status queries
CREATE INDEX IF NOT EXISTS idx_knowledge_files_status ON knowledge_files(status);

-- Index for file lookups
CREATE INDEX IF NOT EXISTS idx_knowledge_files_file_path ON knowledge_files(file_path);

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_knowledge_files_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_knowledge_files_updated_at
    BEFORE UPDATE ON knowledge_files
    FOR EACH ROW
    EXECUTE FUNCTION update_knowledge_files_updated_at();

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE knowledge_files IS 'Tracks uploaded files for the Context Engine file ingestion pipeline';
COMMENT ON COLUMN knowledge_files.file_path IS 'Path in the knowledge_base storage bucket';
COMMENT ON COLUMN knowledge_files.status IS 'Processing status: pending, processing, completed, failed';
COMMENT ON COLUMN knowledge_files.extracted_text IS 'Text content extracted from the file';
COMMENT ON COLUMN knowledge_files.memory_id IS 'Reference to the memory created from this file content';
