"""
Belief Conflict Detector (Phase 2C / MEM-005)
===============================================

Classifies conflicts between new information and existing memories
using the PRD 4.1.2 Decision Matrix:

  - HIGH_CONFIDENCE_OVERRIDE: new confidence > existing + 0.2
  - MARGINAL_UPDATE: confidence difference < 0.2
  - OUTLIER_DETECTION: contradicts >3 related memories
  - PATTERN_VIOLATION: contradicts an established rule

Called from the Fast Path (read-only, <500ms) and from the Slow Path
for deeper reconciliation.
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Enums & Models
# =============================================================================

class ConflictClassification(str, Enum):
    """Conflict classification per PRD 4.1.2 Decision Matrix."""
    HIGH_CONFIDENCE_OVERRIDE = "high_confidence_override"
    MARGINAL_UPDATE = "marginal_update"
    OUTLIER_DETECTION = "outlier_detection"
    PATTERN_VIOLATION = "pattern_violation"


class BeliefConflict(BaseModel):
    """A detected belief-level conflict between new and existing information."""
    classification: ConflictClassification
    entity_name: str = Field(..., description="Name of the entity involved")
    new_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence of new information")
    existing_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence of existing memory")
    confidence_delta: float = Field(..., description="new_confidence - existing_confidence")
    contradicted_memory_ids: List[str] = Field(default_factory=list, description="UUIDs of contradicted memories")
    contradicted_count: int = Field(default=0, description="Number of memories contradicted")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Supporting evidence for the conflict")
    recommended_action: str = Field(..., description="Human-readable recommended action")


# =============================================================================
# Classification Logic
# =============================================================================

# Threshold for high-confidence override (PRD 4.1.2)
CONFIDENCE_OVERRIDE_THRESHOLD: float = 0.2
# Threshold for outlier detection (PRD 4.1.2)
OUTLIER_CONTRADICTION_THRESHOLD: int = 3


def classify_conflict(
    new_confidence: float,
    existing_confidence: float,
    contradicted_memories_count: int = 0,
    violates_rule: bool = False,
) -> ConflictClassification:
    """
    Classify a belief conflict using the PRD 4.1.2 Decision Matrix.

    Priority order (highest to lowest):
      1. PATTERN_VIOLATION -- contradicts an established rule
      2. OUTLIER_DETECTION -- contradicts >3 related memories
      3. HIGH_CONFIDENCE_OVERRIDE -- confidence delta > 0.2
      4. MARGINAL_UPDATE -- all other cases

    Parameters
    ----------
    new_confidence : float
        Confidence score of the new information (0.0-1.0).
    existing_confidence : float
        Confidence score of the existing memory (0.0-1.0).
    contradicted_memories_count : int
        Number of existing memories that the new info contradicts.
    violates_rule : bool
        True if the new info contradicts an established rule.

    Returns
    -------
    ConflictClassification
    """
    if violates_rule:
        return ConflictClassification.PATTERN_VIOLATION

    if contradicted_memories_count > OUTLIER_CONTRADICTION_THRESHOLD:
        return ConflictClassification.OUTLIER_DETECTION

    delta = new_confidence - existing_confidence
    if delta > CONFIDENCE_OVERRIDE_THRESHOLD:
        return ConflictClassification.HIGH_CONFIDENCE_OVERRIDE

    return ConflictClassification.MARGINAL_UPDATE


# =============================================================================
# High-Level Detection
# =============================================================================

async def detect_belief_conflicts(
    entity_name: str,
    entity_id: str,
    new_confidence: float,
    user_id: str,
    existing_memories: Optional[List[Dict[str, Any]]] = None,
) -> List[BeliefConflict]:
    """
    Detect belief-level conflicts for an entity.

    This function is called from the Fast Path (must complete <500ms)
    and performs read-only queries against the MAGMA contradiction graph
    and existing memory confidences.

    Parameters
    ----------
    entity_name : str
        The display name of the entity (used in conflict reports).
    entity_id : str
        UUID string of the entity to check contradiction edges for.
        Passed to ``get_entity_relationships(entity_id=...)``.
    new_confidence : float
        Confidence of the incoming information (0.0-1.0).
    user_id : str
        UUID string of the user (for logging / future scoping).
    existing_memories : list[dict], optional
        Pre-fetched memories to check against.  Each dict should have
        a ``confidence`` key (float).  If *None*, only the contradiction
        graph is consulted.

    Returns
    -------
    list[BeliefConflict]
    """
    conflicts: List[BeliefConflict] = []

    try:
        # ------------------------------------------------------------------
        # 1. Query contradiction edges from the MAGMA graph
        # ------------------------------------------------------------------
        contradiction_count = 0
        contradicted_ids: List[str] = []

        try:
            # Lazy import to avoid circular dependencies at module load
            from backend.magma.query import get_entity_relationships

            rels = await get_entity_relationships(
                entity_id=entity_id,
                relationship_type="contradicts",
                limit=10,
            )
            contradiction_count = len(rels)
            contradicted_ids = [
                r.get("target_entity_id", "") or r.get("source_entity_id", "")
                for r in rels
                if r.get("target_entity_id") or r.get("source_entity_id")
            ]
        except Exception as exc:
            logger.debug(
                "Could not query contradiction graph for entity=%s (id=%s): %s",
                entity_name, entity_id, exc,
            )

        # ------------------------------------------------------------------
        # 2. Compute average existing confidence
        # ------------------------------------------------------------------
        avg_existing_confidence = 0.5  # sensible default
        if existing_memories:
            confidences = [
                m.get("confidence", 1.0)
                for m in existing_memories
                if m.get("confidence") is not None
            ]
            if confidences:
                avg_existing_confidence = sum(confidences) / len(confidences)

        # ------------------------------------------------------------------
        # 3. Check for rule / pattern violations
        # ------------------------------------------------------------------
        # TODO: Query rules table for pattern violations (PUSH-001)
        violates_rule = False

        # ------------------------------------------------------------------
        # 4. Classify
        # ------------------------------------------------------------------
        classification = classify_conflict(
            new_confidence=new_confidence,
            existing_confidence=avg_existing_confidence,
            contradicted_memories_count=contradiction_count,
            violates_rule=violates_rule,
        )

        # ------------------------------------------------------------------
        # 5. Build recommended action (PRD 4.1.2 action column)
        # ------------------------------------------------------------------
        action_map: Dict[ConflictClassification, str] = {
            ConflictClassification.HIGH_CONFIDENCE_OVERRIDE: (
                "Append with version tag; prompt user for confirmation"
            ),
            ConflictClassification.MARGINAL_UPDATE: (
                "Flag for Slow Path reconciliation"
            ),
            ConflictClassification.OUTLIER_DETECTION: (
                f"Flag as Temporary Deviation (contradicts {contradiction_count} memories); "
                "set 7-day expiry"
            ),
            ConflictClassification.PATTERN_VIOLATION: (
                "Trigger push-back protocol with evidence"
            ),
        }

        delta = new_confidence - avg_existing_confidence

        conflict = BeliefConflict(
            classification=classification,
            entity_name=entity_name,
            new_confidence=new_confidence,
            existing_confidence=avg_existing_confidence,
            confidence_delta=delta,
            contradicted_memory_ids=contradicted_ids,
            contradicted_count=contradiction_count,
            evidence={
                "avg_existing_confidence": avg_existing_confidence,
                "contradiction_graph_edges": contradiction_count,
            },
            recommended_action=action_map[classification],
        )

        # Only surface as a conflict if non-trivial
        if classification != ConflictClassification.MARGINAL_UPDATE or abs(delta) > 0.05:
            conflicts.append(conflict)
            logger.info(
                "Belief conflict detected: entity=%s classification=%s delta=%.2f",
                entity_name, classification.value, delta,
            )

    except Exception as exc:
        logger.warning(
            "Belief conflict detection failed for entity=%s user=%s: %s",
            entity_name, user_id, exc,
        )

    return conflicts
