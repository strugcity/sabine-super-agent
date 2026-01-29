# Context Engine - Memory Ingestion Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER INPUT                                  │
│   (SMS, Email, Chat, Voice → "Baseball game moved to 5 PM")        │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    INGESTION PIPELINE                               │
│                  lib/agent/memory.py                                │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ STEP 1: Generate Embedding                                   │  │
│  │ ━━━━━━━━━━━━━━━━━━━━━━━━━━                                  │  │
│  │ Model: text-embedding-3-small                                │  │
│  │ Output: vector(1536)                                         │  │
│  │ Latency: ~200ms                                              │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                 │                                   │
│                                 ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ STEP 2: Extract Context                                      │  │
│  │ ━━━━━━━━━━━━━━━━━━━━━━━                                     │  │
│  │ Model: GPT-4o (temp=0.0)                                     │  │
│  │ Function: extract_context(text)                              │  │
│  │                                                               │  │
│  │ Output Schema:                                                │  │
│  │  ├─ extracted_entities: [                                    │  │
│  │  │    {name, type, domain, attributes}                       │  │
│  │  │  ]                                                         │  │
│  │  ├─ core_memory: "summarized text"                           │  │
│  │  └─ domain: work|family|personal|logistics                   │  │
│  │                                                               │  │
│  │ Latency: ~800ms                                              │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                 │                                   │
│                                 ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ STEP 3: Entity Management                                    │  │
│  │ ━━━━━━━━━━━━━━━━━━━━━━━━                                    │  │
│  │ For each extracted entity:                                   │  │
│  │                                                               │  │
│  │  ┌──────────────────────────────┐                            │  │
│  │  │ find_similar_entity()         │                            │  │
│  │  │ (Fuzzy Match - ILIKE)         │                            │  │
│  │  └────────┬──────────────────────┘                            │  │
│  │           │                                                    │  │
│  │     ┌─────┴─────┐                                             │  │
│  │     ▼           ▼                                             │  │
│  │  FOUND      NOT FOUND                                         │  │
│  │     │           │                                             │  │
│  │     ▼           ▼                                             │  │
│  │  MERGE      CREATE                                            │  │
│  │  (JSONB)    (INSERT)                                          │  │
│  │     │           │                                             │  │
│  │     └─────┬─────┘                                             │  │
│  │           │                                                    │  │
│  │           ▼                                                    │  │
│  │    Entity UUID                                                │  │
│  │                                                               │  │
│  │ Latency: ~100ms per entity                                   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                 │                                   │
│                                 ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ STEP 4: Store Memory                                         │  │
│  │ ━━━━━━━━━━━━━━━━━━━━                                        │  │
│  │ store_memory()                                               │  │
│  │                                                               │  │
│  │ Inserts:                                                      │  │
│  │  ├─ content (core_memory text)                               │  │
│  │  ├─ embedding (vector 1536)                                  │  │
│  │  ├─ entity_links (UUID[])                                    │  │
│  │  ├─ metadata (JSONB)                                         │  │
│  │  └─ importance_score (0-1)                                   │  │
│  │                                                               │  │
│  │ Latency: ~200ms                                              │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    SUPABASE DATABASE                                │
│                                                                     │
│  ┌──────────────────────────┐    ┌───────────────────────────┐   │
│  │    entities              │    │    memories               │   │
│  │  ━━━━━━━━━━━━━━━━━━━━  │    │  ━━━━━━━━━━━━━━━━━━━━   │   │
│  │  id (UUID)               │◄───┤  entity_links (UUID[])    │   │
│  │  name (TEXT)             │    │  content (TEXT)           │   │
│  │  type (TEXT)             │    │  embedding (vector 1536)  │   │
│  │  domain (enum)           │    │  metadata (JSONB)         │   │
│  │  attributes (JSONB)      │    │  importance_score         │   │
│  │  status (active/...)     │    │  created_at               │   │
│  │  created_at              │    │  updated_at               │   │
│  │  updated_at              │    └───────────────────────────┘   │
│  └──────────────────────────┘                                     │
│                                                                     │
│  Indexes:                                                          │
│  ├─ idx_entities_name (B-tree)                                    │
│  ├─ idx_entities_domain (B-tree)                                  │
│  ├─ idx_entities_attributes (GIN - JSONB)                         │
│  ├─ idx_memories_embedding (IVFFlat - Vector)                     │
│  └─ idx_memories_entity_links (GIN - Array)                       │
│                                                                     │
│  Functions:                                                        │
│  └─ search_memories(query_embedding, threshold, count)            │
│       Returns memories by cosine similarity                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow Example

### Input
```
"Baseball game moved to 5 PM Saturday at Lincoln Park"
```

### Step 1: Embedding
```
vector(1536) = [0.123, -0.456, 0.789, ...]
```

### Step 2: Extraction
```json
{
  "extracted_entities": [
    {
      "name": "Baseball Game",
      "type": "event",
      "domain": "family",
      "attributes": {
        "time": "5 PM",
        "day": "Saturday",
        "location": "Lincoln Park",
        "status": "rescheduled"
      }
    }
  ],
  "core_memory": "Baseball game rescheduled to 5 PM Saturday at Lincoln Park",
  "domain": "family"
}
```

### Step 3: Entity Processing

#### 3a. Search for existing "Baseball Game"
```sql
SELECT * FROM entities
WHERE name ILIKE '%baseball game%'
  AND type = 'event'
  AND domain = 'family'
  AND status = 'active'
LIMIT 1;
```

#### 3b. If Found: Merge attributes
```sql
UPDATE entities
SET attributes = attributes || '{"time": "5 PM", "day": "Saturday", ...}'::jsonb,
    updated_at = NOW()
WHERE id = '...';
```

#### 3c. If Not Found: Create entity
```sql
INSERT INTO entities (name, type, domain, attributes, status)
VALUES ('Baseball Game', 'event', 'family', '{"time": "5 PM", ...}'::jsonb, 'active')
RETURNING *;
```

### Step 4: Memory Storage
```sql
INSERT INTO memories (content, embedding, entity_links, metadata)
VALUES (
  'Baseball game rescheduled to 5 PM Saturday at Lincoln Park',
  '[0.123, -0.456, ...]'::vector(1536),
  ARRAY['entity-uuid-here']::uuid[],
  '{"source": "sms", "timestamp": "2026-01-29T12:00:00Z"}'::jsonb
)
RETURNING *;
```

### Final Output
```json
{
  "status": "success",
  "memory_id": "memory-uuid",
  "entities_created": 1,
  "entities_updated": 0,
  "total_entities": 1,
  "entity_ids": ["entity-uuid"],
  "domain": "family",
  "processing_time_ms": 1234
}
```

## Error Handling Flow

```
┌────────────────────┐
│ LLM Extraction     │
│ Fails              │
└─────┬──────────────┘
      │
      ▼
┌────────────────────────────────┐
│ Fallback Strategy:             │
│ ────────────────────           │
│ • No entities extracted        │
│ • core_memory = raw text[0:500]│
│ • domain = "personal"          │
│ • Continue to storage          │
└────────┬───────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│ Store Generic Memory           │
│ (No entity links)              │
└────────────────────────────────┘
```

## Integration Points

### 1. Twilio SMS Handler
```
┌──────────┐         ┌──────────────────┐
│ Twilio   │────────►│ FastAPI          │
│ Webhook  │         │ /api/sms/webhook │
└──────────┘         └────────┬─────────┘
                              │
                              ▼
                     ┌─────────────────────┐
                     │ ingest_user_message │
                     │ (background task)    │
                     └─────────────────────┘
```

### 2. LangGraph Agent
```
┌──────────┐    ┌────────────┐    ┌────────┐    ┌──────────┐
│ __start__│───►│ ingest_    │───►│ agent  │───►│ __end__  │
│          │    │ memory     │    │        │    │          │
└──────────┘    └────────────┘    └────────┘    └──────────┘
```

### 3. Gmail Watch
```
┌──────────┐         ┌──────────────────┐
│ Gmail    │────────►│ /api/gmail/      │
│ PubSub   │         │ webhook          │
└──────────┘         └────────┬─────────┘
                              │
                              ▼
                     ┌─────────────────────┐
                     │ Parse email body    │
                     │ ingest_user_message │
                     └─────────────────────┘
```

## Performance Profile

### Latency Breakdown
```
Total Pipeline: ~1300ms
├─ Embedding:     200ms (15%)
├─ LLM Extract:   800ms (62%)
├─ DB Ops:        300ms (23%)
└─────────────────────────────
    Per Entity:   ~100ms
    Memory Store: ~200ms
```

### Optimization Opportunities
1. **Batch Embeddings**: Process multiple messages together
2. **Cache Entities**: Redis for frequent lookups
3. **Parallel Processing**: Multiple entities concurrently
4. **Prompt Caching**: Cache LLM system prompts (90% reduction)

## Retrieval Flow (Phase 3)

```
User Query: "What's happening with baseball?"
            │
            ▼
    ┌───────────────┐
    │ Generate      │
    │ Query Embed   │
    └───────┬───────┘
            │
            ▼
    ┌───────────────────────────────┐
    │ search_memories()             │
    │ Vector Similarity Search      │
    │ (Cosine Distance < threshold) │
    └───────┬───────────────────────┘
            │
            ▼
    ┌───────────────────┐
    │ Top 5 Memories    │
    │ + Linked Entities │
    └───────┬───────────┘
            │
            ▼
    ┌───────────────────┐
    │ Blend into        │
    │ Agent Context     │
    └───────────────────┘
```

---

**Architecture Notes:**
- All operations are async/await
- Graceful degradation on failures
- Single DB round-trips (no N+1)
- Type-safe with Pydantic V2
- Comprehensive logging for observability
