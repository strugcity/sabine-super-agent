# Memory Ingestion Pipeline - Documentation

**Phase 2: Context Engine**  
**Owner:** @backend-architect-sabine  
**Status:** ✅ Implementation Complete

## Overview

The Memory Ingestion Pipeline implements **Feature A: The Active Listener** from the Context Engine PRD. It transforms raw user messages into structured knowledge stored in Supabase.

## Architecture

```
User Message
    ↓
[1] Generate Embedding (text-embedding-3-small)
    ↓
[2] Extract Entities (GPT-4o)
    ↓
[3] Fuzzy Match & Merge/Create Entities
    ↓
[4] Store Memory with Entity Links
    ↓
Result: Structured Knowledge Graph Entry
```

## Core Components

### 1. `extract_context(text: str) -> ExtractedContext`

**Purpose:** Use GPT-4o to analyze text and extract structured data.

**Output Schema:**
```python
{
    "extracted_entities": [
        {
            "name": "Baseball Game",
            "type": "event",
            "domain": "family",
            "attributes": {"time": "5 PM", "day": "Saturday"}
        }
    ],
    "core_memory": "Baseball game rescheduled to 5 PM on Saturday",
    "domain": "family"
}
```

**Model:** GPT-4o (temp=0.0 for deterministic extraction)

### 2. `ingest_user_message(user_id, content, source) -> Dict`

**Purpose:** Main entry point - orchestrates the complete pipeline.

**Steps:**
1. Generate 1536-dim embedding via `text-embedding-3-small`
2. Extract entities and context via LLM
3. For each entity:
   - Fuzzy match existing entity (ILIKE on name + exact type/domain)
   - If exists: Merge attributes (JSONB merge)
   - If new: Insert row
4. Insert memory linked to entity IDs

**Returns:**
```python
{
    "status": "success",
    "memory_id": "uuid",
    "entities_created": 2,
    "entities_updated": 1,
    "entity_ids": ["uuid1", "uuid2"],
    "processing_time_ms": 1234
}
```

### 3. Entity Management Functions

- `find_similar_entity()` - Case-insensitive fuzzy match using PostgreSQL ILIKE
- `merge_entity_attributes()` - Smart JSONB merge (new overwrites, no deletions)
- `create_entity()` - Insert new entity row

### 4. Memory Storage

- `store_memory()` - Insert memory with embedding and entity links
- `search_memories_by_similarity()` - Vector search (Phase 3 retrieval)

## Database Schema

### Tables Used

**entities:**
- `id` (UUID, PK)
- `name` (TEXT) - Entity name
- `type` (TEXT) - project, person, event, location, etc.
- `domain` (domain_enum) - work, family, personal, logistics
- `attributes` (JSONB) - Flexible key-value data
- `status` (TEXT) - active, archived, deleted

**memories:**
- `id` (UUID, PK)
- `content` (TEXT) - Memory text
- `embedding` (vector(1536)) - OpenAI embedding
- `entity_links` (UUID[]) - Array of entity IDs
- `metadata` (JSONB) - Source, timestamp, etc.
- `importance_score` (FLOAT) - 0-1 ranking

### Indexes

- `idx_entities_name` - Fast name lookups
- `idx_entities_domain` - Domain filtering
- `idx_memories_embedding` - IVFFlat vector index for cosine similarity
- `idx_memories_entity_links` - GIN index for array containment

## Usage Examples

### Basic Ingestion

```python
from uuid import UUID
from lib.agent.memory import ingest_user_message

result = await ingest_user_message(
    user_id=UUID("user-uuid-here"),
    content="Baseball game moved to 5 PM Saturday",
    source="sms"
)

print(result["status"])  # "success"
print(result["entities_created"])  # 1
print(result["memory_id"])  # UUID of stored memory
```

### Extraction Only (No DB Writes)

```python
from lib.agent.memory import extract_context

result = await extract_context("Meeting with Alice on Friday at 2 PM")

for entity in result.extracted_entities:
    print(f"{entity.name} ({entity.type})")
    print(f"  Domain: {entity.domain}")
    print(f"  Attributes: {entity.attributes}")
```

### Vector Search (Phase 3)

```python
from lib.agent.memory import search_memories_by_similarity

memories = await search_memories_by_similarity(
    query="What's happening with the baseball game?",
    limit=5,
    threshold=0.7
)

for memory in memories:
    print(memory.content)
```

## Testing

### Run Test Suite

```bash
# Set environment variables
export OPENAI_API_KEY="sk-..."
export SUPABASE_URL="https://..."
export SUPABASE_SERVICE_ROLE_KEY="..."

# Run extraction tests (no DB required)
python test_memory_ingestion.py

# Or run the module directly
python -m lib.agent.memory
```

### Manual Testing

```python
import asyncio
from uuid import UUID
from lib.agent.memory import ingest_user_message

async def test():
    result = await ingest_user_message(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        content="Q1 product launch deadline is March 31st",
        source="test"
    )
    print(result)

asyncio.run(test())
```

## Configuration

### Required Environment Variables

```bash
# OpenAI API (for embeddings + extraction)
OPENAI_API_KEY=sk-...

# Supabase (for database)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
```

### Model Configuration

- **LLM:** GPT-4o (temperature=0.0)
- **Embeddings:** text-embedding-3-small (1536 dimensions)
- **Fuzzy Matching:** PostgreSQL ILIKE (case-insensitive)

## Error Handling

### Graceful Degradation

If entity extraction fails, the pipeline:
1. Logs the error
2. Returns a fallback `ExtractedContext` with:
   - No entities
   - Raw text as core_memory (truncated to 500 chars)
   - Domain = "personal"
3. Continues to store the memory (so no data is lost)

### Common Issues

**"OPENAI_API_KEY must be set"**
- Solution: Export the environment variable

**"Embedding must be 1536 dimensions"**
- Solution: Ensure using `text-embedding-3-small` model

**"Entity creation returned no data"**
- Solution: Check Supabase connection and table schema

## Performance Metrics

Typical processing times (measured on dev machine):

- Embedding generation: ~200ms
- Entity extraction: ~800ms
- DB operations: ~300ms
- **Total pipeline: ~1300ms**

Optimizations:
- LLM calls use temp=0.0 (no sampling overhead)
- Single DB round-trip per entity (no N+1 queries)
- Batch entity processing where possible

## Future Enhancements (Phase 3+)

1. **Importance Scoring:** Use LLM to classify memory importance (0-1)
2. **Entity Relations:** Extract relationships between entities
3. **Temporal Decay:** Lower importance of old memories
4. **Multi-tenancy:** Partition by user_id in queries
5. **Caching:** Cache common entity lookups in Redis

## Migration Files

- `20260129170000_init_context_engine.sql` - Initial schema
- `20260129180000_memory_search_function.sql` - Vector search function

## Related Files

- `lib/db/models.py` - Pydantic models
- `lib/agent/core.py` - Agent orchestration
- `docs/specs/001-context-engine-prd.md` - Original PRD

## Troubleshooting

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Check Database Connection

```python
from lib.agent.memory import get_supabase_client

supabase = get_supabase_client()
response = supabase.table("entities").select("count").execute()
print(f"Total entities: {response.data}")
```

### Validate Embedding Dimensions

```python
from lib.agent.memory import get_embeddings

embeddings = get_embeddings()
vector = await embeddings.aembed_query("test")
print(f"Dimension: {len(vector)}")  # Should be 1536
```

---

**Questions?** Contact @backend-architect-sabine or check the PRD at `docs/specs/001-context-engine-prd.md`
