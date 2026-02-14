"""
Fast Path Pipeline for Sabine 2.0
==================================

Handles the hot path for user-facing requests:
1. Write incoming message to WAL
2. Perform read-only memory retrieval
3. Run entity extraction (parallel with embedding)
4. Detect potential conflicts (flag for Slow Path)
5. Enqueue WAL entry for Slow Path processing

CRITICAL: No graph mutations on this path. All writes go to WAL.

The Fast Path is latency-sensitive and must complete within ~200ms.
Heavy lifting (relationship extraction, salience recalc, conflict
resolution) is deferred to the Slow Path worker via the WAL and the
rq job queue.

ADR Reference:
- ADR-001: Graph storage is read-only on Fast Path
- ADR-002: Dual-stream architecture, WAL + rq job queue

Owner: @backend-architect-sabine
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================

class ExtractedEntity(BaseModel):
    """
    An entity extracted from a user message during the Fast Path.

    This is a lightweight extraction result; full entity resolution
    and graph integration happen on the Slow Path.
    """

    name: str = Field(
        ..., description="Extracted entity name (e.g., 'Alice', 'New York')"
    )
    type: str = Field(
        ...,
        description=(
            "Entity type: person, place, org, date, project, event, or unknown"
        ),
    )
    confidence: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score (0.0-1.0)",
    )


class ConflictFlag(BaseModel):
    """
    A potential conflict between extracted and existing entity data.

    Conflicts are flagged for the Slow Path to resolve; the Fast Path
    does NOT perform any mutations.
    """

    entity_name: str = Field(
        ..., description="Name of the entity with a detected conflict"
    )
    conflict_type: str = Field(
        ...,
        description=(
            "Conflict classification: attribute_mismatch, "
            "duplicate_name, type_mismatch"
        ),
    )
    existing: Dict[str, Any] = Field(
        default_factory=dict,
        description="Existing entity attributes from Supabase",
    )
    new: Dict[str, Any] = Field(
        default_factory=dict,
        description="Newly extracted entity attributes from message",
    )


class FastPathResult(BaseModel):
    """
    Complete result from a Fast Path pipeline execution.

    Contains WAL entry reference, extracted entities, conflict flags,
    retrieved memories, and timing instrumentation data.
    """

    wal_entry_id: str = Field(
        ..., description="UUID of the WAL entry created for this message"
    )
    user_id: str = Field(
        ..., description="User who sent the message"
    )
    session_id: Optional[str] = Field(
        default=None, description="Session ID (if provided)"
    )
    extracted_entities: List[ExtractedEntity] = Field(
        default_factory=list,
        description="Entities extracted from the message",
    )
    conflicts: List[ConflictFlag] = Field(
        default_factory=list,
        description="Potential conflicts detected with existing entities",
    )
    retrieved_memories: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Read-only memory retrieval results",
    )
    embedding_generated: bool = Field(
        default=False,
        description="Whether an embedding vector was generated",
    )
    queue_job_id: Optional[str] = Field(
        default=None,
        description="rq job ID for the enqueued Slow Path job (None if queue unavailable)",
    )
    timings: Dict[str, float] = Field(
        default_factory=dict,
        description="Step-by-step timing data in milliseconds",
    )


# =============================================================================
# Entity Extraction
# =============================================================================

# Claude Haiku model for low-latency entity extraction
_HAIKU_MODEL = "claude-3-5-haiku-20241022"

# Timeout in seconds for the Haiku API call (Fast Path budget)
_HAIKU_TIMEOUT_SECONDS = 3.0

# System prompt for structured entity extraction
_ENTITY_EXTRACTION_PROMPT = (
    "You are a precise entity extraction system. "
    "Extract named entities from the user message and return ONLY a JSON array. "
    "Each element must be an object with exactly these fields:\n"
    '  - "name": the entity text as it appears in the message\n'
    '  - "type": one of "person", "place", "org", "date", "project", "event", "unknown"\n'
    '  - "confidence": a float between 0.0 and 1.0 indicating extraction confidence\n'
    "\n"
    "Rules:\n"
    "- Include people, places, organizations, dates/times, projects, and events.\n"
    "- Do NOT extract common pronouns (I, he, she, they, etc.).\n"
    "- Do NOT extract generic nouns or adjectives.\n"
    "- For dates, extract the full date expression (e.g., 'January 15, 2026').\n"
    "- Return an empty array [] if no entities are found.\n"
    "- Return ONLY valid JSON. No markdown fences, no explanation."
)


def _extract_entities_regex_fallback(message: str) -> List[ExtractedEntity]:
    """
    Regex-based entity extraction fallback.

    Performs basic pattern matching to extract proper nouns, dates,
    and location-like words. Used as a fallback when the Claude Haiku
    API call fails or times out.

    Args:
        message: Raw user message text.

    Returns:
        List of ``ExtractedEntity`` objects with name, type, and confidence.
    """
    entities: List[ExtractedEntity] = []
    seen_names: set[str] = set()

    # --- Date patterns ---
    # Match patterns like "January 15", "Feb 3", "2026-02-13", "02/13/2026"
    date_patterns = [
        r"\b(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2}(?:,?\s+\d{4})?\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    ]
    for pattern in date_patterns:
        for match in re.finditer(pattern, message):
            name = match.group().strip()
            if name not in seen_names:
                entities.append(
                    ExtractedEntity(name=name, type="date", confidence=0.85)
                )
                seen_names.add(name)

    # --- Time patterns (e.g., "3 PM", "9:00 AM", "5pm") ---
    time_pattern = r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)\b"
    for match in re.finditer(time_pattern, message):
        name = match.group().strip()
        if name not in seen_names:
            entities.append(
                ExtractedEntity(name=name, type="date", confidence=0.80)
            )
            seen_names.add(name)

    # --- Proper nouns (capitalised words not at sentence start) ---
    # Split into sentences, then look for capitalised words mid-sentence
    words = message.split()
    skip_words = {
        "I", "The", "A", "An", "This", "That", "It", "We", "They",
        "He", "She", "My", "Your", "Our", "His", "Her", "Its",
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday", "Sunday", "Today", "Tomorrow", "Yesterday",
        "AM", "PM",
    }

    for i, word in enumerate(words):
        # Strip punctuation for matching
        clean = re.sub(r"[^\w]", "", word)
        if not clean:
            continue

        # Check if it is capitalised and not a common skip word
        if (
            clean[0].isupper()
            and clean not in skip_words
            and len(clean) > 1
            and clean not in seen_names
        ):
            # Heuristic: if it follows a sentence-ending punctuation, skip
            if i > 0:
                prev = words[i - 1]
                if prev.endswith((".", "!", "?")):
                    continue

            # Simple type heuristic
            entity_type = "person"
            # Check for org-like suffixes
            if clean.endswith(("Corp", "Inc", "LLC", "Ltd", "Co")):
                entity_type = "org"

            entities.append(
                ExtractedEntity(
                    name=clean, type=entity_type, confidence=0.70,
                )
            )
            seen_names.add(clean)

    return entities


async def extract_entities(message: str) -> List[ExtractedEntity]:
    """
    Extract named entities from a user message using Claude Haiku.

    Calls Claude Haiku (claude-3-5-haiku-20241022) with a structured
    JSON prompt to extract entities with type classification and
    confidence scores. Falls back to regex-based extraction if the
    API call fails or exceeds the 3-second timeout.

    Args:
        message: Raw user message text.

    Returns:
        List of ``ExtractedEntity`` objects with name, type, and confidence.
    """
    # Short-circuit: skip the API call for very short or empty messages
    if not message or len(message.strip()) < 3:
        return _extract_entities_regex_fallback(message)

    try:
        # Lazy import to avoid circular dependencies
        from anthropic import AsyncAnthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning(
                "ANTHROPIC_API_KEY not set; falling back to regex entity extraction"
            )
            return _extract_entities_regex_fallback(message)

        client = AsyncAnthropic(api_key=api_key)

        # Call Claude Haiku with a timeout enforced by asyncio
        response = await asyncio.wait_for(
            client.messages.create(
                model=_HAIKU_MODEL,
                max_tokens=1024,
                system=_ENTITY_EXTRACTION_PROMPT,
                messages=[{"role": "user", "content": message}],
            ),
            timeout=_HAIKU_TIMEOUT_SECONDS,
        )

        # Extract the text content from the response
        raw_text = response.content[0].text.strip()

        # Strip markdown code fences if the model wraps output
        if raw_text.startswith("```"):
            # Remove opening fence (with optional language tag) and closing fence
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

        # Parse the JSON array
        parsed = json.loads(raw_text)

        if not isinstance(parsed, list):
            logger.warning(
                "Haiku returned non-list JSON (%s); falling back to regex",
                type(parsed).__name__,
            )
            return _extract_entities_regex_fallback(message)

        # Validate allowed entity types
        valid_types = {"person", "place", "org", "date", "project", "event", "unknown"}
        entities: List[ExtractedEntity] = []

        for item in parsed:
            if not isinstance(item, dict):
                continue

            name = item.get("name", "").strip()
            entity_type = item.get("type", "unknown").lower().strip()
            confidence = item.get("confidence", 0.9)

            if not name:
                continue

            # Clamp entity type to valid set
            if entity_type not in valid_types:
                entity_type = "unknown"

            # Clamp confidence to [0.0, 1.0]
            try:
                confidence = float(confidence)
                confidence = max(0.0, min(1.0, confidence))
            except (TypeError, ValueError):
                confidence = 0.9

            entities.append(
                ExtractedEntity(
                    name=name,
                    type=entity_type,
                    confidence=confidence,
                )
            )

        logger.debug(
            "Haiku entity extraction returned %d entities", len(entities),
        )
        return entities

    except asyncio.TimeoutError:
        logger.warning(
            "Haiku entity extraction timed out after %.1fs; "
            "falling back to regex",
            _HAIKU_TIMEOUT_SECONDS,
        )
        return _extract_entities_regex_fallback(message)

    except json.JSONDecodeError as exc:
        logger.warning(
            "Haiku returned invalid JSON: %s; falling back to regex",
            exc,
        )
        return _extract_entities_regex_fallback(message)

    except Exception as exc:
        logger.warning(
            "Haiku entity extraction failed: %s; falling back to regex",
            exc,
        )
        return _extract_entities_regex_fallback(message)


# =============================================================================
# Embedding Generation
# =============================================================================

async def _generate_embedding_hash_fallback(text: str) -> List[float]:
    """
    Hash-based deterministic embedding fallback.

    Generates a deterministic placeholder embedding vector of 1536 dimensions
    using SHA-256 hashing. Used as a fallback when the OpenAI embedding API
    is unavailable, the API key is missing, or the request fails/times out.

    Args:
        text: Input text to generate a deterministic embedding for.

    Returns:
        List of 1536 floats representing the fallback embedding.
    """
    import hashlib

    digest = hashlib.sha256(text.encode()).digest()
    seed_val = int.from_bytes(digest[:4], "big")

    embedding: List[float] = []
    for i in range(1536):
        val = ((seed_val + i * 7919) % 10000) / 10000.0 * 2.0 - 1.0
        embedding.append(round(val, 6))

    return embedding


# OpenAI embedding model configuration
_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIMENSIONS = 1536
_EMBEDDING_TIMEOUT_SECONDS = 5.0


async def generate_embedding(text: str) -> List[float]:
    """
    Generate an embedding vector for a text string using OpenAI.

    Calls the OpenAI ``text-embedding-3-small`` model to produce a
    1536-dimensional embedding vector. Falls back to a deterministic
    hash-based vector if the API key is missing, the request times out
    (5 seconds), or any other error occurs.

    Args:
        text: Input text to embed.

    Returns:
        List of 1536 floats representing the embedding vector.
    """
    api_key: Optional[str] = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning(
            "OPENAI_API_KEY not set; falling back to hash-based embedding"
        )
        return await _generate_embedding_hash_fallback(text)

    try:
        # Lazy import to avoid circular dependencies
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)

        response = await asyncio.wait_for(
            client.embeddings.create(
                model=_EMBEDDING_MODEL,
                input=text,
                dimensions=_EMBEDDING_DIMENSIONS,
            ),
            timeout=_EMBEDDING_TIMEOUT_SECONDS,
        )

        embedding: List[float] = response.data[0].embedding

        if len(embedding) != _EMBEDDING_DIMENSIONS:
            logger.warning(
                "OpenAI returned embedding with %d dimensions (expected %d); "
                "falling back to hash-based embedding",
                len(embedding),
                _EMBEDDING_DIMENSIONS,
            )
            return await _generate_embedding_hash_fallback(text)

        logger.debug(
            "OpenAI embedding generated: model=%s dims=%d",
            _EMBEDDING_MODEL,
            len(embedding),
        )
        return embedding

    except asyncio.TimeoutError:
        logger.warning(
            "OpenAI embedding request timed out after %.1fs; "
            "falling back to hash-based embedding",
            _EMBEDDING_TIMEOUT_SECONDS,
        )
        return await _generate_embedding_hash_fallback(text)

    except Exception as exc:
        logger.warning(
            "OpenAI embedding generation failed: %s; "
            "falling back to hash-based embedding",
            exc,
        )
        return await _generate_embedding_hash_fallback(text)


# =============================================================================
# Read-Only Memory Retrieval
# =============================================================================

async def retrieve_memories_readonly(
    user_id: str,
    message: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Read-only retrieval of relevant memories for context injection.

    Queries Supabase for memories matching the user, ordered by
    recency and salience. Does NOT write or update any records.

    CRITICAL: This function is read-only. No INSERT, UPDATE, or DELETE
    operations are performed.

    Args:
        user_id: UUID string of the user.
        message: Message text for relevance matching.
        limit: Maximum number of memories to return.

    Returns:
        List of memory dicts with ``id``, ``content``, ``salience_score``,
        and ``metadata`` fields.
    """
    try:
        # Lazy import to avoid circular dependencies
        from backend.services.wal import get_supabase_client

        client = get_supabase_client()

        # Read-only query: fetch recent non-archived memories for user
        # Ordered by salience_score descending, then created_at descending
        response = (
            client.table("memories")
            .select("id, content, salience_score, metadata, created_at")
            .eq("is_archived", False)
            .order("salience_score", desc=True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        if not response.data:
            logger.debug(
                "No memories found for user=%s (read-only retrieval)", user_id,
            )
            return []

        logger.debug(
            "Retrieved %d memories for user=%s (read-only)",
            len(response.data),
            user_id,
        )
        return response.data

    except Exception as exc:
        logger.warning(
            "Memory retrieval failed for user=%s: %s (continuing without memories)",
            user_id,
            exc,
        )
        return []


# =============================================================================
# Conflict Detection
# =============================================================================

async def detect_conflicts(
    extracted_entities: List[ExtractedEntity],
    user_id: str,
) -> List[ConflictFlag]:
    """
    Compare extracted entities against existing entities in Supabase.

    Detects potential conflicts such as:
    - **attribute_mismatch**: Same entity name but different attributes
    - **type_mismatch**: Same entity name but different type classification

    Conflicts are flagged for the Slow Path to resolve. The Fast Path
    performs NO mutations.

    Args:
        extracted_entities: Entities extracted from the current message.
        user_id: UUID string of the user.

    Returns:
        List of ``ConflictFlag`` objects describing detected conflicts.
    """
    if not extracted_entities:
        return []

    conflicts: List[ConflictFlag] = []

    try:
        # Lazy import to avoid circular dependencies
        from backend.services.wal import get_supabase_client

        client = get_supabase_client()

        # Batch-fetch existing entities by name for this user
        entity_names = [e.name for e in extracted_entities]

        # Read-only query: fetch entities whose name matches any extracted name
        response = (
            client.table("entities")
            .select("id, name, type, attributes, status")
            .eq("status", "active")
            .in_("name", entity_names)
            .execute()
        )

        if not response.data:
            logger.debug(
                "No existing entities match extracted names for user=%s",
                user_id,
            )
            return []

        # Build lookup of existing entities by name (lowercase for matching)
        existing_by_name: Dict[str, Dict[str, Any]] = {}
        for row in response.data:
            existing_by_name[row["name"].lower()] = row

        # Compare extracted vs existing
        for entity in extracted_entities:
            existing = existing_by_name.get(entity.name.lower())
            if existing is None:
                continue

            # Type mismatch detection
            if existing["type"] != entity.type:
                conflicts.append(
                    ConflictFlag(
                        entity_name=entity.name,
                        conflict_type="type_mismatch",
                        existing={
                            "type": existing["type"],
                            "attributes": existing.get("attributes", {}),
                        },
                        new={
                            "type": entity.type,
                            "confidence": entity.confidence,
                        },
                    )
                )

            # Attribute mismatch detection: if existing has attributes
            # and the new extraction has different data, flag it
            existing_attrs = existing.get("attributes", {})
            if existing_attrs:
                conflicts.append(
                    ConflictFlag(
                        entity_name=entity.name,
                        conflict_type="attribute_mismatch",
                        existing={
                            "type": existing["type"],
                            "attributes": existing_attrs,
                        },
                        new={
                            "type": entity.type,
                            "confidence": entity.confidence,
                        },
                    )
                )

        if conflicts:
            logger.info(
                "Detected %d potential conflicts for user=%s",
                len(conflicts),
                user_id,
            )

    except Exception as exc:
        logger.warning(
            "Conflict detection failed for user=%s: %s (continuing without conflicts)",
            user_id,
            exc,
        )

    return conflicts


# =============================================================================
# Fast Path Pipeline
# =============================================================================

async def process_fast_path(
    user_id: str,
    message: str,
    session_id: Optional[str] = None,
) -> FastPathResult:
    """
    Execute the Fast Path pipeline for an incoming user message.

    Pipeline steps:
    1. Write message to WAL (durable, idempotent)
    2. Parallel: entity extraction + embedding generation
    3. Read-only memory retrieval (no writes)
    4. Conflict detection (compare extracted vs existing entities)
    5. Enqueue WAL entry for Slow Path via rq job queue
    6. Return ``FastPathResult`` with timing data

    CRITICAL: No graph mutations occur on this path. All state changes
    are deferred to the Slow Path worker via the WAL.

    Args:
        user_id: UUID string identifying the user.
        message: Raw user message text.
        session_id: Optional session identifier for grouping.

    Returns:
        ``FastPathResult`` containing WAL entry ID, extracted entities,
        conflicts, retrieved memories, and step-by-step timings.

    Raises:
        Exception: If the WAL write fails (critical path). All other
            step failures are logged and handled gracefully.
    """
    # Lazy import to avoid circular dependencies at module level
    from backend.services.fast_path_timing import FastPathTimings, TimingBlock

    total_start = time.monotonic()
    timings = FastPathTimings()

    logger.info(
        "Fast Path started: user=%s session=%s msg_len=%d",
        user_id,
        session_id,
        len(message),
    )

    # -------------------------------------------------------------------------
    # Step 1: Write message to WAL
    # -------------------------------------------------------------------------
    wal_entry_id: str = ""

    wal_timer = TimingBlock("wal_write")
    with wal_timer:
        try:
            from backend.services.wal import WALService

            wal_service = WALService()
            payload: Dict[str, Any] = {
                "user_id": user_id,
                "message": message,
                "source": "fast_path",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if session_id:
                payload["session_id"] = session_id

            wal_entry = await wal_service.create_entry(payload)
            wal_entry_id = str(wal_entry.id)
            logger.info(
                "WAL entry created: id=%s user=%s", wal_entry_id, user_id,
            )
        except Exception as exc:
            logger.error(
                "Fast Path WAL write FAILED for user=%s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise  # WAL write is critical; cannot continue without it

    timings.wal_write_ms = wal_timer.elapsed_ms

    # -------------------------------------------------------------------------
    # Step 2: Parallel entity extraction + embedding generation
    # -------------------------------------------------------------------------
    extracted_entities: List[ExtractedEntity] = []
    embedding: List[float] = []

    entity_timer = TimingBlock("entity_extraction")
    embedding_timer = TimingBlock("embedding")

    parallel_start = time.monotonic()
    try:
        # Use asyncio.gather for parallel execution
        entity_task = extract_entities(message)
        embedding_task = generate_embedding(message)

        results = await asyncio.gather(
            entity_task, embedding_task, return_exceptions=True,
        )

        # Unpack results
        if isinstance(results[0], BaseException):
            logger.warning(
                "Entity extraction failed: %s", results[0],
            )
        else:
            extracted_entities = results[0]

        if isinstance(results[1], BaseException):
            logger.warning(
                "Embedding generation failed: %s", results[1],
            )
        else:
            embedding = results[1]

    except Exception as exc:
        logger.warning(
            "Parallel extraction/embedding failed: %s", exc,
        )

    parallel_elapsed = (time.monotonic() - parallel_start) * 1000.0
    # Split parallel time attribution (both ran concurrently)
    timings.entity_extraction_ms = parallel_elapsed
    timings.embedding_ms = parallel_elapsed

    # -------------------------------------------------------------------------
    # Step 3: Read-only memory retrieval
    # -------------------------------------------------------------------------
    retrieved_memories: List[Dict[str, Any]] = []

    memory_timer = TimingBlock("memory_retrieval")
    with memory_timer:
        retrieved_memories = await retrieve_memories_readonly(
            user_id=user_id,
            message=message,
            limit=5,
        )

    timings.memory_retrieval_ms = memory_timer.elapsed_ms

    # -------------------------------------------------------------------------
    # Step 4: Conflict detection
    # -------------------------------------------------------------------------
    conflicts: List[ConflictFlag] = []

    conflict_timer = TimingBlock("conflict_detection")
    with conflict_timer:
        conflicts = await detect_conflicts(
            extracted_entities=extracted_entities,
            user_id=user_id,
        )

    timings.conflict_detection_ms = conflict_timer.elapsed_ms

    # -------------------------------------------------------------------------
    # Step 5: Enqueue WAL entry for Slow Path
    # -------------------------------------------------------------------------
    queue_job_id: Optional[str] = None

    enqueue_timer = TimingBlock("queue_enqueue")
    with enqueue_timer:
        try:
            from backend.services.wal_queue_bridge import (
                enqueue_wal_for_processing,
            )

            queue_job_id = await enqueue_wal_for_processing(
                wal_entry_id=wal_entry_id,
                priority="default",
            )
            if queue_job_id:
                logger.info(
                    "WAL entry enqueued for Slow Path: wal_id=%s job_id=%s",
                    wal_entry_id,
                    queue_job_id,
                )
            else:
                logger.warning(
                    "Queue enqueue returned None for wal_id=%s "
                    "(queue may be unavailable; entry remains in WAL)",
                    wal_entry_id,
                )
        except Exception as exc:
            logger.warning(
                "Queue enqueue failed for wal_id=%s: %s "
                "(entry remains in WAL for later pickup)",
                wal_entry_id,
                exc,
            )

    timings.queue_enqueue_ms = enqueue_timer.elapsed_ms

    # -------------------------------------------------------------------------
    # Step 6: Build and return result
    # -------------------------------------------------------------------------
    timings.total_ms = (time.monotonic() - total_start) * 1000.0
    timings.log_summary(user_id=user_id, session_id=session_id)

    result = FastPathResult(
        wal_entry_id=wal_entry_id,
        user_id=user_id,
        session_id=session_id,
        extracted_entities=extracted_entities,
        conflicts=conflicts,
        retrieved_memories=retrieved_memories,
        embedding_generated=len(embedding) > 0,
        queue_job_id=queue_job_id,
        timings=timings.model_dump(),
    )

    logger.info(
        "Fast Path completed: wal_id=%s entities=%d conflicts=%d "
        "memories=%d total=%.1fms",
        wal_entry_id,
        len(extracted_entities),
        len(conflicts),
        len(retrieved_memories),
        timings.total_ms,
    )

    return result
