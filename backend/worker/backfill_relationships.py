"""
Backfill Entity Relationships from Existing Memories
=====================================================

Batch job to extract entity relationships from memories that already
have ``entity_links`` populated.  For each memory with 2+ linked entities,
this job:

1. Looks up entity names from UUIDs in the ``entities`` table
2. Calls ``extract_relationships()`` (Haiku-based extraction) from slow_path
3. Builds a name-to-UUID mapping for the looked-up entities
4. Stores relationships via ``store_relationships()`` in the MAGMA layer
5. Checkpoints progress for crash recovery

The job is idempotent thanks to the UNIQUE constraint on
``entity_relationships(source_entity_id, target_entity_id, relationship_type)``.

ADR Reference: ADR-001 (entity_relationships schema)
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Cost estimate per Haiku call for tracking
_ESTIMATED_COST_PER_CALL: float = 0.00003


def backfill_entity_relationships(
    batch_size: int = 500,
    checkpoint_interval: int = 100,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Backfill entity_relationships from existing memories.

    Synchronous wrapper for rq worker execution.  Delegates to the
    async implementation via ``asyncio.run()``.

    Parameters
    ----------
    batch_size : int
        Maximum number of memories to process in this run.
    checkpoint_interval : int
        Save a checkpoint every N entries for crash recovery.
    dry_run : bool
        If True, log what would be done without storing relationships.

    Returns
    -------
    dict
        Summary with keys: total_memories, processed, relationships_stored,
        errors, estimated_cost, elapsed_ms.
    """
    return asyncio.run(
        _async_backfill(
            batch_size=batch_size,
            checkpoint_interval=checkpoint_interval,
            dry_run=dry_run,
        )
    )


async def _async_backfill(
    batch_size: int = 500,
    checkpoint_interval: int = 100,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Async implementation of entity relationship backfill.

    Process:
        1. Query memories that have entity_links (non-empty array)
        2. For each memory, get its linked entities
        3. If memory has 2+ entities, extract relationships via Haiku
        4. Resolve entity names to UUIDs
        5. Store relationships via store_relationships()
        6. Checkpoint every N entries for crash recovery

    Parameters
    ----------
    batch_size : int
        Maximum memories to process.
    checkpoint_interval : int
        Checkpoint frequency.
    dry_run : bool
        If True, skip actual storage.

    Returns
    -------
    dict
        ``{"total_memories": N, "processed": M, "relationships_stored": R,
          "errors": [...], "estimated_cost": float, "elapsed_ms": float}``
    """
    # Lazy imports to avoid circular dependencies
    from backend.worker.checkpoint import CheckpointManager
    from backend.worker.slow_path import extract_relationships
    from backend.magma.store import store_relationships
    from backend.services.wal import get_supabase_client

    start: float = time.monotonic()
    batch_id: str = f"backfill-rel-{int(time.time())}"
    checkpoint_mgr = CheckpointManager(batch_id=batch_id)

    # --- 1. Query memories with entity_links ---
    client = get_supabase_client()

    logger.info(
        "Backfill START  batch_size=%d  checkpoint_interval=%d  dry_run=%s",
        batch_size,
        checkpoint_interval,
        dry_run,
    )

    try:
        response = (
            client.table("memories")
            .select("id, content, entity_links, metadata")
            .neq("entity_links", "{}")
            .eq("is_archived", False)
            .order("created_at")
            .limit(batch_size)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to query memories for backfill: %s", exc, exc_info=True)
        return {
            "total_memories": 0,
            "processed": 0,
            "relationships_stored": 0,
            "errors": [str(exc)],
            "estimated_cost": 0.0,
            "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
        }

    memories: List[Dict[str, Any]] = response.data or []
    total: int = len(memories)

    logger.info("Found %d memories with entity_links", total)

    if total == 0:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "total_memories": 0,
            "processed": 0,
            "relationships_stored": 0,
            "errors": [],
            "estimated_cost": 0.0,
            "elapsed_ms": round(elapsed_ms, 1),
        }

    # --- 2. Resume from checkpoint if available ---
    resume_index: int = 0
    processed: int = 0
    relationships_stored: int = 0
    haiku_calls: int = 0
    errors: List[str] = []

    existing_checkpoint = checkpoint_mgr.load()
    if existing_checkpoint is not None:
        resume_index = existing_checkpoint.get("last_processed_index", -1) + 1
        processed = existing_checkpoint.get("processed", 0)
        relationships_stored = existing_checkpoint.get("relationships_stored", 0)
        haiku_calls = existing_checkpoint.get("haiku_calls", 0)
        logger.info(
            "Resuming backfill from index %d (processed=%d, stored=%d)",
            resume_index,
            processed,
            relationships_stored,
        )

    # --- 3. Process each memory ---
    for i in range(resume_index, total):
        memory = memories[i]
        memory_id: str = memory.get("id", "")
        content: str = memory.get("content", "")
        entity_link_ids: List[str] = memory.get("entity_links", [])

        if len(entity_link_ids) < 2:
            processed += 1
            continue

        # --- 3a. Look up entity details from UUIDs ---
        try:
            entity_details = await _lookup_entities(client, entity_link_ids)
        except Exception as exc:
            error_msg = f"Entity lookup failed for memory {memory_id}: {exc}"
            logger.warning(error_msg)
            errors.append(error_msg)
            processed += 1
            continue

        if len(entity_details) < 2:
            processed += 1
            continue

        # Build the entity list for extract_relationships
        entities_list: List[Dict[str, Any]] = [
            {"name": e["name"], "type": e.get("type", "unknown")}
            for e in entity_details
        ]

        # Build name -> UUID mapping
        name_to_id: Dict[str, UUID] = {}
        for e in entity_details:
            try:
                name_to_id[e["name"].strip()] = UUID(e["id"])
            except (ValueError, KeyError, TypeError):
                pass

        # --- 3b. Extract relationships via Haiku ---
        try:
            relationships = extract_relationships(
                message=content,
                entities=entities_list,
                source_wal_id=memory_id,
            )
            haiku_calls += 1
        except Exception as exc:
            error_msg = f"Relationship extraction failed for memory {memory_id}: {exc}"
            logger.warning(error_msg)
            errors.append(error_msg)
            processed += 1
            continue

        if not relationships:
            processed += 1
            continue

        # --- 3c. Store relationships ---
        if dry_run:
            logger.info(
                "DRY RUN: would store %d relationships for memory %s",
                len(relationships),
                memory_id,
            )
            relationships_stored += len(relationships)
        else:
            try:
                stored = await store_relationships(
                    relationships=relationships,
                    entity_name_to_id=name_to_id,
                    source_wal_id=memory_id,
                )
                relationships_stored += stored.get("stored", 0)
            except Exception as exc:
                error_msg = f"store_relationships failed for memory {memory_id}: {exc}"
                logger.warning(error_msg)
                errors.append(error_msg)

        processed += 1

        # --- 3d. Log progress ---
        if (i + 1) % 100 == 0 or i == total - 1:
            logger.info(
                "Backfill progress: %d/%d memories  relationships=%d  "
                "haiku_calls=%d  errors=%d",
                i + 1,
                total,
                relationships_stored,
                haiku_calls,
                len(errors),
            )

        # --- 3e. Checkpoint periodically ---
        if (i + 1) % checkpoint_interval == 0 or i == total - 1:
            checkpoint_mgr.save(
                last_processed_index=i,
                metadata={
                    "processed": processed,
                    "relationships_stored": relationships_stored,
                    "haiku_calls": haiku_calls,
                    "errors_count": len(errors),
                    "remaining": total - (i + 1),
                },
            )

    # --- 4. Cleanup ---
    checkpoint_mgr.clear()

    elapsed_ms = (time.monotonic() - start) * 1000
    estimated_cost = haiku_calls * _ESTIMATED_COST_PER_CALL

    result: Dict[str, Any] = {
        "total_memories": total,
        "processed": processed,
        "relationships_stored": relationships_stored,
        "haiku_calls": haiku_calls,
        "errors": errors[:50],  # Cap error list to avoid oversized responses
        "error_count": len(errors),
        "estimated_cost": round(estimated_cost, 5),
        "dry_run": dry_run,
        "elapsed_ms": round(elapsed_ms, 1),
    }

    logger.info(
        "Backfill DONE: total=%d  processed=%d  relationships=%d  "
        "haiku_calls=%d  errors=%d  cost=$%.5f  elapsed=%.0fms",
        total,
        processed,
        relationships_stored,
        haiku_calls,
        len(errors),
        estimated_cost,
        elapsed_ms,
    )

    return result


async def _lookup_entities(
    client: Any,
    entity_ids: List[str],
) -> List[Dict[str, Any]]:
    """
    Look up entity details (name, type, id) from a list of entity UUIDs.

    Parameters
    ----------
    client : supabase.Client
        Supabase client instance.
    entity_ids : list[str]
        List of entity UUID strings.

    Returns
    -------
    list[dict]
        Entity detail dicts with keys: id, name, type, domain.
    """
    if not entity_ids:
        return []

    # Filter out any empty or invalid UUIDs
    valid_ids: List[str] = [
        eid for eid in entity_ids
        if eid and isinstance(eid, str) and len(eid) > 0
    ]

    if not valid_ids:
        return []

    try:
        response = (
            client.table("entities")
            .select("id, name, type, domain")
            .in_("id", valid_ids)
            .execute()
        )
        return response.data or []
    except Exception as exc:
        logger.error(
            "Entity lookup failed for %d IDs: %s",
            len(valid_ids),
            exc,
            exc_info=True,
        )
        raise
