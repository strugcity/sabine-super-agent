"""
MAGMA Query - Relationship Graph Traversal and Queries
========================================================

Query functions for traversing the entity relationship graph.

Functions:
  - causal_trace():             Trace causal chains via traverse_graph RPC
  - entity_network():           Load connected entity graph for visualization
  - get_entity_relationships(): Simple 1-hop direct relationship lookup

All functions use the Supabase client.  For multi-hop traversals the
``traverse_graph()`` Postgres RPC is called via ``supabase.rpc()``.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# =============================================================================
# Helper: get Supabase client (lazy to avoid circular imports)
# =============================================================================

def _get_client() -> Any:
    """Return the singleton Supabase client."""
    from backend.services.wal import get_supabase_client
    return get_supabase_client()


# =============================================================================
# causal_trace
# =============================================================================

async def causal_trace(
    entity_id: str,
    max_depth: int = 3,
    min_confidence: float = 0.3,
) -> Dict[str, Any]:
    """
    Trace causal chains from an entity.

    Follows cause-effect relationships using the ``traverse_graph()``
    Postgres RPC with ``layer_filter='causal'``.

    Parameters
    ----------
    entity_id : str
        UUID string of the starting entity.
    max_depth : int
        Maximum hops to follow (default: 3).
    min_confidence : float
        Minimum confidence threshold (default: 0.3).

    Returns
    -------
    dict
        ``{"root_entity": {...}, "chain": [...], "total_hops": int,
          "max_confidence": float, "min_confidence": float}``
    """
    try:
        client = _get_client()

        # Fetch root entity name
        root_resp = await asyncio.to_thread(
            lambda: client.table("entities")
            .select("id, name, type, domain")
            .eq("id", entity_id)
            .limit(1)
            .execute()
        )
        root_data = (root_resp.data or [{}])[0] if root_resp.data else {}
        root_entity: Dict[str, Any] = {
            "id": entity_id,
            "name": root_data.get("name", "unknown"),
        }

        # Call traverse_graph RPC with causal layer filter
        rpc_resp = await asyncio.to_thread(
            lambda: client.rpc(
                "traverse_graph",
                {
                    "start_entity_id": entity_id,
                    "max_depth": max_depth,
                    "relationship_type_filter": None,
                    "layer_filter": "causal",
                    "min_confidence": min_confidence,
                },
            ).execute()
        )

        rows: List[Dict[str, Any]] = rpc_resp.data or []

        # Build causal chain
        chain: List[Dict[str, Any]] = []
        confidences: List[float] = []

        for row in rows:
            conf = float(row.get("confidence", 0.0))
            chain.append({
                "from": row.get("source_name", "unknown"),
                "from_id": row.get("source_id", ""),
                "to": row.get("target_name", "unknown"),
                "to_id": row.get("target_id", ""),
                "type": row.get("relationship_type", ""),
                "confidence": conf,
                "hop": row.get("hop", 0),
            })
            confidences.append(conf)

        total_hops = max((r.get("hop", 0) for r in rows), default=0)

        return {
            "root_entity": root_entity,
            "chain": chain,
            "total_hops": total_hops,
            "max_confidence": max(confidences) if confidences else 0.0,
            "min_confidence": min(confidences) if confidences else 0.0,
        }

    except Exception as exc:
        logger.error(
            "causal_trace failed for entity %s: %s",
            entity_id,
            exc,
            exc_info=True,
        )
        raise


# =============================================================================
# entity_network
# =============================================================================

async def entity_network(
    entity_id: str,
    layers: Optional[List[str]] = None,
    max_depth: int = 2,
    min_confidence: float = 0.3,
) -> Dict[str, Any]:
    """
    Load all connected entities across specified relationship layers.

    If *layers* is ``None``, returns all layers.  Returns a graph structure
    suitable for visualization with ``nodes`` and ``edges``.

    Parameters
    ----------
    entity_id : str
        UUID string of the starting entity.
    layers : list[str] or None
        Graph layers to include (e.g. ``["entity", "causal"]``).
        ``None`` means all layers.
    max_depth : int
        Maximum hops (default: 2).
    min_confidence : float
        Minimum confidence threshold (default: 0.3).

    Returns
    -------
    dict
        ``{"root_entity": {...}, "nodes": [...], "edges": [...],
          "statistics": {...}}``
    """
    try:
        client = _get_client()

        # Fetch root entity details
        root_resp = await asyncio.to_thread(
            lambda: client.table("entities")
            .select("id, name, type, domain")
            .eq("id", entity_id)
            .limit(1)
            .execute()
        )
        root_data = (root_resp.data or [{}])[0] if root_resp.data else {}
        root_entity: Dict[str, Any] = {
            "id": entity_id,
            "name": root_data.get("name", "unknown"),
            "type": root_data.get("type", "unknown"),
            "domain": root_data.get("domain", ""),
        }

        # If multiple layers requested, query each via RPC and merge.
        # If a single layer or None, one RPC call suffices.
        all_rows: List[Dict[str, Any]] = []

        if layers:
            for layer in layers:
                rpc_resp = await asyncio.to_thread(
                    lambda _layer=layer: client.rpc(
                        "traverse_graph",
                        {
                            "start_entity_id": entity_id,
                            "max_depth": max_depth,
                            "relationship_type_filter": None,
                            "layer_filter": _layer,
                            "min_confidence": min_confidence,
                        },
                    ).execute()
                )
                all_rows.extend(rpc_resp.data or [])
        else:
            rpc_resp = await asyncio.to_thread(
                lambda: client.rpc(
                    "traverse_graph",
                    {
                        "start_entity_id": entity_id,
                        "max_depth": max_depth,
                        "relationship_type_filter": None,
                        "layer_filter": None,
                        "min_confidence": min_confidence,
                    },
                ).execute()
            )
            all_rows = rpc_resp.data or []

        # Deduplicate edges (same source+target+type can appear from
        # multiple layer queries)
        seen_edges: set[tuple[str, str, str]] = set()
        edges: List[Dict[str, Any]] = []
        node_ids: set[str] = {entity_id}
        node_details: Dict[str, Dict[str, str]] = {
            entity_id: {
                "name": root_entity["name"],
                "type": root_entity["type"],
                "domain": root_entity["domain"],
            }
        }
        layers_found: set[str] = set()
        max_hop: int = 0

        for row in all_rows:
            src_id = str(row.get("source_id", ""))
            tgt_id = str(row.get("target_id", ""))
            rel_type = str(row.get("relationship_type", ""))
            edge_key = (src_id, tgt_id, rel_type)

            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            hop = int(row.get("hop", 0))
            layer = str(row.get("graph_layer", "entity"))
            layers_found.add(layer)
            max_hop = max(max_hop, hop)

            edges.append({
                "source": src_id,
                "target": tgt_id,
                "type": rel_type,
                "layer": layer,
                "confidence": float(row.get("confidence", 0.0)),
                "hop": hop,
            })

            # Collect node info
            if src_id not in node_ids:
                node_ids.add(src_id)
                node_details[src_id] = {
                    "name": row.get("source_name", "unknown"),
                    "type": "",
                    "domain": "",
                }
            if tgt_id not in node_ids:
                node_ids.add(tgt_id)
                node_details[tgt_id] = {
                    "name": row.get("target_name", "unknown"),
                    "type": "",
                    "domain": "",
                }

        # Build nodes list
        nodes: List[Dict[str, Any]] = []
        for nid in node_ids:
            detail = node_details.get(nid, {})
            nodes.append({
                "id": nid,
                "name": detail.get("name", "unknown"),
                "type": detail.get("type", ""),
                "domain": detail.get("domain", ""),
            })

        return {
            "root_entity": root_entity,
            "nodes": nodes,
            "edges": edges,
            "statistics": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "max_hop": max_hop,
                "layers_found": sorted(layers_found),
            },
        }

    except Exception as exc:
        logger.error(
            "entity_network failed for entity %s: %s",
            entity_id,
            exc,
            exc_info=True,
        )
        raise


# =============================================================================
# get_entity_relationships
# =============================================================================

async def get_entity_relationships(
    entity_id: "str | UUID",
    direction: str = "both",
    relationship_type: Optional[str] = None,
    limit: int = 50,
    min_confidence: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Get direct relationships for an entity (1-hop only).

    Queries the ``entity_relationships`` table directly (no RPC needed).
    Simpler than full traversal -- useful for UI display.

    Parameters
    ----------
    entity_id : str or UUID
        The entity to query relationships for.
    direction : str
        ``"outgoing"`` (entity is source), ``"incoming"`` (entity is target),
        or ``"both"`` (default).
    relationship_type : str or None
        Optional filter by relationship type.
    limit : int
        Maximum relationships to return per direction (default: 50).
    min_confidence : float
        Minimum confidence threshold for filtering (default: 0.0).

    Returns
    -------
    list[dict]
        Relationship dicts with keys: source_entity_id, target_entity_id,
        relationship_type, confidence, graph_layer, source_name, target_name,
        direction.
    """
    try:
        client = _get_client()
        entity_id_str = str(entity_id)
        relationships: List[Dict[str, Any]] = []

        if direction in ("outgoing", "both"):
            query = (
                client.table("entity_relationships")
                .select(
                    "*, source_entity:entities!source_entity_id(name, type), "
                    "target_entity:entities!target_entity_id(name, type)"
                )
                .eq("source_entity_id", entity_id_str)
                .gte("confidence", min_confidence)
                .order("confidence", desc=True)
                .limit(limit)
            )
            if relationship_type:
                query = query.eq("relationship_type", relationship_type)
            response = await asyncio.to_thread(query.execute)

            for row in response.data or []:
                row["direction"] = "outgoing"
                source_entity = row.pop("source_entity", {}) or {}
                target_entity = row.pop("target_entity", {}) or {}
                row["source_name"] = source_entity.get("name", "unknown")
                row["target_name"] = target_entity.get("name", "unknown")
                row["source_type"] = source_entity.get("type", "unknown")
                row["target_type"] = target_entity.get("type", "unknown")
                relationships.append(row)

        if direction in ("incoming", "both"):
            query = (
                client.table("entity_relationships")
                .select(
                    "*, source_entity:entities!source_entity_id(name, type), "
                    "target_entity:entities!target_entity_id(name, type)"
                )
                .eq("target_entity_id", entity_id_str)
                .gte("confidence", min_confidence)
                .order("confidence", desc=True)
                .limit(limit)
            )
            if relationship_type:
                query = query.eq("relationship_type", relationship_type)
            response = await asyncio.to_thread(query.execute)

            for row in response.data or []:
                row["direction"] = "incoming"
                source_entity = row.pop("source_entity", {}) or {}
                target_entity = row.pop("target_entity", {}) or {}
                row["source_name"] = source_entity.get("name", "unknown")
                row["target_name"] = target_entity.get("name", "unknown")
                row["source_type"] = source_entity.get("type", "unknown")
                row["target_type"] = target_entity.get("type", "unknown")
                relationships.append(row)

        logger.debug(
            "Found %d relationships for entity %s (direction=%s, type=%s)",
            len(relationships),
            entity_id_str,
            direction,
            relationship_type,
        )
        return relationships

    except Exception as exc:
        logger.error(
            "get_entity_relationships failed for entity %s: %s",
            entity_id,
            exc,
            exc_info=True,
        )
        raise
