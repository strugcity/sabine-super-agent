# Calendar Subscription Skill - Technical Plan

> **Project:** Sabine Calendar Subscription Ingestion
> **Author:** Technical Lead
> **Date:** 2026-02-01
> **Status:** Draft

---

## Technical Analysis

### 1. ICS Parsing: Library Recommendation

**Recommendation: `icalendar`**

| Criteria | icalendar | ics.py |
|----------|-----------|--------|
| Error Tolerance | ✅ `ignore_exceptions=True` by default, `vBrokenProperty` fallback | ❌ Strict, throws on malformed input |
| Messy Feed Handling | ✅ Handles trailing semicolons, embedded HTML, UTF-8 issues | ❌ Requires pre-processing |
| Non-Standard Props | ✅ Native X-property support (`X-WR-CALNAME`, etc.) | ⚠️ Limited documentation |
| Large File Support | ✅ `cal.walk()` generator for lazy iteration | ❌ Full memory load only |
| Maintenance | ✅ v6.3.2 (Nov 2025), active development | ❌ v0.7.2 (July 2022), abandoned |

**Rationale:** Sports association feeds (TeamSnap, LeagueLobster, etc.) are notoriously non-compliant. `icalendar` can extract valid events even when some entries are malformed, which is critical for BTBA/Fastpitch feeds.

```python
# Example pattern for messy feeds
from icalendar import Calendar

def parse_ics_robust(ics_content: bytes) -> list[dict]:
    cal = Calendar.from_ical(ics_content)
    events = []
    for event in cal.walk('VEVENT'):
        if hasattr(event, 'errors') and event.errors:
            logger.warning(f"Parse warning: {event.errors}")
        events.append({
            'summary': str(event.get('summary', '')),
            'description': str(event.get('description', '')),
            'location': str(event.get('location', '')),
            'dtstart': event.get('dtstart').dt if event.get('dtstart') else None,
        })
    return events
```

---

### 2. Inference Engine: Fuzzy Context Matching

**Approach:** Weighted keyword scoring against a Family Entity Graph stored in Supabase `entities` table.

**Algorithm:**
1. Extract all text fields from ICS (`X-WR-CALNAME`, `SUMMARY`, `DESCRIPTION`, `LOCATION`)
2. Normalize text (lowercase, remove punctuation)
3. Score against each family member's keyword set
4. Return highest confidence match, or `None` if below threshold

**Family Entity Graph Schema:**

```json
{
  "entity_type": "family_member",
  "name": "Jack",
  "domain": "family",
  "attributes": {
    "calendar_keywords": {
      "sports": {
        "keywords": ["btba", "bandits", "baseball"],
        "weight": 1.0
      },
      "school": {
        "keywords": ["jefferson", "jefferson high", "jhs"],
        "weight": 0.8
      }
    },
    "age": 14,
    "grade": "9th"
  }
}
```

**Confidence Scoring:**
```python
def infer_family_member(ics_metadata: dict, entity_graph: list[dict]) -> tuple[str | None, float]:
    """
    Returns (family_member_name, confidence_score)
    Confidence < 0.6 triggers user clarification
    """
    text_blob = ' '.join([
        ics_metadata.get('calendar_name', ''),
        ics_metadata.get('first_event_summary', ''),
        ics_metadata.get('first_event_location', ''),
    ]).lower()

    scores = {}
    for entity in entity_graph:
        if entity['entity_type'] != 'family_member':
            continue
        score = 0.0
        keywords = entity['attributes'].get('calendar_keywords', {})
        for category, config in keywords.items():
            for kw in config['keywords']:
                if kw in text_blob:
                    score += config['weight']
        scores[entity['name']] = score

    if not scores or max(scores.values()) == 0:
        return None, 0.0

    best_match = max(scores, key=scores.get)
    # Normalize to 0-1 range (assuming max possible score ~3.0)
    confidence = min(scores[best_match] / 3.0, 1.0)
    return best_match, confidence
```

**Conflict Resolution:**
- If `confidence < 0.6`: Return clarification prompt with top 2 candidates
- If multiple members score identically: Ask user to disambiguate

---

### 3. Google Calendar Strategy

**Constraint:** We need to read events BEFORE subscribing to determine ownership, but `calendarList.insert` subscribes without exposing content.

**Solution: Two-Phase Approach**

```
Phase 1: Preview & Infer
┌─────────────────────────────────────────────────────┐
│ User provides URL (webcal:// or https://)           │
│                    ↓                                │
│ Convert webcal:// → https://                        │
│                    ↓                                │
│ HTTP GET the ICS content directly                   │
│                    ↓                                │
│ Parse with icalendar                                │
│                    ↓                                │
│ Run inference engine → "Jack - BTBA Bandits 2026"  │
│                    ↓                                │
│ Confirm with user (show first upcoming event)       │
└─────────────────────────────────────────────────────┘

Phase 2: Subscribe (after user confirmation)
┌─────────────────────────────────────────────────────┐
│ calendarList.insert({                               │
│   id: "https://..../calendar.ics",                  │
│   summaryOverride: "Jack - BTBA Bandits 2026"       │
│ })                                                  │
│                    ↓                                │
│ Store subscription metadata in memory               │
│                    ↓                                │
│ Return confirmation with proof-of-life event        │
└─────────────────────────────────────────────────────┘
```

**API Sequence:**
```python
# Phase 1: Fetch and parse (NOT using Google API)
async def preview_calendar(url: str) -> dict:
    https_url = url.replace('webcal://', 'https://')
    async with httpx.AsyncClient() as client:
        response = await client.get(https_url, follow_redirects=True)
        response.raise_for_status()

    events = parse_ics_robust(response.content)
    metadata = extract_calendar_metadata(response.content)
    family_member, confidence = infer_family_member(metadata, get_entity_graph())

    return {
        'url': https_url,
        'inferred_owner': family_member,
        'confidence': confidence,
        'suggested_name': f"{family_member} - {metadata['calendar_name']}",
        'first_event': events[0] if events else None,
        'event_count': len(events),
    }

# Phase 2: Subscribe via Google Calendar API
async def subscribe_calendar(url: str, summary_override: str) -> dict:
    access_token = await get_fresh_access_token()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            'https://www.googleapis.com/calendar/v3/users/me/calendarList',
            headers={'Authorization': f'Bearer {access_token}'},
            json={
                'id': url,
                'summaryOverride': summary_override,
            }
        )
    return response.json()
```

---

### 4. Error Handling: URL Scheme Conversion

**Problem:** `webcal://` is not a valid HTTP scheme; Python's `httpx`/`requests` will fail.

**Solution:**
```python
def normalize_calendar_url(url: str) -> str:
    """
    Convert webcal:// to https:// and validate URL structure.

    webcal:// is just a URI scheme hint for calendar apps;
    the actual protocol is always HTTPS.
    """
    if url.startswith('webcal://'):
        url = 'https://' + url[9:]
    elif url.startswith('http://'):
        # Upgrade to HTTPS (most ICS providers support it)
        url = 'https://' + url[7:]

    # Validate it looks like a calendar URL
    if not url.endswith('.ics') and 'ical' not in url.lower():
        logger.warning(f"URL may not be a calendar feed: {url}")

    return url
```

**Additional Error Cases:**
| Error | Handling |
|-------|----------|
| 404 Not Found | "Calendar URL not accessible. Check if the link is correct." |
| 401/403 | "This calendar requires authentication. Please provide a public link." |
| SSL Error | Retry with `verify=False` after warning user |
| Timeout | Retry once, then fail with "Calendar server not responding" |
| Invalid ICS | "This URL doesn't contain valid calendar data" |

---

## Project Plan & Work Breakdown

---

## Epic 1: Foundation & Infrastructure

Setup the skill structure, database schema, and core utilities.

* [ ] **Story 1.1:** As a developer, I need the skill scaffolding so the agent can invoke calendar subscription actions
  * [ ] Task: [Backend] Create `/lib/skills/calendar_subscription/` directory structure
  * [ ] Task: [Backend] Create `manifest.json` with actions: `preview`, `subscribe`, `list`, `unsubscribe`
  * [ ] Task: [Backend] Create `handler.py` with async `execute()` entry point and action router
  * [ ] Task: [Backend] Add `icalendar` to `requirements.txt`

* [ ] **Story 1.2:** As a developer, I need database schema for subscription tracking and the family entity graph
  * [ ] Task: [Database] Add `calendar_subscriptions` table to `schema.sql`
    ```sql
    CREATE TABLE calendar_subscriptions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL,
        google_calendar_id TEXT NOT NULL,
        source_url TEXT NOT NULL,
        display_name TEXT NOT NULL,
        inferred_owner TEXT,
        inference_confidence FLOAT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    ```
  * [ ] Task: [Database] Seed `entities` table with family member records and `calendar_keywords` attributes
  * [ ] Task: [Backend] Create `db/calendar_subscriptions.py` with CRUD helpers

* [ ] **Story 1.3:** As a developer, I need URL normalization utilities
  * [ ] Task: [Backend] Create `lib/skills/calendar_subscription/url_utils.py`
  * [ ] Task: [Backend] Implement `normalize_calendar_url()` (webcal→https conversion)
  * [ ] Task: [Backend] Implement `validate_ics_url()` with HEAD request check
  * [ ] Task: [Tests] Unit tests for URL edge cases (webcal, http, https, non-.ics URLs)

---

## Epic 2: ICS Parsing & Metadata Extraction

Fetch and parse ICS feeds robustly.

* [ ] **Story 2.1:** As Sabine, I can fetch and parse an ICS file from a URL so I can read its contents
  * [ ] Task: [Backend] Create `lib/skills/calendar_subscription/ics_parser.py`
  * [ ] Task: [Backend] Implement `fetch_ics_content()` with httpx, timeout, and retry logic
  * [ ] Task: [Backend] Implement `parse_ics_robust()` using icalendar with error collection
  * [ ] Task: [Backend] Handle large files with streaming/chunked approach if >1MB
  * [ ] Task: [Tests] Test against real BTBA/TeamSnap sample feeds

* [ ] **Story 2.2:** As Sabine, I can extract calendar metadata for inference
  * [ ] Task: [Backend] Implement `extract_calendar_metadata()` returning:
    - `calendar_name` (from X-WR-CALNAME or first VCALENDAR property)
    - `event_count`
    - `first_event_summary`, `first_event_location`, `first_event_date`
    - `unique_locations` (set of all LOCATION values)
    - `unique_summaries` (set of all SUMMARY values, truncated)
  * [ ] Task: [Tests] Unit tests for metadata extraction from sample ICS files

---

## Epic 3: Contextual Inference Engine

Automatically determine calendar ownership.

* [ ] **Story 3.1:** As Sabine, I can load the Family Entity Graph from the database
  * [ ] Task: [Backend] Create `lib/skills/calendar_subscription/inference.py`
  * [ ] Task: [Backend] Implement `get_family_entity_graph()` querying entities table
  * [ ] Task: [Backend] Cache entity graph with 5-minute TTL to avoid repeated DB calls

* [ ] **Story 3.2:** As Sabine, I can infer which family member owns a calendar based on keywords
  * [ ] Task: [Backend] Implement `infer_family_member(metadata, entity_graph)` with weighted scoring
  * [ ] Task: [Backend] Return confidence score (0.0-1.0) alongside inference
  * [ ] Task: [Backend] Handle edge case: no matches → return `(None, 0.0)`
  * [ ] Task: [Backend] Handle edge case: tie → return both candidates with flag
  * [ ] Task: [Tests] Unit tests with mock entity graph and various ICS inputs

* [ ] **Story 3.3:** As a user, Sabine asks me for clarification when confidence is low
  * [ ] Task: [Backend] Define confidence threshold constant (0.6)
  * [ ] Task: [Backend] Implement `generate_clarification_prompt()` showing top candidates and evidence
  * [ ] Task: [Backend] Return structured response with `needs_clarification: true` flag

---

## Epic 4: Google Calendar Integration

Subscribe to calendars via Google Calendar API.

* [ ] **Story 4.1:** As Sabine, I can preview a calendar before subscribing
  * [ ] Task: [Backend] Implement `preview` action in handler.py
  * [ ] Task: [Backend] Orchestrate: fetch → parse → infer → format preview response
  * [ ] Task: [Backend] Include in response: suggested name, inferred owner, confidence, first 3 events

* [ ] **Story 4.2:** As Sabine, I can subscribe to a calendar with a custom display name
  * [ ] Task: [Backend] Implement `subscribe` action in handler.py
  * [ ] Task: [Backend] Call `calendarList.insert` with `id` (URL) and `summaryOverride`
  * [ ] Task: [Backend] Handle API errors: already subscribed, quota exceeded, invalid URL
  * [ ] Task: [Backend] Store subscription record in `calendar_subscriptions` table
  * [ ] Task: [Tests] Integration test with test Google account

* [ ] **Story 4.3:** As a user, I can list and manage my calendar subscriptions
  * [ ] Task: [Backend] Implement `list` action returning all subscriptions with metadata
  * [ ] Task: [Backend] Implement `unsubscribe` action calling `calendarList.delete`
  * [ ] Task: [Backend] Clean up database record on unsubscribe

---

## Epic 5: Memory & Confirmation

Persist context and provide user feedback.

* [ ] **Story 5.1:** As Sabine, I commit subscription context to long-term memory
  * [ ] Task: [Backend] After successful subscribe, call `memory.ingest_user_message()` with structured fact
  * [ ] Task: [Backend] Format memory as: "Jack is playing for the Bandits (BTBA) this season. Calendar subscribed on {date}."
  * [ ] Task: [Backend] Link memory to family member entity

* [ ] **Story 5.2:** As a user, I receive confirmation with proof-of-life
  * [ ] Task: [Backend] Format confirmation response with:
    - Action taken: "Subscribed to calendar as '{display_name}'"
    - Inference explanation: "I matched 'Bandits' and 'BTBA' to Jack's baseball keywords"
    - Proof-of-life: "Next event: Practice on Feb 5 at 6:00 PM at Jefferson Field"
  * [ ] Task: [Backend] Handle empty calendar case: "Calendar subscribed but no upcoming events found"

---

## Epic 6: Error Handling & Edge Cases

Robust handling of real-world failures.

* [ ] **Story 6.1:** As Sabine, I handle network and parsing errors gracefully
  * [ ] Task: [Backend] Implement retry logic (3 attempts with exponential backoff)
  * [ ] Task: [Backend] Handle SSL certificate errors with user warning
  * [ ] Task: [Backend] Handle malformed ICS with partial extraction + warning
  * [ ] Task: [Backend] Log all errors to structured logging for debugging

* [ ] **Story 6.2:** As Sabine, I handle Google API errors gracefully
  * [ ] Task: [Backend] Handle 409 Conflict (already subscribed) → offer to rename
  * [ ] Task: [Backend] Handle 403 Forbidden → token refresh and retry
  * [ ] Task: [Backend] Handle quota exceeded → inform user to try later

---

## Implementation Order

```
Week 1: Epic 1 (Foundation) + Epic 2 (Parsing)
Week 2: Epic 3 (Inference) + Epic 4 (Google Integration)
Week 3: Epic 5 (Memory) + Epic 6 (Error Handling)
Week 4: Integration testing, edge case fixes, documentation
```

---

## Appendix: Sample Family Entity Graph Seed Data

```sql
-- Jack (14, 9th grade)
INSERT INTO entities (id, entity_type, name, domain, attributes) VALUES (
  gen_random_uuid(),
  'family_member',
  'Jack',
  'family',
  '{
    "calendar_keywords": {
      "sports": {"keywords": ["btba", "bandits", "baseball", "diamond"], "weight": 1.0},
      "school": {"keywords": ["jefferson", "jefferson high", "jhs"], "weight": 0.8}
    },
    "age": 14,
    "grade": "9th"
  }'
);

-- Anna (12, 7th grade)
INSERT INTO entities (id, entity_type, name, domain, attributes) VALUES (
  gen_random_uuid(),
  'family_member',
  'Anna',
  'family',
  '{
    "calendar_keywords": {
      "sports": {"keywords": ["fastpitch", "blast", "bloomington fastpitch", "softball"], "weight": 1.0},
      "school": {"keywords": ["ogms", "oak grove", "middle school"], "weight": 0.8}
    },
    "age": 12,
    "grade": "7th"
  }'
);

-- Charlie (9, 4th grade)
INSERT INTO entities (id, entity_type, name, domain, attributes) VALUES (
  gen_random_uuid(),
  'family_member',
  'Charlie',
  'family',
  '{
    "calendar_keywords": {
      "sports": {"keywords": ["evaa", "eastview", "youth"], "weight": 1.0},
      "school": {"keywords": ["oak ridge", "oak ridge elementary", "ore"], "weight": 0.8}
    },
    "age": 9,
    "grade": "4th"
  }'
);
```

---

## Appendix: Manifest.json

```json
{
  "name": "calendar_subscribe",
  "description": "Subscribe to external calendar feeds (ICS/iCal) with automatic family member inference and custom naming",
  "version": "1.0.0",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "enum": ["preview", "subscribe", "list", "unsubscribe"],
        "description": "Action to perform"
      },
      "url": {
        "type": "string",
        "description": "Calendar subscription URL (webcal://, https://, or http://)"
      },
      "display_name": {
        "type": "string",
        "description": "Custom display name for the calendar (optional, will be inferred if not provided)"
      },
      "owner": {
        "type": "string",
        "description": "Family member who owns this calendar (optional, will be inferred if not provided)"
      },
      "subscription_id": {
        "type": "string",
        "description": "Subscription ID for unsubscribe action"
      }
    },
    "required": ["action"]
  }
}
```
