"""
Value-of-Information (VoI) Calculator (Phase 2D / DECIDE-001 through DECIDE-004)
==================================================================================

Implements the Active Inference decision logic from PRD 4.5.1:

    If (C_error x P_error) > C_int -> ASK for clarification
    Else -> PROCEED with best guess

Where:
  C_error = Cost of making an error (action reversibility)
  P_error = Probability of error (context ambiguity)
  C_int   = Cost of interruption (user friction, configurable)
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_C_INT: float = 0.3  # Default chattiness threshold (balanced)
MIN_C_INT: float = 0.05
MAX_C_INT: float = 0.95


# =============================================================================
# Enums & Models
# =============================================================================

class ActionType(str, Enum):
    """Action reversibility classification (PRD 4.5.1)."""
    IRREVERSIBLE = "irreversible"   # C_error = 1.0
    REVERSIBLE = "reversible"       # C_error = 0.5
    INFORMATIONAL = "informational" # C_error = 0.2


# Map action type to C_error
ACTION_TYPE_COSTS: Dict[ActionType, float] = {
    ActionType.IRREVERSIBLE: 1.0,
    ActionType.REVERSIBLE: 0.5,
    ActionType.INFORMATIONAL: 0.2,
}

# Tool name -> action type mapping (DECIDE-001)
# This is the initial catalog; extend as new tools are added.
TOOL_ACTION_MAP: Dict[str, ActionType] = {
    # Irreversible
    "send_email": ActionType.IRREVERSIBLE,
    "send_sms": ActionType.IRREVERSIBLE,
    "delete_file": ActionType.IRREVERSIBLE,
    "send_slack_message": ActionType.IRREVERSIBLE,
    "make_purchase": ActionType.IRREVERSIBLE,
    "confirm_appointment": ActionType.IRREVERSIBLE,
    # Reversible
    "create_draft": ActionType.REVERSIBLE,
    "schedule_event": ActionType.REVERSIBLE,
    "create_reminder": ActionType.REVERSIBLE,
    "create_task": ActionType.REVERSIBLE,
    "update_calendar": ActionType.REVERSIBLE,
    # Informational
    "search": ActionType.INFORMATIONAL,
    "lookup": ActionType.INFORMATIONAL,
    "get_weather": ActionType.INFORMATIONAL,
    "get_calendar": ActionType.INFORMATIONAL,
    "retrieve_context": ActionType.INFORMATIONAL,
    "summarize": ActionType.INFORMATIONAL,
}


class VoIResult(BaseModel):
    """Result of a Value-of-Information calculation."""
    action_type: ActionType
    c_error: float = Field(..., ge=0.0, le=1.0, description="Cost of error")
    p_error: float = Field(..., ge=0.0, le=1.0, description="Probability of error")
    c_int: float = Field(..., ge=0.0, le=1.0, description="Cost of interruption")
    voi_score: float = Field(..., description="(C_error * P_error) - C_int")
    should_clarify: bool = Field(..., description="True if VoI > 0 (should ask)")
    tool_name: Optional[str] = Field(default=None, description="Tool that triggered the check")
    reasoning: str = Field(default="", description="Human-readable explanation")


class AmbiguitySignals(BaseModel):
    """Signals used to estimate P_error (context ambiguity)."""
    retrieval_count: int = Field(default=0, description="Number of memories retrieved")
    avg_salience: float = Field(default=0.5, ge=0.0, le=1.0, description="Average salience of retrieved memories")
    query_length: int = Field(default=0, description="Length of user query in tokens (approx words)")
    has_explicit_target: bool = Field(default=False, description="Whether query specifies a clear target")
    entity_count: int = Field(default=0, description="Number of entities extracted")


# =============================================================================
# Action Classification (DECIDE-001)
# =============================================================================

def classify_action(
    tool_name: str,
    tool_input: Optional[Dict[str, Any]] = None,
) -> ActionType:
    """
    Classify a tool invocation by its reversibility.

    Uses the TOOL_ACTION_MAP for known tools, falls back to REVERSIBLE
    for unknown tools (conservative default).

    Parameters
    ----------
    tool_name : str
        Name of the tool being invoked.
    tool_input : dict, optional
        Tool input arguments (for future context-aware classification).

    Returns
    -------
    ActionType
    """
    # Normalize tool name
    normalized = tool_name.lower().strip().replace("-", "_").replace(" ", "_")

    # Direct lookup
    if normalized in TOOL_ACTION_MAP:
        return TOOL_ACTION_MAP[normalized]

    # Partial match: check if any key is a substring
    for key, action_type in TOOL_ACTION_MAP.items():
        if key in normalized or normalized in key:
            logger.debug(
                "Partial match: tool=%s matched key=%s -> %s",
                tool_name, key, action_type.value,
            )
            return action_type

    # Unknown tool -> conservative default
    logger.info(
        "Unknown tool '%s' -- defaulting to REVERSIBLE (conservative)",
        tool_name,
    )
    return ActionType.REVERSIBLE


# =============================================================================
# Ambiguity Scoring (DECIDE-002)
# =============================================================================

def calculate_ambiguity(
    signals: AmbiguitySignals,
) -> float:
    """
    Calculate P_error (probability of error) from context signals.

    Higher ambiguity -> higher P_error -> more likely to trigger clarification.

    Heuristic components (each 0.0-1.0, weighted average):
      - Sparse retrieval (few memories) -> high ambiguity
      - Low salience scores -> high ambiguity
      - Short query -> potentially ambiguous
      - No explicit target -> ambiguous
      - Few entities extracted -> ambiguous

    Parameters
    ----------
    signals : AmbiguitySignals
        Context signals from retrieval and entity extraction.

    Returns
    -------
    float
        P_error in range [0.0, 1.0].
    """
    components: List[Tuple[float, float]] = []  # (score, weight)

    # Retrieval sparsity: fewer memories = more ambiguous
    if signals.retrieval_count == 0:
        retrieval_score = 0.9
    elif signals.retrieval_count <= 2:
        retrieval_score = 0.6
    elif signals.retrieval_count <= 5:
        retrieval_score = 0.3
    else:
        retrieval_score = 0.1
    components.append((retrieval_score, 0.25))

    # Salience: low average salience = uncertain context
    salience_ambiguity = 1.0 - signals.avg_salience
    components.append((salience_ambiguity, 0.25))

    # Query length: very short queries are more ambiguous
    if signals.query_length <= 3:
        length_score = 0.8
    elif signals.query_length <= 10:
        length_score = 0.4
    else:
        length_score = 0.1
    components.append((length_score, 0.15))

    # Explicit target: no target = ambiguous
    target_score = 0.1 if signals.has_explicit_target else 0.7
    components.append((target_score, 0.2))

    # Entity count: few entities = ambiguous context
    if signals.entity_count == 0:
        entity_score = 0.8
    elif signals.entity_count <= 2:
        entity_score = 0.4
    else:
        entity_score = 0.1
    components.append((entity_score, 0.15))

    # Weighted average
    total_weight = sum(w for _, w in components)
    p_error = sum(s * w for s, w in components) / total_weight

    return round(max(0.0, min(1.0, p_error)), 4)


# =============================================================================
# VoI Calculation (DECIDE-002, DECIDE-003)
# =============================================================================

def calculate_voi(
    action_type: ActionType,
    p_error: float,
    c_int: float = DEFAULT_C_INT,
    tool_name: Optional[str] = None,
) -> VoIResult:
    """
    Calculate the Value of Information for a decision.

    Formula: VoI = (C_error x P_error) - C_int
    If VoI > 0 -> should ask for clarification.

    Parameters
    ----------
    action_type : ActionType
        Classified action reversibility.
    p_error : float
        Probability of error (from ambiguity scoring).
    c_int : float
        Cost of interruption (user's chattiness threshold).
    tool_name : str, optional
        Name of the tool for logging.

    Returns
    -------
    VoIResult
    """
    c_error = ACTION_TYPE_COSTS[action_type]
    voi_score = (c_error * p_error) - c_int
    should_clarify = voi_score > 0

    # Build reasoning
    if should_clarify:
        reasoning = (
            f"VoI={voi_score:.3f} > 0: C_error({c_error:.1f}) x P_error({p_error:.3f}) = "
            f"{c_error * p_error:.3f} exceeds C_int({c_int:.2f}). "
            f"Recommend asking for clarification before {action_type.value} action."
        )
    else:
        reasoning = (
            f"VoI={voi_score:.3f} <= 0: C_error({c_error:.1f}) x P_error({p_error:.3f}) = "
            f"{c_error * p_error:.3f} does not exceed C_int({c_int:.2f}). "
            f"Proceeding with best guess."
        )

    logger.info(
        "VoI calculation: tool=%s action=%s C_e=%.1f P_e=%.3f C_i=%.2f VoI=%.3f -> %s",
        tool_name or "unknown",
        action_type.value,
        c_error,
        p_error,
        c_int,
        voi_score,
        "CLARIFY" if should_clarify else "PROCEED",
    )

    return VoIResult(
        action_type=action_type,
        c_error=c_error,
        p_error=p_error,
        c_int=c_int,
        voi_score=round(voi_score, 6),
        should_clarify=should_clarify,
        tool_name=tool_name,
        reasoning=reasoning,
    )


# =============================================================================
# C_int Management (DECIDE-003)
# =============================================================================

async def get_c_int(user_id: str) -> float:
    """
    Get the user's chattiness threshold C_int.

    Falls back to DEFAULT_C_INT (0.3) if not configured.

    Parameters
    ----------
    user_id : str
        UUID string of the user.

    Returns
    -------
    float
        C_int value in [0.05, 0.95].
    """
    try:
        from lib.db.user_config import get_user_config
        value = await get_user_config(user_id, "c_int")
        if value:
            parsed = float(value)
            if MIN_C_INT <= parsed <= MAX_C_INT:
                return parsed
    except Exception as exc:
        logger.warning("Failed to load c_int for user=%s: %s", user_id[:8], exc)

    return DEFAULT_C_INT


async def set_c_int(user_id: str, value: float) -> bool:
    """
    Set the user's chattiness threshold C_int.

    Parameters
    ----------
    user_id : str
        UUID string of the user.
    value : float
        C_int value (0.05-0.95). Lower = more chatty, higher = less interruptions.

    Returns
    -------
    bool
        True on success.
    """
    if not (MIN_C_INT <= value <= MAX_C_INT):
        logger.error("Invalid c_int=%s (must be %.2f-%.2f)", value, MIN_C_INT, MAX_C_INT)
        return False

    try:
        from lib.db.user_config import set_user_config
        return await set_user_config(user_id, "c_int", str(value))
    except Exception as exc:
        logger.error("Failed to set c_int for user=%s: %s", user_id[:8], exc)
        return False


# =============================================================================
# High-Level Entry Point
# =============================================================================

async def evaluate_action(
    tool_name: str,
    user_id: str,
    ambiguity_signals: Optional[AmbiguitySignals] = None,
    tool_input: Optional[Dict[str, Any]] = None,
) -> VoIResult:
    """
    Full VoI evaluation pipeline for a tool invocation.

    Steps:
      1. Classify action type (DECIDE-001)
      2. Calculate ambiguity / P_error (DECIDE-002)
      3. Load user's C_int (DECIDE-003)
      4. Calculate VoI and return decision

    Parameters
    ----------
    tool_name : str
        Name of the tool being invoked.
    user_id : str
        UUID for C_int lookup.
    ambiguity_signals : AmbiguitySignals, optional
        Pre-computed context signals. If None, uses conservative defaults.
    tool_input : dict, optional
        Tool arguments for context-aware classification.

    Returns
    -------
    VoIResult
    """
    # Step 1: Classify
    action_type = classify_action(tool_name, tool_input)

    # Step 2: Ambiguity
    if ambiguity_signals is None:
        ambiguity_signals = AmbiguitySignals()  # Conservative defaults
    p_error = calculate_ambiguity(ambiguity_signals)

    # Step 3: Load C_int
    c_int = await get_c_int(user_id)

    # Step 4: Calculate VoI
    return calculate_voi(
        action_type=action_type,
        p_error=p_error,
        c_int=c_int,
        tool_name=tool_name,
    )
