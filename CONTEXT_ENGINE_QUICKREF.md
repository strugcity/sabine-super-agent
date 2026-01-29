# Context Engine - Quick Reference

## 🚀 Quick Start

### Start the Server
```bash
cd /workspaces/sabine-super-agent
python lib/agent/server.py
```

Server runs on: `http://localhost:8001`

---

## 📡 API Endpoints

### 1. POST /invoke (Main Endpoint - Enhanced)

Send a message to the agent. Automatically retrieves context and ingests the message.

```bash
curl -X POST http://localhost:8001/invoke \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What contracts did I sign?",
    "user_id": "00000000-0000-0000-0000-000000000001"
  }'
```

**Response:**
```json
{
  "success": true,
  "response": "Based on your memory, you signed the PriceSpider contract on Friday...",
  "user_id": "...",
  "session_id": "...",
  "timestamp": "2025-01-30T12:00:00Z"
}
```

**What happens:**
1. ✅ Retrieves relevant memories/entities (~150ms)
2. ✅ Injects context into agent's prompt
3. ✅ Generates context-aware response
4. ✅ Ingests message in background (async)

---

### 2. POST /memory/ingest (Manual Ingestion)

Manually add memories for testing or bulk import.

```bash
curl -X POST http://localhost:8001/memory/ingest \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "00000000-0000-0000-0000-000000000001",
    "content": "I met John at the AI conference. He works at Acme Corp.",
    "source": "manual"
  }'
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

---

### 3. POST /memory/query (Debug Retrieval)

See what the agent "remembers" about a query.

```bash
curl -X POST http://localhost:8001/memory/query \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "00000000-0000-0000-0000-000000000001",
    "query": "Who is John?"
  }'
```

**Response:**
```json
{
  "success": true,
  "context": "[RELEVANT MEMORIES]\n\nMemory: I met John at the AI conference...\n\n[RELATED ENTITIES]\n\n• John (person, work)\n• Acme Corp (company, work)",
  "context_length": 234,
  "metadata": {
    "memories_found": 1,
    "entities_found": 2,
    "query": "Who is John?"
  }
}
```

---

## 🧪 Testing

### Run Phase 4 Integration Tests

```bash
cd /workspaces/sabine-super-agent
python tests/test_phase4_integration.py
```

**Tests:**
1. ✅ Manual memory ingestion (3 messages)
2. ✅ Context retrieval (3 queries)
3. ✅ Integrated /invoke with context

---

### Run Phase 2 Memory Tests

```bash
python tests/verify_memory.py
```

**Tests:**
- Entity extraction (Claude 3 Haiku)
- Embedding generation (OpenAI)
- Entity matching/merging
- Memory storage

---

### Run Phase 3 Retrieval Tests

```bash
python tests/verify_retrieval.py
```

**Tests:**
- Vector similarity search
- Entity keyword search
- Context formatting

---

## 📊 Database Queries

### Check Memories

```sql
-- Count memories per user
SELECT user_id, COUNT(*) 
FROM memories 
GROUP BY user_id;

-- View recent memories
SELECT 
  id,
  user_id,
  LEFT(content, 50) as preview,
  source,
  created_at
FROM memories
ORDER BY created_at DESC
LIMIT 10;
```

### Check Entities

```sql
-- Count entities per user
SELECT user_id, type, COUNT(*)
FROM entities
GROUP BY user_id, type;

-- View all entities for a user
SELECT 
  name,
  type,
  domain,
  attributes,
  created_at
FROM entities
WHERE user_id = '00000000-0000-0000-0000-000000000001'
ORDER BY created_at DESC;
```

### Test Vector Search

```sql
-- Get a sample embedding
SELECT embedding 
FROM memories 
LIMIT 1;

-- Test match_memories function
SELECT * FROM match_memories(
  query_embedding := (SELECT embedding FROM memories LIMIT 1),
  match_threshold := 0.7,
  match_count := 5,
  user_id_filter := '00000000-0000-0000-0000-000000000001'
);
```

---

## 🔧 Configuration

### Environment Variables

Required in `.env`:

```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# LLM (Entity Extraction)
ANTHROPIC_API_KEY=sk-ant-...

# Embeddings
OPENAI_API_KEY=sk-...

# API Auth
SABINE_API_KEY=your-secure-key
```

### Tuning Parameters

**In [lib/agent/retrieval.py](lib/agent/retrieval.py):**

```python
# Default thresholds
memory_threshold = 0.7    # Cosine similarity (0.0-1.0)
memory_limit = 10         # Max memories to return
entity_limit = 20         # Max entities to return
```

**Lower threshold = more results (less strict)**  
**Higher threshold = fewer results (more strict)**

---

## 🐛 Troubleshooting

### No Context Retrieved

**Symptoms:** Agent doesn't mention past conversations

**Checks:**
```sql
-- 1. Are there memories?
SELECT COUNT(*) FROM memories WHERE user_id = 'your-uuid';

-- 2. Do they have embeddings?
SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL;

-- 3. Is match_memories() working?
SELECT * FROM match_memories(
  (SELECT embedding FROM memories LIMIT 1),
  0.5, 5, 'your-uuid'
);
```

**Solutions:**
- Apply SQL migration: `supabase/migrations/20260130000000_add_match_memories.sql`
- Lower threshold: `memory_threshold=0.5`
- Check logs for retrieval errors

---

### Ingestion Failing

**Symptoms:** No entities created, no memories stored

**Checks:**
```bash
# 1. Check API keys
echo $ANTHROPIC_API_KEY
echo $OPENAI_API_KEY

# 2. Check server logs
# Look for: "Memory ingestion failed: {error}"

# 3. Test manually
curl -X POST http://localhost:8001/memory/ingest \
  -H "X-API-Key: dev-key-123" \
  -d '{"user_id":"...","content":"Test"}'
```

**Solutions:**
- Verify environment variables loaded
- Check Anthropic API key is valid (Claude 3 Haiku access)
- Ensure Supabase credentials are correct

---

### Slow Responses

**Symptoms:** /invoke taking >2 seconds

**Checks:**
```bash
# Check logs for timing
# Look for: "✓ Retrieved context (XXX chars)" - should be <300ms
```

**Solutions:**
- Build pgvector index (for 10k+ memories)
- Reduce limits: `memory_limit=5, entity_limit=10`
- Enable query caching (future feature)

---

## 📈 Performance Metrics

| Operation | Typical Latency |
|-----------|-----------------|
| Entity Extraction (Claude) | ~500ms |
| Embedding Generation | ~100ms |
| Vector Search | ~50ms |
| Entity Search | ~30ms |
| **Total Retrieval** | **~150ms** |
| Background Ingestion | ~600ms (async) |

**Impact on /invoke:** +150ms (retrieval only)

---

## 🎯 Usage Tips

### 1. Batch Ingestion

```bash
# Import historical data
for message in "${messages[@]}"; do
  curl -X POST http://localhost:8001/memory/ingest \
    -H "X-API-Key: $API_KEY" \
    -d "{\"user_id\":\"$USER_ID\",\"content\":\"$message\"}"
  sleep 1  # Rate limiting
done
```

### 2. Context Preview

Before sending a query, check what the agent will see:

```bash
curl -X POST http://localhost:8001/memory/query \
  -H "X-API-Key: $API_KEY" \
  -d '{"user_id":"...","query":"your question"}'
```

### 3. Manual Entity Creation

Ingest structured data:

```bash
curl -X POST http://localhost:8001/memory/ingest \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "user_id": "...",
    "content": "John Smith is the VP of Engineering at Acme Corp. Email: john@acme.com. Phone: 555-1234.",
    "source": "crm_import"
  }'
```

---

## 📚 Documentation

- **Complete Guide:** [CONTEXT_ENGINE_COMPLETE.md](CONTEXT_ENGINE_COMPLETE.md)
- **Phase 2 - Ingestion:** [MEMORY_INGESTION_SUMMARY.md](MEMORY_INGESTION_SUMMARY.md)
- **Phase 3 - Retrieval:** [RETRIEVAL_IMPLEMENTATION.md](RETRIEVAL_IMPLEMENTATION.md)
- **Phase 4 - API:** [PHASE_4_API_INTEGRATION.md](PHASE_4_API_INTEGRATION.md)
- **Architecture:** [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md)

---

## 🔗 Key Files

| File | Lines | Purpose |
|------|-------|---------|
| [lib/agent/memory.py](lib/agent/memory.py) | 649 | Memory ingestion pipeline |
| [lib/agent/retrieval.py](lib/agent/retrieval.py) | 600+ | Context retrieval logic |
| [lib/agent/server.py](lib/agent/server.py) | 890+ | FastAPI server with integration |

---

## ✅ Deployment Checklist

Before going live:

- [ ] Apply SQL migrations (match_memories function)
- [ ] Verify environment variables in production
- [ ] Test with real user data
- [ ] Set up monitoring for retrieval latency
- [ ] Enable error alerting
- [ ] Load test with concurrent requests

---

**Last Updated:** January 30, 2025  
**Status:** Phase 4 Complete ✅
