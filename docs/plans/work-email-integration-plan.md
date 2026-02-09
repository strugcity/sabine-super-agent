# Work Email Integration + Domain-Aware Memory

## Summary
Enable Sabine to receive and understand work emails from `rknollmaier@coca-cola.com` via a forwarding relay (`coca-cola → ryan@strugcity.com → sabine@strugcity.com`), classify them as work domain, ingest them into memory with domain tagging, draft replies for Ryan's review, and enable cross-context intelligence (e.g., scheduling conflicts, shared contacts across work/personal).

---

## Phase 1: Email Routing & Classification

### 1A. Outlook Forwarding Rule (Manual — Ryan)
- Create an auto-forward rule in Outlook/Microsoft 365:
  - **From:** All inbound email to `rknollmaier@coca-cola.com`
  - **Forward to:** `ryan@strugcity.com`
- Then set up a Google Workspace forwarding rule on `ryan@strugcity.com`:
  - **Forward to:** `sabine@strugcity.com`
  - OR configure `ryan@strugcity.com` as an additional monitored inbox

### 1B. Add Work Email Authorization
**File:** `lib/agent/gmail_handler.py`

Update `get_config()` to add work-related env vars:
```python
# New env vars
WORK_RELAY_EMAIL = os.getenv("WORK_RELAY_EMAIL", "ryan@strugcity.com")
WORK_ORIGIN_EMAIL = os.getenv("WORK_ORIGIN_EMAIL", "rknollmaier@coca-cola.com")
WORK_ORIGIN_DOMAIN = os.getenv("WORK_ORIGIN_DOMAIN", "coca-cola.com")
```

Add `ryan@strugcity.com` to `GMAIL_AUTHORIZED_EMAILS` env var (comma-separated alongside existing `rknollmaier@gmail.com`).

### 1C. Email Domain Classifier Function
**File:** `lib/agent/gmail_handler.py`

Add a new function that inspects email headers to determine if an email is work-originated:

```python
def classify_email_domain(sender: str, subject: str, headers: dict) -> str:
    """
    Classify whether an email is 'work' or 'personal'.

    Detection signals (in priority order):
    1. X-Forwarded-From or X-Original-Sender header contains WORK_ORIGIN_DOMAIN
    2. Sender is WORK_RELAY_EMAIL (ryan@strugcity.com)
    3. Subject contains "[Fwd:" or "Fw:" and original sender has work domain
    4. Sender domain matches WORK_ORIGIN_DOMAIN

    Returns: "work" | "personal"
    """
```

This function is called early in `handle_new_email_notification()` right after extracting email metadata, and the result is threaded through the rest of the pipeline.

### 1D. Update Blocked Sender Patterns for Work Context
**File:** `lib/agent/gmail_handler.py`

Work emails forwarded from Coca-Cola may come from corporate notification systems. Add a work-aware exception list so internal corporate senders aren't blocked by the existing `BLOCKED_SENDER_PATTERNS` when they arrive via the work relay. The classifier from 1C will inform whether to apply work-specific or personal-specific filtering.

---

## Phase 2: Domain-Aware Memory Ingestion

### 2A. Wire Email Content into Memory Pipeline
**File:** `lib/agent/gmail_handler.py` — inside `handle_new_email_notification()`

Currently, emails are processed by the agent but **never ingested into memory**. Add a call to `ingest_user_message()` after successfully processing each email:

```python
from lib.agent.memory import ingest_user_message

# After extracting email content, before generating response:
await ingest_user_message(
    user_id=UUID(user_id),
    content=f"Email from {sender} — Subject: {subject}\n\n{body_text}",
    source="email",
    role="assistant",
    domain_hint=email_domain  # "work" or "personal" — NEW PARAM
)
```

### 2B. Add `domain_hint` Parameter to Ingestion
**File:** `lib/agent/memory.py` — `ingest_user_message()`

Add an optional `domain_hint: Optional[str] = None` parameter. When provided, this **overrides** Claude's auto-classification during `extract_context()`. This is important because the email relay gives us a more reliable domain signal than LLM classification alone.

```python
async def ingest_user_message(
    user_id: UUID,
    content: str,
    source: str = "api",
    role: str = "assistant",
    domain_hint: Optional[str] = None  # NEW: "work", "personal", etc.
) -> Dict[str, Any]:
```

Inside the function, after `extract_context()` returns:
```python
extracted = await extract_context(content)

# Override domain if hint provided (email relay is more reliable than LLM classification)
if domain_hint:
    extracted.domain = DomainEnum(domain_hint)
    for entity in extracted.extracted_entities:
        entity.domain = DomainEnum(domain_hint)
```

Also store the domain in memory metadata:
```python
metadata = {
    "user_id": str(user_id),
    "source": source,
    "domain": extracted.domain.value,  # Already exists but verify it's stored
    "role": role,
    "timestamp": datetime.utcnow().isoformat(),
}
```

---

## Phase 3: Domain-Filtered Retrieval

### 3A. SQL Migration — Add domain_filter to match_memories()
**New file:** `supabase/migrations/20260210_add_domain_filter_to_match_memories.sql`

Follow the exact same pattern as the existing `role_filter` migration:

```sql
DROP FUNCTION IF EXISTS match_memories(text, float, int, uuid, text);
DROP FUNCTION IF EXISTS match_memories(text, float, int, uuid, text, text);

CREATE OR REPLACE FUNCTION match_memories(
    query_embedding text,
    match_threshold float DEFAULT 0.5,
    match_count int DEFAULT 10,
    user_id_filter uuid DEFAULT NULL,
    role_filter text DEFAULT NULL,
    domain_filter text DEFAULT NULL          -- NEW PARAMETER
)
RETURNS TABLE (
    id uuid, content text, embedding text,
    entity_links uuid[], metadata jsonb,
    importance_score float, created_at timestamptz,
    updated_at timestamptz, similarity float
)
LANGUAGE plpgsql AS $$
DECLARE query_vec vector(1536);
BEGIN
    query_vec := query_embedding::vector(1536);
    RETURN QUERY
    WITH scored_memories AS (
        SELECT m.*, (1.0 - (m.embedding::vector(1536) <=> query_vec)) as sim_score
        FROM memories m WHERE m.embedding IS NOT NULL
    )
    SELECT sm.id, sm.content, sm.embedding::text, sm.entity_links,
           sm.metadata, sm.importance_score, sm.created_at, sm.updated_at,
           sm.sim_score::float as similarity
    FROM scored_memories sm
    WHERE sm.sim_score > match_threshold
        AND (user_id_filter IS NULL OR (sm.metadata->>'user_id')::uuid = user_id_filter)
        AND (role_filter IS NULL OR (sm.metadata->>'role' = role_filter) OR (sm.metadata->>'role' IS NULL))
        -- Domain filtering: same pattern as role_filter
        AND (domain_filter IS NULL OR (sm.metadata->>'domain' = domain_filter) OR (sm.metadata->>'domain' IS NULL))
    ORDER BY sm.sim_score DESC
    LIMIT match_count;
END; $$;
```

### 3B. Thread domain_filter Through Retrieval Pipeline
**File:** `lib/agent/retrieval.py`

Add `domain_filter: Optional[str] = None` to:
1. `search_similar_memories()` — pass it to the RPC call
2. `search_entities_by_keywords()` — add `.eq("domain", domain_filter)` when provided
3. `retrieve_context()` — accept it and pass to both sub-functions

```python
async def retrieve_context(
    user_id: UUID,
    query: str,
    memory_threshold: float = DEFAULT_MEMORY_THRESHOLD,
    memory_limit: int = DEFAULT_MEMORY_COUNT,
    entity_limit: int = DEFAULT_ENTITY_LIMIT,
    role_filter: str = "assistant",
    domain_filter: Optional[str] = None     # NEW
) -> str:
```

### 3C. Domain-Aware Context Formatting
**File:** `lib/agent/retrieval.py` — `blend_context()`

When domain_filter is active, label the context section:
```
[CONTEXT FOR: "What's the PriceSpider deadline?" (WORK DOMAIN)]

[RELEVANT WORK MEMORIES]
- Meeting with Jenny about PriceSpider contract...

[RELATED WORK ENTITIES]
- PriceSpider Contract (Document, Work): Due Feb 15
```

---

## Phase 4: Cross-Context Intelligence

### 4A. Cross-Context Retrieval Function
**File:** `lib/agent/retrieval.py`

Add a new function for detecting cross-context relevance:

```python
async def cross_context_scan(
    user_id: UUID,
    query: str,
    primary_domain: str,
    memory_limit: int = 3,
) -> str:
    """
    After retrieving primary-domain context, scan the OTHER domain
    for conflicts/overlaps. Returns a compact cross-context advisory.

    Use cases:
    - Work meeting at 2 PM but personal dentist at 2:30 PM
    - Coworker 'Jenny' is also a friend at kids' soccer
    - Work travel overlapping with custody weekend
    """
    other_domain = "personal" if primary_domain == "work" else "work"

    # Vector search the other domain
    cross_memories = await search_similar_memories(
        query_embedding=..., domain_filter=other_domain, limit=memory_limit
    )

    # Entity overlap detection
    primary_entities = await search_entities_by_keywords(keywords, domain_filter=primary_domain)
    cross_entities = await search_entities_by_keywords(keywords, domain_filter=other_domain)

    # Find entities that exist in BOTH domains (shared contacts, etc.)
    shared = find_overlapping_entities(primary_entities, cross_entities)

    # Format as advisory
    return format_cross_context_advisory(cross_memories, shared, other_domain)
```

### 4B. Shared Entity Detection
**File:** `lib/agent/retrieval.py`

```python
def find_overlapping_entities(
    primary: List[Entity],
    cross: List[Entity]
) -> List[tuple[Entity, Entity]]:
    """
    Find entities that appear in both domains.
    Uses fuzzy name matching (same logic as find_similar_entity in memory.py).

    Examples:
    - 'Jenny' exists as Work/colleague AND Personal/friend
    - 'Downtown Office' appears in both work and personal contexts
    """
```

### 4C. Wire Cross-Context Into Agent
**File:** `lib/agent/sabine_agent.py`

After primary context retrieval (Step 4), add:

```python
# === STEP 4b: Cross-context scan (if domain known) ===
if email_domain:  # work or personal
    cross_advisory = await cross_context_scan(
        user_id=UUID(user_id),
        query=user_message,
        primary_domain=email_domain,
    )
    if cross_advisory:
        enhanced_message += f"\n\nCross-Context Advisory:\n{cross_advisory}"
```

---

## Phase 5: Work Email Response Drafting

### 5A. Draft-Reply Mode for Work Emails
**File:** `lib/agent/gmail_handler.py`

When `classify_email_domain()` returns `"work"`, instead of calling `send_threaded_reply()`, Sabine:

1. Generates an AI response (same as now via `generate_ai_response()`)
2. **Does NOT send it to the work email thread**
3. Instead, sends the draft to Ryan via SMS (Twilio) or personal email:

```python
if email_domain == "work":
    # Generate draft
    draft_response = await generate_ai_response(sender, subject, body, email_domain)

    # Notify Ryan with the draft
    draft_notification = (
        f"📧 WORK EMAIL DRAFT\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"---\n"
        f"Suggested reply:\n{draft_response}\n"
        f"---\n"
        f"Reply APPROVE to send, or reply with edits."
    )

    # Send via SMS or personal email
    await send_sms_notification(draft_notification)

    # Track as "draft_pending" in email_tracking
    save_draft_pending(message_id, thread_id, draft_response, email_domain)
else:
    # Personal: existing behavior — auto-reply
    await send_threaded_reply(...)
```

### 5B. Draft Approval Endpoint
**File:** `lib/agent/routers/gmail.py`

Add a new endpoint for approving/editing drafts:

```python
@router.post("/gmail/draft/approve", dependencies=[Depends(verify_api_key)])
async def approve_draft(request: DraftApprovalRequest):
    """
    Approve or edit a pending work email draft.
    Called when Ryan replies 'APPROVE' via SMS or sends edited text.
    """
```

Alternatively, this can be handled in the existing SMS → Sabine flow: if the user's SMS contains "APPROVE" and there's a pending draft, Sabine sends it.

---

## Phase 6: System Prompt & Agent Awareness

### 6A. Work Context Instructions
**File:** `lib/agent/core.py` — `build_static_context()`

Add a new section to the system prompt:

```
## Work Email Context

You now receive emails from Ryan's work account (rknollmaier@coca-cola.com)
via a forwarding relay through ryan@strugcity.com.

### Work Email Rules:
1. NEVER auto-reply to work emails. Always draft a reply for Ryan's review.
2. Work knowledge is tagged as domain="work" in memory.
3. Maintain professional tone when drafting work replies.
4. When processing work emails, check for cross-context conflicts:
   - Calendar conflicts between work meetings and personal events
   - Shared contacts (coworkers who are also personal friends)
   - Work travel vs custody/family schedule conflicts
5. Work entities (projects, colleagues, deadlines) should be tracked separately
   but cross-referenced when relevant.

### Domain Compartmentalization:
- Work memories are stored with domain="work"
- Personal/family memories use domain="personal"/"family"
- When retrieving context, primary domain memories are prioritized
- Cross-domain scan runs automatically to catch conflicts/overlaps
- NEVER share work-specific details in personal contexts unless Ryan asks
- NEVER share personal details in work draft replies
```

### 6B. Propagate Email Domain to Agent
**File:** `lib/agent/sabine_agent.py`

Add optional `email_domain: Optional[str] = None` parameter to `run_sabine_agent()`, and thread it through:
- Memory retrieval (as `domain_filter`)
- Cross-context scan
- System prompt (dynamic context can note "this message is from WORK context")

**File:** `lib/agent/shared.py`

Add `source_channel: Optional[str]` to `InvokeRequest`:
```python
class InvokeRequest(BaseModel):
    ...
    source_channel: Optional[str] = Field(
        None,
        description="Source channel hint: 'email-work', 'email-personal', 'sms', 'api'"
    )
```

---

## Phase 7: Morning Briefing Enhancement

### 7A. Dual-Context Briefing
**File:** `lib/agent/scheduler.py`

Update `get_briefing_context()` to generate a structured briefing:

```
☀️ Good morning, Ryan!

📋 WORK
- PriceSpider contract review due Friday
- 2 PM meeting with Jenny (design review)
- 3 unread work emails overnight

👨‍👩‍👧 PERSONAL/FAMILY
- Soccer practice at 4:30 PM (carpool: confirmed)
- Dentist appointment tomorrow at 10 AM

⚠️ CROSS-CONTEXT ALERTS
- 2 PM work meeting may conflict with 2:30 PM school pickup
- Jenny (work colleague) also invited to Saturday BBQ
```

---

## Files to Modify (Summary)

| File | Changes |
|------|---------|
| `lib/agent/gmail_handler.py` | Add `classify_email_domain()`, work relay config, email→memory ingestion, draft-reply mode for work emails |
| `lib/agent/memory.py` | Add `domain_hint` param to `ingest_user_message()`, override LLM domain classification when hint provided |
| `lib/agent/retrieval.py` | Add `domain_filter` to `search_similar_memories()`, `search_entities_by_keywords()`, `retrieve_context()`; add `cross_context_scan()` and `find_overlapping_entities()` |
| `lib/agent/sabine_agent.py` | Add `email_domain` param, wire domain-filtered retrieval + cross-context scan |
| `lib/agent/core.py` | Add work email rules to `build_static_context()` system prompt |
| `lib/agent/shared.py` | Add `source_channel` to `InvokeRequest`, add `DraftApprovalRequest` model |
| `lib/agent/routers/gmail.py` | Add `/gmail/draft/approve` endpoint, update `/gmail/handle` to pass domain |
| `lib/agent/scheduler.py` | Dual-context morning briefing |
| `supabase/migrations/20260210_add_domain_filter_to_match_memories.sql` | New migration: add `domain_filter` param to `match_memories()` |

## Environment Variables to Add

```
WORK_RELAY_EMAIL=ryan@strugcity.com
WORK_ORIGIN_EMAIL=rknollmaier@coca-cola.com
WORK_ORIGIN_DOMAIN=coca-cola.com
GMAIL_AUTHORIZED_EMAILS=rknollmaier@gmail.com,ryan@strugcity.com
```

---

## Implementation Order

1. **Migration first** — `domain_filter` in `match_memories()` (Phase 3A)
2. **Memory pipeline** — `domain_hint` in `ingest_user_message()` (Phase 2B)
3. **Retrieval pipeline** — domain_filter threading (Phase 3B, 3C)
4. **Email classifier** — `classify_email_domain()` + config (Phase 1B, 1C)
5. **Email ingestion** — wire emails into memory (Phase 2A)
6. **Draft reply mode** — work email drafting (Phase 5A)
7. **Agent wiring** — domain propagation, cross-context (Phase 4, 6)
8. **Morning briefing** — dual-context (Phase 7)

---

## Verification Plan

1. **Unit test domain classification:** Send test emails from `ryan@strugcity.com` and `rknollmaier@gmail.com`, verify correct classification
2. **Memory ingestion test:** Process a work email, verify it's stored with `domain="work"` in metadata
3. **Domain-filtered retrieval test:** `POST /memory/query` with `domain_filter="work"` should only return work memories
4. **Cross-context test:** Create overlapping entities (e.g., "Jenny" in both work and personal), verify `cross_context_scan()` detects them
5. **Draft mode test:** Send a work email, verify Sabine sends draft via SMS instead of auto-replying
6. **End-to-end:** Forward a real Coca-Cola email through the relay chain, verify full pipeline: receive → classify → ingest → draft → notify
7. **Regression:** Verify existing personal email flow still works identically (auto-reply to authorized personal senders)
8. **Syntax checks:** `python -m py_compile` on all modified Python files, `npm run lint` if any `.tsx` changes
