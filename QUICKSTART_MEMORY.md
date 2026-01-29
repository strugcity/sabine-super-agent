# Quick Start: Memory Ingestion Pipeline

**5-Minute Setup Guide** for the Context Engine Phase 2

---

## Prerequisites

```bash
# 1. Environment variables
export OPENAI_API_KEY="sk-..."
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="eyJ..."

# 2. Python packages (already in requirements.txt)
# - langchain-openai
# - supabase
# - pydantic
```

---

## Test 1: Entity Extraction (No Database Required)

```python
import asyncio
from lib.agent.memory import extract_context

async def test():
    result = await extract_context("Baseball game moved to 5 PM Saturday")
    
    print(f"Domain: {result.domain}")
    print(f"Entities: {len(result.extracted_entities)}")
    for entity in result.extracted_entities:
        print(f"  - {entity.name} ({entity.type}): {entity.attributes}")

asyncio.run(test())
```

**Expected Output:**
```
Domain: family
Entities: 1
  - Baseball Game (event): {'time': '5 PM', 'day': 'Saturday', 'status': 'rescheduled'}
```

---

## Test 2: Full Ingestion Pipeline (Database Required)

```python
import asyncio
from uuid import UUID
from lib.agent.memory import ingest_user_message

async def test():
    result = await ingest_user_message(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        content="Baseball game moved to 5 PM Saturday at Lincoln Park",
        source="sms"
    )
    
    print(f"Status: {result['status']}")
    print(f"Memory ID: {result['memory_id']}")
    print(f"Created: {result['entities_created']} entities")
    print(f"Updated: {result['entities_updated']} entities")
    print(f"Time: {result['processing_time_ms']}ms")

asyncio.run(test())
```

**Expected Output:**
```
Status: success
Memory ID: 550e8400-e29b-41d4-a716-446655440000
Created: 1 entities
Updated: 0 entities
Time: 1234ms
```

---

## Test 3: Using the Test Suite

```bash
# Run the comprehensive test suite
python test_memory_ingestion.py
```

This will test:
1. ✅ Entity extraction (GPT-4o)
2. ✅ Full ingestion pipeline (if Supabase configured)

---

## Verify Database Schema

```bash
# Check if tables exist
psql $DATABASE_URL -c "SELECT * FROM entities LIMIT 1;"
psql $DATABASE_URL -c "SELECT * FROM memories LIMIT 1;"

# Check if vector search function exists
psql $DATABASE_URL -c "SELECT proname FROM pg_proc WHERE proname = 'search_memories';"
```

---

## Integration Example: Add to FastAPI

### 1. Create Endpoint

```python
# src/app/api/memory/route.py (create this file)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from uuid import UUID
from lib.agent.memory import ingest_user_message

router = APIRouter()

class IngestRequest(BaseModel):
    user_id: str
    content: str
    source: str = "api"

@router.post("/ingest")
async def ingest_endpoint(request: IngestRequest):
    try:
        result = await ingest_user_message(
            user_id=UUID(request.user_id),
            content=request.content,
            source=request.source
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 2. Test the Endpoint

```bash
curl -X POST http://localhost:3000/api/memory/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "00000000-0000-0000-0000-000000000001",
    "content": "Baseball game moved to 5 PM Saturday",
    "source": "api"
  }'
```

---

## Common Issues & Fixes

### Issue 1: "OPENAI_API_KEY must be set"
```bash
# Fix: Export environment variable
export OPENAI_API_KEY="sk-..."
```

### Issue 2: "SUPABASE_URL must be set"
```bash
# Fix: Export Supabase credentials
export SUPABASE_URL="https://..."
export SUPABASE_SERVICE_ROLE_KEY="eyJ..."
```

### Issue 3: "Table 'entities' does not exist"
```bash
# Fix: Run migrations
cd supabase
psql $DATABASE_URL < migrations/20260129170000_init_context_engine.sql
psql $DATABASE_URL < migrations/20260129180000_memory_search_function.sql
```

### Issue 4: Import errors
```bash
# Fix: Ensure you're in the project root
cd /workspaces/sabine-super-agent
python -c "from lib.agent.memory import ingest_user_message; print('OK')"
```

---

## Next Steps

### Phase 3: Retrieval
1. Implement `retrieve_relevant_context(query)`
2. Blend vector search + entity graph queries
3. Use in agent context window

### Integration
1. Add to Twilio SMS handler
2. Hook into LangGraph agent graph
3. Connect to Gmail watch pipeline

### Optimization
1. Add Redis caching for entities
2. Batch process multiple messages
3. Implement importance scoring

---

## Monitoring & Debugging

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Check Pipeline Performance
```python
from lib.agent.memory import ingest_user_message
import asyncio
import time

async def benchmark():
    start = time.time()
    result = await ingest_user_message(...)
    elapsed = time.time() - start
    print(f"Pipeline took {elapsed:.2f}s")

asyncio.run(benchmark())
```

### Query Database Directly
```python
from lib.agent.memory import get_supabase_client

supabase = get_supabase_client()

# Get all entities
entities = supabase.table("entities").select("*").execute()
print(f"Total entities: {len(entities.data)}")

# Get all memories
memories = supabase.table("memories").select("*").execute()
print(f"Total memories: {len(memories.data)}")
```

---

## Documentation

- **Full API Docs**: `docs/MEMORY_INGESTION.md`
- **Architecture**: `docs/MEMORY_ARCHITECTURE.md`
- **Integration Examples**: `lib/agent/memory_integration_example.py`
- **Original PRD**: `docs/specs/001-context-engine-prd.md`

---

## Support

**Questions?** Check the documentation or contact @backend-architect-sabine

**Found a bug?** Open an issue with:
1. Environment (Python version, OS)
2. Error message and stack trace
3. Minimal reproduction code
