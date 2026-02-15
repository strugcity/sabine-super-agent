"""
Slow Path Consolidation Pipeline for Sabine 2.0
=================================================

Processes WAL entries asynchronously in the background worker:

1. Read unprocessed WAL entries from Supabase
2. Extract relationships using Claude Haiku
3. Update entity records
4. Resolve conflicts flagged by Fast Path
5. Checkpoint progress for crash recovery
6. Mark WAL entries as processed

ADR References:
    - ADR-002 (rq worker architecture, retry config)
    - ADR-001 (entity_relationships graph storage schema)
    - ADR-004 (cold storage archival trigger criteria)

The public entry points are :func:`consolidate_wal_entry` (single entry)
and :func:`consolidate_wal_batch` (batch with checkpointing), which are
called by the rq job handlers in ``backend/worker/jobs.py``.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from backend.magma.taxonomy import is_valid_predicate, infer_layer, GraphLayer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-entry consolidation
# ---------------------------------------------------------------------------

def consolidate_wal_entry(wal_entry_id: str) -> "ConsolidationResult":
    """
    Process a single WAL entry through the Slow Path pipeline.

    This is the synchronous wrapper called by rq.  It delegates to
    the async implementation via ``asyncio.run()``.

    Parameters
    ----------
    wal_entry_id : str
        UUID (as string) of the WAL entry to process.

    Returns
    -------
    ConsolidationResult
        Pydantic model with processing stats.
    """
    return asyncio.run(_async_consolidate_entry(wal_entry_id))


async def _async_consolidate_entry(wal_entry_id: str) -> "ConsolidationResult":
    """
    Async implementation of single-entry consolidation.

    Steps:
        1. Read WAL entry from Supabase
        2. Parse raw_payload for message content
        3. Extract entities from the message
        4. Run relationship extraction
        5. Resolve entities against existing records
        6. Resolve any conflict flags from Fast Path
        7. Mark WAL entry as completed
        8. Return consolidation stats

    Parameters
    ----------
    wal_entry_id : str
        UUID (as string) of the WAL entry.

    Returns
    -------
    ConsolidationResult
    """
    # Lazy imports to avoid circular dependencies at module load time
    from backend.services.wal import WALService
    from lib.db.models import ConsolidationResult

    start: float = time.monotonic()
    wal_service = WALService()

    # 1. Read WAL entry -------------------------------------------------------
    entry = await wal_service.get_entry_by_id(UUID(wal_entry_id))

    if entry is None:
        logger.warning(
            "WAL entry not found: %s (may have been already processed)",
            wal_entry_id,
        )
        elapsed_ms = (time.monotonic() - start) * 1000.0
        return ConsolidationResult(
            wal_entry_id=wal_entry_id,
            status="skipped",
            duration_ms=round(elapsed_ms, 1),
        )

    # If already completed, skip
    if entry.status in ("completed",):
        logger.info(
            "WAL entry %s already completed; skipping", wal_entry_id,
        )
        elapsed_ms = (time.monotonic() - start) * 1000.0
        return ConsolidationResult(
            wal_entry_id=wal_entry_id,
            status="skipped",
            duration_ms=round(elapsed_ms, 1),
        )

    # Mark as processing
    worker_id = f"slow-path-{UUID(wal_entry_id).hex[:8]}"
    await wal_service.mark_processing(entry.id, worker_id)

    try:
        # 2. Parse raw_payload ----------------------------------------------------
        raw_payload: Dict[str, Any] = entry.raw_payload or {}
        message: str = raw_payload.get("message", "")
        user_id: str = raw_payload.get("user_id", "")

        if not message:
            logger.warning(
                "WAL entry %s has no message in raw_payload; marking completed",
                wal_entry_id,
            )
            await wal_service.mark_completed(entry.id)
            elapsed_ms = (time.monotonic() - start) * 1000.0
            return ConsolidationResult(
                wal_entry_id=wal_entry_id,
                status="processed",
                duration_ms=round(elapsed_ms, 1),
            )

        # 3. Extract entities from message (simple heuristic for now) ----------
        entities_in_payload: List[Dict[str, Any]] = raw_payload.get(
            "entities", []
        )

        # 4. Run relationship extraction ----------------------------------------
        relationships: List[Dict[str, Any]] = extract_relationships(
            message=message,
            entities=entities_in_payload,
            source_wal_id=wal_entry_id,
        )

        # 5. Resolve entities --------------------------------------------------
        entities_resolved: int = 0
        resolve_results: List[Dict[str, Any]] = []
        for entity_data in entities_in_payload:
            try:
                resolve_result = await _async_resolve_entity(
                    entity_data=entity_data,
                    user_id=user_id,
                )
                resolve_results.append(resolve_result)
                if resolve_result.get("action") in ("created", "updated"):
                    entities_resolved += 1
            except Exception as entity_exc:
                logger.warning(
                    "Entity resolution failed for %s in WAL %s: %s",
                    entity_data.get("name", "unknown"),
                    wal_entry_id,
                    entity_exc,
                )
                resolve_results.append({"action": "failed", "entity_id": None})

        # 6. Persist extracted relationships -----------------------------------
        relationships_stored: int = 0
        if relationships and entities_in_payload:
            try:
                # Lazy import to avoid circular deps
                from backend.magma.store import (
                    build_entity_name_to_id,
                    store_relationships,
                )

                entity_name_to_id: Dict[str, str] = build_entity_name_to_id(
                    entities=entities_in_payload,
                    resolve_results=resolve_results,
                )

                store_result: Dict[str, Any] = await store_relationships(
                    relationships=relationships,
                    entity_name_to_id=entity_name_to_id,
                    source_wal_id=wal_entry_id,
                )
                relationships_stored = store_result.get("stored", 0)

                if store_result.get("errors"):
                    logger.warning(
                        "Relationship storage had %d errors for WAL %s",
                        len(store_result["errors"]),
                        wal_entry_id,
                    )
            except Exception as rel_exc:
                logger.error(
                    "Relationship storage failed for WAL %s: %s",
                    wal_entry_id,
                    rel_exc,
                    exc_info=True,
                )

        # 7. Resolve conflicts -------------------------------------------------
        conflicts: List[Dict[str, Any]] = raw_payload.get("conflicts", [])
        conflict_results: List[Dict[str, Any]] = resolve_conflicts(
            conflicts=conflicts,
            wal_entry_id=wal_entry_id,
        )

        # 8. Mark WAL entry as completed ---------------------------------------
        await wal_service.mark_completed(entry.id)

        elapsed_ms = (time.monotonic() - start) * 1000.0

        logger.info(
            "Consolidated WAL entry %s: entities=%d  relationships=%d "
            "(stored=%d)  conflicts=%d  elapsed=%.0fms",
            wal_entry_id,
            entities_resolved,
            len(relationships),
            relationships_stored,
            len(conflict_results),
            elapsed_ms,
        )

        return ConsolidationResult(
            wal_entry_id=wal_entry_id,
            status="processed",
            entities_resolved=entities_resolved,
            relationships_extracted=len(relationships),
            relationships_stored=relationships_stored,
            conflicts_resolved=len(conflict_results),
            duration_ms=round(elapsed_ms, 1),
        )

    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        error_msg = str(exc)
        logger.error(
            "Consolidation failed for WAL entry %s: %s",
            wal_entry_id,
            error_msg,
            exc_info=True,
        )

        # Mark as failed with retry logic
        await wal_service.mark_failed(entry.id, error_msg)

        return ConsolidationResult(
            wal_entry_id=wal_entry_id,
            status="failed",
            duration_ms=round(elapsed_ms, 1),
            error=error_msg,
        )


# ---------------------------------------------------------------------------
# Batch consolidation with checkpointing
# ---------------------------------------------------------------------------

def consolidate_wal_batch(
    wal_entry_ids: List[str],
    checkpoint_interval: int = 100,
) -> "BatchConsolidationResult":
    """
    Process a batch of WAL entries with periodic checkpointing.

    This is the synchronous wrapper called by rq.

    Parameters
    ----------
    wal_entry_ids : list[str]
        Ordered list of WAL entry UUIDs (processed FIFO).
    checkpoint_interval : int
        Save a checkpoint every N entries (default: 100).

    Returns
    -------
    BatchConsolidationResult
        Aggregate stats for the batch.
    """
    return asyncio.run(
        _async_consolidate_batch(wal_entry_ids, checkpoint_interval)
    )


async def _async_consolidate_batch(
    wal_entry_ids: List[str],
    checkpoint_interval: int = 100,
) -> "BatchConsolidationResult":
    """
    Async implementation of batch consolidation with checkpointing.

    Parameters
    ----------
    wal_entry_ids : list[str]
        WAL entry UUIDs in processing order.
    checkpoint_interval : int
        Checkpoint frequency.

    Returns
    -------
    BatchConsolidationResult
    """
    # Lazy imports
    from backend.worker.checkpoint import CheckpointManager
    from lib.db.models import BatchConsolidationResult

    batch_id: str = uuid4().hex[:16]
    start: float = time.monotonic()

    checkpoint_mgr = CheckpointManager(batch_id=batch_id)
    total: int = len(wal_entry_ids)
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    checkpoint_count: int = 0

    # Attempt to resume from a prior checkpoint
    resume_index: int = 0
    existing_checkpoint = checkpoint_mgr.load()
    if existing_checkpoint is not None:
        resume_index = existing_checkpoint.get("last_processed_index", -1) + 1
        processed = existing_checkpoint.get("entries_processed", 0)
        failed = existing_checkpoint.get("entries_failed", 0)
        skipped = existing_checkpoint.get("entries_skipped", 0)
        checkpoint_count = existing_checkpoint.get("checkpoint_count", 0)
        logger.info(
            "Resuming batch %s from index %d (processed=%d, failed=%d)",
            batch_id,
            resume_index,
            processed,
            failed,
        )

    logger.info(
        "Batch %s: processing %d entries (starting at index %d, "
        "checkpoint every %d)",
        batch_id,
        total,
        resume_index,
        checkpoint_interval,
    )

    for i in range(resume_index, total):
        entry_id = wal_entry_ids[i]

        try:
            result = await _async_consolidate_entry(entry_id)

            if result.status == "processed":
                processed += 1
            elif result.status == "skipped":
                skipped += 1
            else:
                failed += 1

        except Exception as exc:
            logger.error(
                "Batch %s: unexpected error at index %d (entry %s): %s",
                batch_id,
                i,
                entry_id,
                exc,
                exc_info=True,
            )
            failed += 1

        # Checkpoint periodically
        if (i + 1) % checkpoint_interval == 0 or i == total - 1:
            checkpoint_mgr.save(
                last_processed_index=i,
                metadata={
                    "entries_processed": processed,
                    "entries_failed": failed,
                    "entries_skipped": skipped,
                    "entries_remaining": total - (i + 1),
                    "checkpoint_count": checkpoint_count + 1,
                },
            )
            checkpoint_count += 1
            logger.info(
                "Batch %s: checkpoint at index %d  processed=%d  failed=%d",
                batch_id,
                i,
                processed,
                failed,
            )

    # Clear checkpoint after successful batch completion
    checkpoint_mgr.clear()

    elapsed_ms = (time.monotonic() - start) * 1000.0

    logger.info(
        "Batch %s DONE: total=%d  processed=%d  failed=%d  skipped=%d  "
        "checkpoints=%d  elapsed=%.0fms",
        batch_id,
        total,
        processed,
        failed,
        skipped,
        checkpoint_count,
        elapsed_ms,
    )

    return BatchConsolidationResult(
        batch_id=batch_id,
        total=total,
        processed=processed,
        failed=failed,
        skipped=skipped,
        duration_ms=round(elapsed_ms, 1),
        checkpoint_count=checkpoint_count,
    )


# ---------------------------------------------------------------------------
# Relationship extraction
# ---------------------------------------------------------------------------

_RELATIONSHIP_EXTRACTION_PROMPT = """\
You are a relationship extraction engine. Given a message and a list of known \
entities, extract all meaningful relationships as subject/predicate/object \
triples.

KNOWN ENTITIES:
{entity_list}

MESSAGE:
{message}

Return a JSON array of relationship objects. Each object MUST have exactly \
these fields:
- "subject": name of the source entity (must be one of the known entities)
- "predicate": relationship type as a snake_case verb phrase (e.g. "works_at", \
"lives_in", "married_to", "manages", "part_of", "knows", "reports_to", \
"collaborates_with", "founded", "attended", "located_in", "member_of")
- "object": name of the target entity (must be one of the known entities)
- "confidence": a float between 0.0 and 1.0 indicating your confidence
- "graph_layer": one of "semantic", "temporal", "causal", "entity"
  - "entity" for direct entity-to-entity relations (works_at, lives_in, etc.)
  - "semantic" for meaning/topic relations (related_to, similar_to, etc.)
  - "temporal" for time-based relations (preceded_by, happened_during, etc.)
  - "causal" for cause/effect relations (caused_by, led_to, etc.)

Rules:
- Both subject and object MUST be from the known entities list.
- Do NOT invent entities not in the list.
- Extract only relationships supported by the message text.
- If no relationships can be extracted, return an empty array: []

Return ONLY the JSON array, no other text or markdown formatting.\
"""


def extract_relationships(
    message: str,
    entities: List[Dict[str, Any]],
    source_wal_id: str = "",
) -> List[Dict[str, Any]]:
    """
    Extract relationships from message text using Claude Haiku.

    Calls Claude 3.5 Haiku to identify subject/predicate/object triples
    between known entities mentioned in the message.  Falls back to a
    simple heuristic if the API call fails.

    Parameters
    ----------
    message : str
        The message text to analyse.
    entities : list[dict]
        Entity dicts extracted by the Fast Path or other pipeline step.
    source_wal_id : str
        WAL entry ID for provenance tracking.

    Returns
    -------
    list[dict]
        Relationship dicts in the ``entity_relationships`` schema format
        (per ADR-001).
    """
    if not entities or len(entities) < 2:
        return []

    # Build the entity list string for the prompt
    entity_names: List[str] = [
        e.get("name", f"entity_{i}") for i, e in enumerate(entities)
    ]
    entity_list_str: str = "\n".join(f"- {name}" for name in entity_names)

    prompt: str = _RELATIONSHIP_EXTRACTION_PROMPT.format(
        entity_list=entity_list_str,
        message=message,
    )

    try:
        # Lazy imports to avoid circular deps and module-load overhead
        import json as _json
        import os as _os

        import anthropic

        api_key: str = _os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning(
                "ANTHROPIC_API_KEY not set; falling back to heuristic "
                "relationship extraction for WAL %s",
                source_wal_id,
            )
            return _extract_relationships_fallback(
                message, entities, source_wal_id,
            )

        client = anthropic.Anthropic(
            api_key=api_key,
            timeout=10.0,
        )

        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt},
            ],
        )

        # Extract the text content from the response
        raw_text: str = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        raw_text = raw_text.strip()

        # Parse the JSON response
        parsed: Any = _json.loads(raw_text)

        if not isinstance(parsed, list):
            logger.warning(
                "Haiku returned non-list JSON for WAL %s; falling back",
                source_wal_id,
            )
            return _extract_relationships_fallback(
                message, entities, source_wal_id,
            )

        # Validate and normalise each relationship
        entity_name_set = set(entity_names)
        relationships: List[Dict[str, Any]] = []

        for rel in parsed:
            if not isinstance(rel, dict):
                continue

            subject: str = rel.get("subject", "")
            predicate: str = rel.get("predicate", "").lower().replace(" ", "_")
            obj: str = rel.get("object", "")
            confidence: float = float(rel.get("confidence", 0.5))
            graph_layer: str = rel.get("graph_layer", "").lower()

            # Skip entries where subject/object aren't known entities
            if subject not in entity_name_set or obj not in entity_name_set:
                logger.debug(
                    "Skipping relationship with unknown entity: "
                    "%s -> %s -> %s (WAL %s)",
                    subject, predicate, obj, source_wal_id,
                )
                continue

            if not predicate:
                continue

            # Clamp confidence to [0.0, 1.0]
            confidence = max(0.0, min(1.0, confidence))

            # Validate predicate against canonical taxonomy
            if not is_valid_predicate(predicate):
                logger.warning("Non-canonical predicate '%s', falling back to 'related_to'", predicate)
                predicate = "related_to"

            # Infer correct layer from predicate (overrides Haiku's guess)
            inferred = infer_layer(predicate)
            if graph_layer and graph_layer != inferred.value:
                logger.debug(
                    "Correcting graph_layer: Haiku said '%s', taxonomy says '%s' for predicate '%s'",
                    graph_layer, inferred.value, predicate
                )
            graph_layer = inferred.value

            relationships.append({
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "confidence": confidence,
                "source_wal_id": source_wal_id,
                "graph_layer": graph_layer,
                "relationship_type": predicate,
            })

        logger.info(
            "Haiku extracted %d relationships from %d entities for WAL %s",
            len(relationships),
            len(entities),
            source_wal_id,
        )

        return relationships

    except Exception as exc:
        logger.error(
            "Haiku relationship extraction failed for WAL %s: %s  "
            "(falling back to heuristic)",
            source_wal_id,
            exc,
            exc_info=True,
        )
        return _extract_relationships_fallback(
            message, entities, source_wal_id,
        )


def _extract_relationships_fallback(
    message: str,
    entities: List[Dict[str, Any]],
    source_wal_id: str = "",
) -> List[Dict[str, Any]]:
    """
    Heuristic fallback for relationship extraction.

    Produces simple pairwise ``related_to`` relationships between
    consecutive entities.  Used when the Haiku API call is unavailable
    or fails.

    Parameters
    ----------
    message : str
        The message text (unused in the heuristic, kept for signature
        compatibility).
    entities : list[dict]
        Entity dicts.
    source_wal_id : str
        WAL entry ID for provenance tracking.

    Returns
    -------
    list[dict]
        Placeholder relationship dicts.
    """
    if not entities or len(entities) < 2:
        return []

    relationships: List[Dict[str, Any]] = []
    for i in range(len(entities) - 1):
        relationships.append({
            "subject": entities[i].get("name", f"entity_{i}"),
            "predicate": "related_to",
            "object": entities[i + 1].get("name", f"entity_{i + 1}"),
            "confidence": 0.8,
            "source_wal_id": source_wal_id,
            "graph_layer": "entity",
            "relationship_type": "related_to",
        })

    return relationships


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------

def resolve_entity(entity_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Synchronous wrapper for entity resolution.

    Parameters
    ----------
    entity_data : dict
        Entity data dict with at minimum ``name`` and ``type`` keys.
    user_id : str
        User ID for scoping the entity lookup.

    Returns
    -------
    dict
        ``{"action": "created" | "updated", "entity_id": "..."}``
    """
    return asyncio.run(_async_resolve_entity(entity_data, user_id))


async def _async_resolve_entity(
    entity_data: Dict[str, Any],
    user_id: str,
) -> Dict[str, Any]:
    """
    Resolve an entity against existing records in Supabase.

    - If an entity with the same ``name`` already exists: update its
      attributes and increment the mention count in metadata.
    - If no match: create a new entity record.

    Parameters
    ----------
    entity_data : dict
        Must contain ``name`` (str).  Optional: ``type``, ``domain``,
        ``attributes``.
    user_id : str
        User ID for scoping (stored in entity metadata).

    Returns
    -------
    dict
        ``{"action": "created" | "updated", "entity_id": "<uuid>"}``
    """
    entity_name: str = entity_data.get("name", "").strip()

    if not entity_name:
        logger.warning("Entity resolution skipped: empty name")
        return {"action": "skipped", "entity_id": None}

    # Lazy import for Supabase client (after early return to avoid
    # unnecessary connection when name is empty)
    from backend.services.wal import get_supabase_client

    client = get_supabase_client()

    entity_type: str = entity_data.get("type", "unknown")
    domain: str = entity_data.get("domain", "personal")
    attributes: Dict[str, Any] = entity_data.get("attributes", {})

    # Look up existing entity by name
    try:
        response = client.table("entities").select("*").ilike(
            "name", entity_name,
        ).limit(1).execute()
    except Exception as exc:
        logger.error(
            "Entity lookup failed for '%s': %s",
            entity_name, exc, exc_info=True,
        )
        raise

    if response.data and len(response.data) > 0:
        # Entity exists -- update attributes and increment mention count
        existing = response.data[0]
        existing_attrs: Dict[str, Any] = existing.get("attributes", {})
        mention_count: int = existing_attrs.get("mention_count", 0) + 1

        # Merge new attributes into existing
        merged_attrs = {**existing_attrs, **attributes}
        merged_attrs["mention_count"] = mention_count
        merged_attrs["last_mentioned_by"] = user_id
        merged_attrs["last_mentioned_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        try:
            client.table("entities").update({
                "attributes": merged_attrs,
            }).eq("id", existing["id"]).execute()
        except Exception as exc:
            logger.error(
                "Entity update failed for '%s' (id=%s): %s",
                entity_name, existing["id"], exc, exc_info=True,
            )
            raise

        logger.debug(
            "Entity updated: name=%s  id=%s  mentions=%d",
            entity_name, existing["id"], mention_count,
        )
        return {
            "action": "updated",
            "entity_id": existing["id"],
        }

    else:
        # New entity -- create
        new_attrs = {**attributes}
        new_attrs["mention_count"] = 1
        new_attrs["first_mentioned_by"] = user_id
        new_attrs["first_mentioned_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        insert_data: Dict[str, Any] = {
            "name": entity_name,
            "type": entity_type,
            "domain": domain,
            "attributes": new_attrs,
            "status": "active",
        }

        try:
            insert_response = client.table("entities").insert(
                insert_data
            ).execute()
        except Exception as exc:
            logger.error(
                "Entity creation failed for '%s': %s",
                entity_name, exc, exc_info=True,
            )
            raise

        new_id: Optional[str] = None
        if insert_response.data and len(insert_response.data) > 0:
            new_id = insert_response.data[0].get("id")

        logger.info(
            "Entity created: name=%s  type=%s  domain=%s  id=%s",
            entity_name, entity_type, domain, new_id,
        )
        return {
            "action": "created",
            "entity_id": new_id,
        }


# ---------------------------------------------------------------------------
# Conflict resolution
# ---------------------------------------------------------------------------

def resolve_conflicts(
    conflicts: List[Dict[str, Any]],
    wal_entry_id: str,
) -> List[Dict[str, Any]]:
    """
    Resolve conflict flags from the Fast Path.

    Strategy: **newer data wins**.  The most recent WAL entry takes
    precedence over older data.  Each resolution decision is logged
    for auditability.

    Parameters
    ----------
    conflicts : list[dict]
        Conflict flag dicts from ``raw_payload["conflicts"]``.
        Each dict should have ``field``, ``old_value``, ``new_value``,
        and optionally ``entity_id``.
    wal_entry_id : str
        The WAL entry that contains the newer data.

    Returns
    -------
    list[dict]
        Resolution results, each with ``conflict``, ``resolution``,
        and ``winner`` keys.
    """
    if not conflicts:
        return []

    results: List[Dict[str, Any]] = []

    for conflict in conflicts:
        field: str = conflict.get("field", "unknown")
        old_value: Any = conflict.get("old_value")
        new_value: Any = conflict.get("new_value")
        entity_id: Optional[str] = conflict.get("entity_id")

        # Newer data wins
        resolution: Dict[str, Any] = {
            "conflict": conflict,
            "resolution": "newer_wins",
            "winner": "new",
            "resolved_value": new_value,
            "wal_entry_id": wal_entry_id,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "Conflict resolved: field=%s  entity=%s  old=%s -> new=%s  "
            "strategy=newer_wins  wal=%s",
            field,
            entity_id,
            str(old_value)[:50],
            str(new_value)[:50],
            wal_entry_id,
        )

        results.append(resolution)

    return results
