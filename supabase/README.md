# Supabase Database Schema

This directory contains the database schema for the Personal Super Agent V1.

## Schema Overview

The database implements the **Dual-Brain Memory** architecture:

1. **Vector Store** (Fuzzy Memory)
   - `memories` table with pgvector embeddings
   - Semantic search for notes and observations

2. **Knowledge Graph** (Strict Logic)
   - `users`, `user_identities`, `user_config`
   - `rules`, `custody_schedule`
   - `conversation_state`, `conversation_history`

## Tables

### Core Tables
- **users** - User accounts with roles and timezone
- **user_identities** - Multi-channel identities (Twilio, email, Slack, web)
- **user_config** - Key-value settings per user

### Memory & Logic
- **memories** - Vector embeddings for semantic search (pgvector)
- **rules** - Deterministic triggers and actions
- **custody_schedule** - Family logistics knowledge graph

### Conversation Tracking
- **conversation_state** - Active LangGraph sessions
- **conversation_history** - Full audit trail

## How to Apply the Schema

### Option 1: Supabase Dashboard (Recommended for First Time)

1. Go to your Supabase project dashboard
2. Navigate to **SQL Editor** in the left sidebar
3. Click **New Query**
4. Copy the entire contents of `schema.sql`
5. Paste into the editor
6. Click **Run** (or press Cmd/Ctrl + Enter)

### Option 2: Command Line with psql

If you have PostgreSQL client tools installed:

```bash
# From the project root directory
psql "$DATABASE_URL" < supabase/schema.sql
```

Where `$DATABASE_URL` is from your `.env` file in the format:
```
postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
```

### Option 3: Using Supabase CLI

If you have the Supabase CLI installed:

```bash
# Link to your project (first time only)
supabase link --project-ref your-project-ref

# Apply the schema
supabase db push
```

## Verifying the Schema

After running the schema, verify it was created successfully:

```sql
-- Check that pgvector is enabled
SELECT * FROM pg_extension WHERE extname = 'vector';

-- List all tables
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;

-- Check row counts (should be 0 for new schema)
SELECT
    schemaname,
    tablename,
    n_live_tup as row_count
FROM pg_stat_user_tables
ORDER BY tablename;
```

## Next Steps

After applying the schema:

1. **Create a test user** (optional)
   ```sql
   INSERT INTO users (role, name, timezone)
   VALUES ('admin', 'Test User', 'America/New_York')
   RETURNING id;
   ```

2. **Add a user identity** (optional)
   ```sql
   INSERT INTO user_identities (user_id, provider, identifier, is_primary, verified)
   VALUES ('[USER_ID]', 'twilio', '+1234567890', true, true);
   ```

3. **Update your `.env` file** with Supabase credentials:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `DATABASE_URL`

4. **Test the connection** from Python:
   ```python
   from supabase import create_client
   import os

   supabase = create_client(
       os.getenv("SUPABASE_URL"),
       os.getenv("SUPABASE_SERVICE_ROLE_KEY")
   )

   # Test query
   result = supabase.table("users").select("*").execute()
   print(result.data)
   ```

## Schema Modifications

When making changes to the schema:

1. Update `schema.sql` with your changes
2. Create a migration file in `supabase/migrations/` (if using Supabase CLI)
3. Test in a development environment first
4. Apply to production

## Important Notes

- **pgvector Extension**: Must be enabled before creating the memories table
- **RLS Policies**: Currently permissive for development. Implement proper RLS before production!
- **Indexes**: The vector index uses IVFFlat. For large datasets, consider adjusting the `lists` parameter
- **Embedding Dimension**: Currently set to 1536 (OpenAI text-embedding-3-small). Change if using different models
