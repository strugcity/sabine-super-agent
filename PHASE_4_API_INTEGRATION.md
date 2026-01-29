# Phase 4: API Integration - Context Engine

## Overview

Phase 4 integrates the Context Engine (Memory Ingestion + Retrieval) into the main FastAPI server ([lib/agent/server.py](lib/agent/server.py)), enabling automatic context-aware responses.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Server                          │
│                   (lib/agent/server.py)                     │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
         ┌─────────────────────────────────┐
         │   POST /invoke (modified)       │
         │                                 │
         │  1. Retrieve Context First      │──┐
         │  2. Inject into System Prompt   │  │
         │  3. Generate Response           │  │
         │  4. Ingest (Background Task)    │◄─┘
         └─────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
    ┌──────────────────┐      ┌──────────────────┐
    │  retrieve_context│      │ ingest_user_      │
    │  (retrieval.py)  │      │ message           │
    │                  │      │ (memory.py)       │
    │ • Vector Search  │      │ • Extract Entities│
    │ • Entity Search  │      │ • Generate        │
    │ • Format Context │      │   Embeddings      │
    └──────────────────┘      │ • Store Memory    │
                              └──────────────────┘
```

## Modified Endpoints

### POST /invoke (Enhanced)

**What Changed:**
- Added `BackgroundTasks` dependency injection
- Retrieves context **before** generating response
- Injects context into the prompt as a prefix
- Queues ingestion as a background task (non-blocking)

**Flow:**

```python
1. User sends message
2. retrieve_context(user_id, message) → formatted context string
3. Enhanced message: "Context from Memory:\n{context}\n\nUser Query: {message}"
4. Agent generates response with context
5. background_tasks.add_task(ingest_user_message, ...)
6. Return response immediately (ingestion happens async)
```

**Benefits:**
- **No latency increase:** Ingestion doesn't block response
- **Context-aware:** Agent sees relevant memories/entities
- **Automatic learning:** Every conversation is ingested

## New Endpoints

### POST /memory/ingest

Manual memory ingestion for testing/dashboard.

**Request:**
```json
{
  "user_id": "00000000-0000-0000-0000-000000000001",
  "content": "I met John at the conference. He works at Acme Corp.",
  "source": "manual"  // optional, defaults to "manual"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Memory ingestion completed successfully",
  "entities_created": 2,
  "entities_updated": 0,
  "memory_id": "uuid-here"
}
```

**Use Cases:**
- Testing memory ingestion without sending agent messages
- Dashboard for manually adding context
- Bulk data import

### POST /memory/query

Debug endpoint to test context retrieval.

**Request:**
```json
{
  "user_id": "00000000-0000-0000-0000-000000000001",
  "query": "Who did I meet at the conference?",
  "memory_threshold": 0.7,    // optional, default 0.7
  "memory_limit": 10,          // optional, default 10
  "entity_limit": 20           // optional, default 20
}
```

**Response:**
```json
{
  "success": true,
  "context": "[RELEVANT MEMORIES]\n\nMemory: I met John at the conference...\n\n[RELATED ENTITIES]\n\n• John (person, work)\n• Acme Corp (company, work)",
  "context_length": 234,
  "metadata": {
    "memories_found": 1,
    "entities_found": 2,
    "query": "Who did I meet at the conference?"
  }
}
```

**Use Cases:**
- Debug what the agent "remembers"
- Test retrieval quality
- Dashboard preview of context

## Implementation Details

### Dependencies Added

```python
from fastapi import BackgroundTasks
from lib.agent.memory import ingest_user_message
from lib.agent.retrieval import retrieve_context
```

### Request Models Added

```python
class MemoryIngestRequest(BaseModel):
    user_id: str
    content: str
    source: str | None = None

class MemoryQueryRequest(BaseModel):
    user_id: str
    query: str
    memory_threshold: float | None = None
    memory_limit: int | None = None
    entity_limit: int | None = None
```

### Error Handling

- **Retrieval failure:** Logs warning, continues without context (graceful degradation)
- **Ingestion failure:** Logged in background task, doesn't affect response
- **Manual endpoints:** Return HTTP 500 with error details

## Testing

### 1. Test Manual Ingestion

```bash
curl -X POST http://localhost:8001/memory/ingest \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "00000000-0000-0000-0000-000000000001",
    "content": "I signed the PriceSpider contract on Friday. Jenny from their team was helpful.",
    "source": "test"
  }'
```

Expected:
```json
{
  "success": true,
  "message": "Memory ingestion completed successfully",
  "entities_created": 2,
  "entities_updated": 0,
  "memory_id": "..."
}
```

### 2. Test Context Retrieval

```bash
curl -X POST http://localhost:8001/memory/query \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "00000000-0000-0000-0000-000000000001",
    "query": "What happened with PriceSpider?"
  }'
```

Expected:
```json
{
  "success": true,
  "context": "[RELEVANT MEMORIES]\n\nMemory: I signed the PriceSpider contract on Friday...\n\n[RELATED ENTITIES]\n\n• PriceSpider Contract (document, work)\n• Jenny (person, work)",
  "context_length": 180,
  "metadata": {
    "memories_found": 1,
    "entities_found": 2,
    "query": "What happened with PriceSpider?"
  }
}
```

### 3. Test Integrated /invoke

```bash
curl -X POST http://localhost:8001/invoke \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Who is Jenny?",
    "user_id": "00000000-0000-0000-0000-000000000001"
  }'
```

**Check Logs:**
```
✓ Retrieved context (234 chars)
✓ Queued message ingestion as background task
```

**Expected Response:**
```json
{
  "success": true,
  "response": "Jenny is a person from the PriceSpider team who helped with the contract signing on Friday.",
  "user_id": "00000000-0000-0000-0000-000000000001",
  "session_id": "session-00000000",
  "timestamp": "2025-01-30T12:00:00Z"
}
```

## Performance Considerations

### Latency

- **Retrieval:** ~100-300ms (vector search + entity queries)
- **Ingestion:** 0ms (background task, doesn't block response)
- **Total impact:** +100-300ms on /invoke endpoint

### Optimization Strategies

1. **Cache embeddings:** Store query embeddings for repeated questions
2. **Parallel execution:** Vector search + entity search run concurrently
3. **Pagination:** Limit results (default 10 memories, 20 entities)
4. **Index tuning:** Ensure pgvector IVFFlat index is built

### Database Load

- **Reads (per request):** 1 vector search + 1 entity search
- **Writes (background):** 1 memory + N entity upserts
- **Connection pooling:** Uses Supabase client with default pool

## Monitoring

### Key Metrics

1. **Context Retrieval Success Rate:** % of /invoke calls with successful context retrieval
2. **Ingestion Success Rate:** % of background tasks completed without errors
3. **Context Length:** Average characters of context injected
4. **Retrieval Latency:** p50, p95, p99 for retrieve_context()

### Logs to Watch

```
✓ Retrieved context (234 chars)           # Context successfully retrieved
✓ Queued message ingestion as background task  # Ingestion scheduled
Context retrieval failed, continuing without: {error}  # Graceful degradation
Memory ingestion failed: {error}           # Background ingestion error
```

## Migration Checklist

Before deploying to production:

- [ ] Apply SQL migration: `supabase/migrations/20260130000000_add_match_memories.sql`
- [ ] Verify pgvector extension enabled
- [ ] Test with real user data
- [ ] Monitor logs for retrieval/ingestion errors
- [ ] Set up alerting for high error rates
- [ ] Load test with concurrent requests

## Rollback Plan

If issues arise:

1. **Disable context retrieval:**
   ```python
   # In /invoke endpoint, comment out retrieval section
   # retrieved_context = await retrieve_context(...)
   enhanced_message = request.message  # Skip context injection
   ```

2. **Disable ingestion:**
   ```python
   # In /invoke endpoint, comment out background task
   # background_tasks.add_task(ingest_user_message, ...)
   ```

3. **Full rollback:** Revert server.py to previous commit

## Next Steps (Future Phases)

- **Phase 5:** Frontend dashboard for memory visualization
- **Phase 6:** Entity relationship graph rendering
- **Phase 7:** Memory editing/deletion via UI
- **Phase 8:** Cross-user entity merging (shared knowledge)

## References

- [Memory Ingestion Implementation](MEMORY_INGESTION_SUMMARY.md)
- [Retrieval Implementation](RETRIEVAL_IMPLEMENTATION.md)
- [Memory Architecture](MEMORY_ARCHITECTURE.md)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
