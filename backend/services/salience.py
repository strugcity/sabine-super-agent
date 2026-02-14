"""
Salience Scoring Service for Sabine 2.0
========================================

Implements the composite salience formula for ranking memory importance:

    S = w_r * recency + w_f * frequency + w_e * emotional_weight + w_c * causal_centrality

Components:
    - **Recency**: Exponential decay based on ``last_accessed_at``
      ``exp(-lambda * days_since_access)`` with lambda=0.1 (half-life ~7 days)
    - **Frequency**: Normalised ``access_count`` using log-scale
      ``log(1 + access_count) / log(1 + max_count)``
    - **Emotional weight**: Stub returning 0.5 (Phase 2: sentiment analysis)
    - **Causal centrality**: Stub returning 0.3 (Phase 2: graph degree count)

Default weights: w_r=0.4, w_f=0.2, w_e=0.2, w_c=0.2

PRD Reference: MEM-001 (Salience Scoring Formula)
ADR Reference: ADR-004 (Cold Storage Archival Trigger Criteria)
"""

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Exponential decay parameter: lambda = 0.1 gives a half-life of ~6.93 days
DECAY_LAMBDA: float = 0.1

# Default max access count when no global max is available
DEFAULT_MAX_ACCESS_COUNT: int = 10


# =============================================================================
# Pydantic Models
# =============================================================================

class SalienceWeights(BaseModel):
    """
    Configurable weights for the salience scoring formula.

    All weights must be non-negative and sum to 1.0.
    Default values: w_r=0.4, w_f=0.2, w_e=0.2, w_c=0.2
    """
    w_recency: float = Field(
        default=0.4, ge=0.0, le=1.0,
        description="Weight for recency component (exponential decay)",
    )
    w_frequency: float = Field(
        default=0.2, ge=0.0, le=1.0,
        description="Weight for frequency component (normalised access count)",
    )
    w_emotional: float = Field(
        default=0.2, ge=0.0, le=1.0,
        description="Weight for emotional weight component (sentiment analysis stub)",
    )
    w_causal: float = Field(
        default=0.2, ge=0.0, le=1.0,
        description="Weight for causal centrality component (graph degree stub)",
    )

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "SalienceWeights":
        """Ensure weights sum to 1.0 (within floating-point tolerance)."""
        total = self.w_recency + self.w_frequency + self.w_emotional + self.w_causal
        if not math.isclose(total, 1.0, rel_tol=1e-6):
            raise ValueError(
                f"Salience weights must sum to 1.0, got {total:.6f} "
                f"(w_r={self.w_recency}, w_f={self.w_frequency}, "
                f"w_e={self.w_emotional}, w_c={self.w_causal})"
            )
        return self


class SalienceComponents(BaseModel):
    """
    Breakdown of individual salience sub-scores before weighting.

    Each component is in the range [0.0, 1.0].
    """
    recency: float = Field(
        ..., ge=0.0, le=1.0,
        description="Recency score: exp(-lambda * days_since_access)",
    )
    frequency: float = Field(
        ..., ge=0.0, le=1.0,
        description="Frequency score: log(1 + count) / log(1 + max_count)",
    )
    emotional_weight: float = Field(
        ..., ge=0.0, le=1.0,
        description="Emotional weight (stub: 0.5)",
    )
    causal_centrality: float = Field(
        ..., ge=0.0, le=1.0,
        description="Causal centrality (stub: 0.3)",
    )


class SalienceResult(BaseModel):
    """
    Complete result of a salience calculation for a single memory.
    """
    memory_id: Optional[str] = Field(
        default=None,
        description="UUID of the memory (as string), if available",
    )
    score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Final composite salience score",
    )
    components: SalienceComponents = Field(
        ...,
        description="Individual component scores before weighting",
    )
    weights: SalienceWeights = Field(
        ...,
        description="Weights used for this calculation",
    )


# =============================================================================
# Component Calculators
# =============================================================================

def compute_recency(
    last_accessed_at: Optional[datetime],
    now: Optional[datetime] = None,
    decay_lambda: float = DECAY_LAMBDA,
) -> float:
    """
    Compute recency score using exponential decay.

    Formula: exp(-lambda * days_since_access)

    Parameters
    ----------
    last_accessed_at : datetime or None
        When the memory was last accessed.  If ``None``, returns 0.0
        (never accessed = lowest recency).
    now : datetime or None
        Reference time.  Defaults to ``datetime.now(timezone.utc)``.
    decay_lambda : float
        Decay rate.  Default 0.1 gives half-life ~6.93 days.

    Returns
    -------
    float
        Recency score in [0.0, 1.0].
    """
    if last_accessed_at is None:
        return 0.0

    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure both are timezone-aware for comparison
    if last_accessed_at.tzinfo is None:
        last_accessed_at = last_accessed_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta = now - last_accessed_at
    days_since_access = max(delta.total_seconds() / 86400.0, 0.0)

    score = math.exp(-decay_lambda * days_since_access)
    return round(min(max(score, 0.0), 1.0), 6)


def compute_frequency(
    access_count: int,
    max_access_count: int = DEFAULT_MAX_ACCESS_COUNT,
) -> float:
    """
    Compute frequency score using log-normalised access count.

    Formula: log(1 + access_count) / log(1 + max_access_count)

    Parameters
    ----------
    access_count : int
        Number of times this memory has been retrieved.
    max_access_count : int
        Maximum access count across all memories (for normalisation).
        Must be >= 1 to avoid division by zero.

    Returns
    -------
    float
        Frequency score in [0.0, 1.0].
    """
    if access_count <= 0:
        return 0.0

    # Ensure max_access_count is at least 1 to avoid log(1)/log(1) = NaN
    effective_max = max(max_access_count, 1)

    numerator = math.log(1 + access_count)
    denominator = math.log(1 + effective_max)

    if denominator == 0.0:
        return 0.0

    score = numerator / denominator
    return round(min(max(score, 0.0), 1.0), 6)


def compute_emotional_weight(
    memory_metadata: Optional[dict] = None,
) -> float:
    """
    Compute emotional weight for a memory.

    Currently a stub returning 0.5.

    .. todo::
        Phase 2: Integrate sentiment analysis (e.g., Claude Haiku) to
        extract emotional valence from memory content.  High-emotion
        memories (grief, joy, anger) should score higher.  Consider
        using a separate ``emotional_valence`` column on the memories
        table once the sentiment model is wired.

    Parameters
    ----------
    memory_metadata : dict or None
        Memory metadata dict (unused in stub).

    Returns
    -------
    float
        Emotional weight in [0.0, 1.0].  Stub returns 0.5.
    """
    # TODO(phase2): Replace stub with real sentiment analysis integration.
    # Expected flow:
    #   1. Extract emotion from memory.content via Claude Haiku
    #   2. Map sentiment polarity + intensity to [0.0, 1.0]
    #   3. Cache result in memory.metadata["emotional_valence"]
    return 0.5


def compute_causal_centrality(
    memory_metadata: Optional[dict] = None,
    entity_links: Optional[list] = None,
) -> float:
    """
    Compute causal centrality for a memory.

    Currently a stub returning 0.3.

    .. todo::
        Phase 2: Compute actual graph degree centrality from
        ``entity_relationships`` table.  Count the number of
        relationships (edges) connected to entities linked by this
        memory, then normalise by the max degree in the graph.

    Parameters
    ----------
    memory_metadata : dict or None
        Memory metadata dict (unused in stub).
    entity_links : list or None
        List of entity UUIDs linked to this memory (unused in stub).

    Returns
    -------
    float
        Causal centrality in [0.0, 1.0].  Stub returns 0.3.
    """
    # TODO(phase2): Replace stub with real graph centrality calculation.
    # Expected flow:
    #   1. Query entity_relationships for all edges touching memory.entity_links
    #   2. Count degree (number of distinct relationships) for each entity
    #   3. Normalise by max_degree across all entities
    #   4. Return average normalised degree for the memory's linked entities
    return 0.3


# =============================================================================
# Main Salience Calculator
# =============================================================================

def calculate_salience(
    memory: "Memory",
    weights: Optional[SalienceWeights] = None,
    max_access_count: int = DEFAULT_MAX_ACCESS_COUNT,
    now: Optional[datetime] = None,
) -> SalienceResult:
    """
    Calculate the composite salience score for a single memory.

    Formula:
        S = w_r * recency + w_f * frequency + w_e * emotional + w_c * causal

    Parameters
    ----------
    memory : Memory
        The memory model instance (from ``lib.db.models``).
    weights : SalienceWeights or None
        Custom weights.  Defaults to ``SalienceWeights()`` (0.4/0.2/0.2/0.2).
    max_access_count : int
        Maximum access count across all memories for frequency normalisation.
    now : datetime or None
        Reference time for recency calculation.

    Returns
    -------
    SalienceResult
        Full result including composite score, component breakdown, and weights.
    """
    if weights is None:
        weights = SalienceWeights()

    # Compute individual components
    recency = compute_recency(
        last_accessed_at=memory.last_accessed_at,
        now=now,
        decay_lambda=DECAY_LAMBDA,
    )
    frequency = compute_frequency(
        access_count=memory.access_count,
        max_access_count=max_access_count,
    )
    emotional = compute_emotional_weight(
        memory_metadata=memory.metadata if hasattr(memory, "metadata") else None,
    )
    causal = compute_causal_centrality(
        memory_metadata=memory.metadata if hasattr(memory, "metadata") else None,
        entity_links=memory.entity_links if hasattr(memory, "entity_links") else None,
    )

    components = SalienceComponents(
        recency=recency,
        frequency=frequency,
        emotional_weight=emotional,
        causal_centrality=causal,
    )

    # Weighted sum
    raw_score = (
        weights.w_recency * recency
        + weights.w_frequency * frequency
        + weights.w_emotional * emotional
        + weights.w_causal * causal
    )

    # Clamp to [0.0, 1.0]
    final_score = round(min(max(raw_score, 0.0), 1.0), 6)

    memory_id_str: Optional[str] = None
    if memory.id is not None:
        memory_id_str = str(memory.id)

    logger.debug(
        "Salience calculated: memory=%s  score=%.4f  "
        "recency=%.4f  frequency=%.4f  emotional=%.4f  causal=%.4f",
        memory_id_str or "unknown",
        final_score,
        recency,
        frequency,
        emotional,
        causal,
    )

    return SalienceResult(
        memory_id=memory_id_str,
        score=final_score,
        components=components,
        weights=weights,
    )
