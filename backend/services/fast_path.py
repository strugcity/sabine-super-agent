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
import logging
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
# Entity Extraction Stub
# =============================================================================

async def extract_entities_stub(message: str) -> List[ExtractedEntity]:
    """
    Stub entity extraction from a user message.

    Performs basic pattern matching to extract proper nouns, dates,
    and location-like words. This is a placeholder for the full
    Claude Haiku-powered extraction pipeline in Phase 2.

    Args:
        message: Raw user message text.

    Returns:
        List of ``ExtractedEntity`` objects with name, type, and confidence.

    .. todo::
        Phase 2: Replace with Claude Haiku-based NER pipeline for
        production-grade entity extraction with context awareness.
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


# =============================================================================
# Embedding Generation Stub
# =============================================================================

async def generate_embedding_stub(message: str) -> List[float]:
    """
    Stub embedding generation for a user message.

    Returns a deterministic placeholder embedding vector of 1536 dimensions.
    This is a placeholder for the real OpenAI / Voyage embedding call.

    Args:
        message: Raw user message text.

    Returns:
        List of 1536 floats representing the placeholder embedding.

    .. todo::
        Phase 2: Replace with actual embedding API call
        (OpenAI text-embedding-3-small or Voyage).
    """
    # Deterministic stub: hash-based seed for reproducibility
    import hashlib

    digest = hashlib.sha256(message.encode()).digest()
    seed_val = int.from_bytes(digest[:4], "big")

    # Generate a simple deterministic vector
    embedding: List[float] = []
    for i in range(1536):
        # Simple deterministic float in [-1, 1]
        val = ((seed_val + i * 7919) % 10000) / 10000.0 * 2.0 - 1.0
        embedding.append(round(val, 6))

    return embedding


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
        entity_task = extract_entities_stub(message)
        embedding_task = generate_embedding_stub(message)

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
