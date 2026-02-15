"""
MAGMA Store - Persist Extracted Relationships
==============================================

Resolves entity names to UUIDs and inserts relationship triples
into the ``entity_relationships`` table in Supabase.

The main entry point is :func:`store_relationships`, called from
``backend/worker/slow_path.py`` after ``extract_relationships()``.

Key behaviours:
  - Resolves subject/object names to entity UUIDs via a name-to-id mapping
  - Skips relationships where either entity cannot be resolved
  - Checks existing confidence before upsert; skips if new confidence is not higher
  - Validates predicates against the MAGMA taxonomy
  - Corrects ``graph_layer`` via :func:`infer_layer` if mismatched
  - Logs all skips and errors (never swallows silently)
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def store_relationships(
    relationships: List[Dict[str, Any]],
    entity_name_to_id: Dict[str, str],
    source_wal_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve entity names to UUIDs and insert relationships.

    Parameters
    ----------
    relationships : list[dict]
        List of relationship dicts from ``extract_relationships()``.
        Each dict has keys: ``subject``, ``predicate``, ``object``,
        ``confidence``, ``source_wal_id``, ``graph_layer``,
        ``relationship_type``.
    entity_name_to_id : dict[str, str]
        Mapping of entity names to UUID strings (from entity resolution).
    source_wal_id : str, optional
        WAL entry UUID string for provenance tracking.

    Returns
    -------
    dict
        ``{"stored": N, "skipped": M, "errors": [...]}``
    """
    # Lazy imports to avoid circular deps and module-load overhead
    from backend.magma.taxonomy import infer_layer, is_valid_predicate

    result: Dict[str, Any] = {
        "stored": 0,
        "skipped": 0,
        "errors": [],
    }

    if not relationships:
        logger.debug("store_relationships called with empty list; nothing to do")
        return result

    if not entity_name_to_id:
        logger.warning(
            "store_relationships called with empty entity_name_to_id mapping; "
            "all %d relationships will be skipped",
            len(relationships),
        )
        result["skipped"] = len(relationships)
        return result

    try:
        # Lazy import for Supabase client
        from backend.services.wal import get_supabase_client

        client = get_supabase_client()
    except Exception as exc:
        error_msg = f"Failed to get Supabase client: {exc}"
        logger.error(error_msg, exc_info=True)
        result["errors"].append(error_msg)
        result["skipped"] = len(relationships)
        return result

    # Build case-insensitive lookup for entity names
    name_lookup: Dict[str, str] = {
        k.lower().strip(): v for k, v in entity_name_to_id.items()
    }

    for rel in relationships:
        subject_name: str = rel.get("subject", "")
        object_name: str = rel.get("object", "")
        predicate: str = rel.get("predicate", rel.get("relationship_type", ""))
        confidence: float = float(rel.get("confidence", 0.5))
        graph_layer: str = rel.get("graph_layer", "entity")

        # --- Resolve entity names to UUIDs (case-insensitive) ---
        source_entity_id: Optional[str] = name_lookup.get(subject_name.lower().strip())
        target_entity_id: Optional[str] = name_lookup.get(object_name.lower().strip())

        if not source_entity_id or not target_entity_id:
            skip_reason = (
                f"Cannot resolve entities: "
                f"subject='{subject_name}' -> {source_entity_id}, "
                f"object='{object_name}' -> {target_entity_id}"
            )
            logger.debug(
                "Skipping relationship: %s (WAL %s)",
                skip_reason,
                source_wal_id,
            )
            result["skipped"] += 1
            continue

        if not predicate:
            logger.debug(
                "Skipping relationship with empty predicate: "
                "%s -> ? -> %s (WAL %s)",
                subject_name,
                object_name,
                source_wal_id,
            )
            result["skipped"] += 1
            continue

        # --- Validate and correct predicate / graph_layer ---
        if not is_valid_predicate(predicate):
            logger.debug(
                "Predicate '%s' not in canonical taxonomy; "
                "keeping as-is with inferred layer (WAL %s)",
                predicate,
                source_wal_id,
            )

        # Always use infer_layer to ensure graph_layer matches predicate
        inferred_layer = infer_layer(predicate)
        if graph_layer != inferred_layer.value:
            logger.debug(
                "Correcting graph_layer for '%s': %s -> %s (WAL %s)",
                predicate,
                graph_layer,
                inferred_layer.value,
                source_wal_id,
            )
            graph_layer = inferred_layer.value

        # Clamp confidence to [0.0, 1.0]
        confidence = max(0.0, min(1.0, confidence))

        # --- Build the row for upsert ---
        row: Dict[str, Any] = {
            "source_entity_id": str(source_entity_id),
            "target_entity_id": str(target_entity_id),
            "relationship_type": predicate,
            "graph_layer": graph_layer,
            "confidence": confidence,
            "metadata": {},
        }

        if source_wal_id:
            row["source_wal_id"] = source_wal_id

        # --- Upsert: only if new confidence is higher than existing ---
        try:
            existing = (
                client.table("entity_relationships")
                .select("confidence")
                .eq("source_entity_id", str(source_entity_id))
                .eq("target_entity_id", str(target_entity_id))
                .eq("relationship_type", predicate)
                .limit(1)
                .execute()
            )
            existing_conf: float = (
                float(existing.data[0]["confidence"]) if existing.data else 0.0
            )

            if confidence <= existing_conf:
                logger.debug(
                    "Skipping upsert: existing confidence %.2f >= new %.2f "
                    "for %s -[%s]-> %s",
                    existing_conf,
                    confidence,
                    subject_name,
                    predicate,
                    object_name,
                )
                result["skipped"] += 1
                continue

            # New confidence is strictly higher or row does not exist yet
            client.table("entity_relationships").upsert(
                row,
                on_conflict="source_entity_id,target_entity_id,relationship_type",
            ).execute()
            result["stored"] += 1
        except Exception as insert_exc:
            error_msg = (
                f"Failed to upsert relationship "
                f"{subject_name} -[{predicate}]-> {object_name}: {insert_exc}"
            )
            logger.warning(error_msg)
            result["errors"].append(error_msg)

    logger.info(
        "store_relationships complete: stored=%d  skipped=%d  errors=%d  "
        "total=%d  wal=%s",
        result["stored"],
        result["skipped"],
        len(result["errors"]),
        len(relationships),
        source_wal_id,
    )

    return result


def build_entity_name_to_id(
    entities: List[Dict[str, Any]],
    resolve_results: List[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Build a mapping of entity names to their resolved UUIDs.

    Pairs each entity from the input list with the resolution result
    from ``_async_resolve_entity()`` to create the lookup table
    needed by :func:`store_relationships`.

    Parameters
    ----------
    entities : list[dict]
        Entity dicts from ``raw_payload["entities"]``.
        Each must have a ``"name"`` key.
    resolve_results : list[dict]
        Results from entity resolution, each with ``"entity_id"``
        and ``"action"`` keys.  Must be in the same order as
        ``entities``.

    Returns
    -------
    dict[str, str]
        Mapping of entity name -> entity UUID string.
        Only includes entities that were successfully resolved
        (action is ``"created"`` or ``"updated"``).
    """
    name_to_id: Dict[str, str] = {}

    for entity_data, resolve_result in zip(entities, resolve_results):
        name: str = entity_data.get("name", "").strip()
        entity_id: Optional[str] = resolve_result.get("entity_id")
        action: str = resolve_result.get("action", "")

        if name and entity_id and action in ("created", "updated"):
            name_to_id[name] = str(entity_id)

    return name_to_id
