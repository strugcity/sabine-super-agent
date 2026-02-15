"""
Non-Monotonic Belief Revision (Phase 2C / BELIEF-004 through BELIEF-007)
=========================================================================

Implements the belief revision formula from PRD 4.4.2:

    v' = a · λ_α + v

Where:
  v     = current belief strength (memory confidence)
  a     = argument force (confidence of new evidence)
  λ_α   = open-mindedness parameter (user-configurable, default 0.5)

Also implements the Martingale score (PRD 4.4.1) for epistemic integrity:

    M = Σ(predicted_update - actual_update)² / n

If M < 0.1 for 7 consecutive days → triggers self-reflection prompt.
"""

import logging
import math
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_LAMBDA_ALPHA: float = 0.5
MIN_LAMBDA_ALPHA: float = 0.05
MAX_LAMBDA_ALPHA: float = 0.95
MIN_CONFIDENCE: float = 0.0
MAX_CONFIDENCE: float = 1.0

# Martingale alert threshold (BELIEF-002)
MARTINGALE_ALERT_THRESHOLD: float = 0.1
MARTINGALE_CONSECUTIVE_DAYS: int = 7


# =============================================================================
# Models
# =============================================================================

class RevisionResult(BaseModel):
    """Result of applying the belief revision formula."""
    original_confidence: float = Field(..., ge=0.0, le=1.0)
    new_confidence: float = Field(..., ge=0.0, le=1.0)
    argument_force: float = Field(..., ge=0.0, le=1.0)
    lambda_alpha: float = Field(..., ge=0.0, le=1.0)
    delta: float = Field(..., description="Change in confidence: new - original")
    new_version: int = Field(..., ge=1, description="Incremented belief version")


class MartingaleResult(BaseModel):
    """Result of Martingale score calculation."""
    score: float = Field(..., ge=0.0, description="Martingale score M")
    n_samples: int = Field(..., ge=0, description="Number of update pairs used")
    is_alert: bool = Field(default=False, description="True if M < threshold")
    message: str = Field(default="", description="Human-readable status")


class LambdaAlphaConfig(BaseModel):
    """Configuration for the open-mindedness parameter."""
    global_value: float = Field(
        default=DEFAULT_LAMBDA_ALPHA,
        ge=MIN_LAMBDA_ALPHA,
        le=MAX_LAMBDA_ALPHA,
        description="Global open-mindedness parameter",
    )
    domain_overrides: Dict[str, float] = Field(
        default_factory=dict,
        description="Per-domain overrides (e.g., {'work': 0.3, 'personal': 0.7})",
    )

    @model_validator(mode="after")
    def validate_domain_values(self) -> "LambdaAlphaConfig":
        """Ensure all domain overrides are within valid range."""
        for domain, value in self.domain_overrides.items():
            if not (MIN_LAMBDA_ALPHA <= value <= MAX_LAMBDA_ALPHA):
                raise ValueError(
                    f"Domain '{domain}' lambda_alpha={value} out of range "
                    f"[{MIN_LAMBDA_ALPHA}, {MAX_LAMBDA_ALPHA}]"
                )
        return self


# =============================================================================
# Core Revision Formula
# =============================================================================

def revise_belief(
    current_confidence: float,
    argument_force: float,
    lambda_alpha: float = DEFAULT_LAMBDA_ALPHA,
    current_version: int = 1,
) -> RevisionResult:
    """
    Apply the non-monotonic belief revision formula.

    Formula: v' = a · λ_α + v (clamped to [0.0, 1.0])

    Parameters
    ----------
    current_confidence : float
        Current belief strength v (0.0-1.0).
    argument_force : float
        Confidence of new evidence a (0.0-1.0).
        Positive values strengthen, negative values weaken.
        In practice: a = new_confidence - current_confidence
        (so it can be negative when new evidence is weaker).
    lambda_alpha : float
        Open-mindedness parameter λ_α (default 0.5).
    current_version : int
        Current belief version counter.

    Returns
    -------
    RevisionResult
    """
    # Clamp inputs
    v = max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, current_confidence))
    a = max(-1.0, min(1.0, argument_force))
    la = max(MIN_LAMBDA_ALPHA, min(MAX_LAMBDA_ALPHA, lambda_alpha))

    # Apply formula: v' = a · λ_α + v
    v_prime = a * la + v

    # Clamp output to valid range
    v_prime = max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, v_prime))

    return RevisionResult(
        original_confidence=v,
        new_confidence=round(v_prime, 6),
        argument_force=a,
        lambda_alpha=la,
        delta=round(v_prime - v, 6),
        new_version=current_version + 1,
    )


# =============================================================================
# Martingale Score (BELIEF-001, BELIEF-002)
# =============================================================================

def calculate_martingale_score(
    predicted_updates: List[float],
    actual_updates: List[float],
) -> MartingaleResult:
    """
    Calculate the Martingale score for epistemic integrity monitoring.

    Formula: M = Σ(predicted_update - actual_update)² / n

    A consistently low M (< 0.1) indicates the system is only confirming
    existing beliefs — a signal of confirmation bias.

    Parameters
    ----------
    predicted_updates : list[float]
        The confidence deltas the system predicted it would make.
    actual_updates : list[float]
        The confidence deltas that were actually applied.

    Returns
    -------
    MartingaleResult
    """
    if not predicted_updates or not actual_updates:
        return MartingaleResult(
            score=0.0,
            n_samples=0,
            is_alert=False,
            message="Insufficient data for Martingale calculation",
        )

    n = min(len(predicted_updates), len(actual_updates))
    if n == 0:
        return MartingaleResult(
            score=0.0,
            n_samples=0,
            is_alert=False,
            message="No matching update pairs",
        )

    sum_squared_diff = sum(
        (predicted_updates[i] - actual_updates[i]) ** 2
        for i in range(n)
    )
    m_score = sum_squared_diff / n

    is_alert = m_score < MARTINGALE_ALERT_THRESHOLD and n >= MARTINGALE_CONSECUTIVE_DAYS

    if is_alert:
        message = (
            f"ALERT: Martingale score M={m_score:.4f} < {MARTINGALE_ALERT_THRESHOLD} "
            f"over {n} samples. Possible confirmation bias detected. "
            "Consider triggering self-reflection prompt (BELIEF-002)."
        )
    else:
        message = f"Martingale score M={m_score:.4f} over {n} samples. Epistemic health OK."

    return MartingaleResult(
        score=round(m_score, 6),
        n_samples=n,
        is_alert=is_alert,
        message=message,
    )


# =============================================================================
# Lambda Alpha Management (BELIEF-004, BELIEF-005, BELIEF-006)
# =============================================================================

async def get_lambda_alpha(
    user_id: str,
    domain: Optional[str] = None,
) -> float:
    """
    Look up the open-mindedness parameter λ_α for a user.

    Fallback chain:
      1. Per-domain override (if domain specified)
      2. User's global λ_α from user_config
      3. DEFAULT_LAMBDA_ALPHA (0.5)

    Parameters
    ----------
    user_id : str
        UUID string of the user.
    domain : str, optional
        Domain context (e.g., "work", "personal").

    Returns
    -------
    float
        The λ_α value to use.
    """
    try:
        from lib.db.user_config import get_user_config

        # Try per-domain first (BELIEF-006)
        if domain:
            domain_key = f"lambda_alpha_{domain}"
            domain_value = await get_user_config(user_id, domain_key)
            if domain_value:
                parsed = float(domain_value)
                if MIN_LAMBDA_ALPHA <= parsed <= MAX_LAMBDA_ALPHA:
                    logger.debug(
                        "Using per-domain lambda_alpha[%s]=%s for user=%s",
                        domain, parsed, user_id[:8],
                    )
                    return parsed

        # Try global (BELIEF-004)
        global_value = await get_user_config(user_id, "lambda_alpha")
        if global_value:
            parsed = float(global_value)
            if MIN_LAMBDA_ALPHA <= parsed <= MAX_LAMBDA_ALPHA:
                logger.debug(
                    "Using global lambda_alpha=%s for user=%s",
                    parsed, user_id[:8],
                )
                return parsed

    except Exception as exc:
        logger.warning(
            "Failed to load lambda_alpha for user=%s: %s; using default",
            user_id[:8], exc,
        )

    # Default (BELIEF-005)
    return DEFAULT_LAMBDA_ALPHA


async def set_lambda_alpha(
    user_id: str,
    value: float,
    domain: Optional[str] = None,
) -> bool:
    """
    Persist the open-mindedness parameter λ_α for a user.

    Parameters
    ----------
    user_id : str
        UUID string of the user.
    value : float
        λ_α value (0.05-0.95).
    domain : str, optional
        Domain context. If None, sets the global value.

    Returns
    -------
    bool
        True on success.
    """
    if not (MIN_LAMBDA_ALPHA <= value <= MAX_LAMBDA_ALPHA):
        logger.error(
            "Invalid lambda_alpha=%s (must be %.2f-%.2f)",
            value, MIN_LAMBDA_ALPHA, MAX_LAMBDA_ALPHA,
        )
        return False

    try:
        from lib.db.user_config import set_user_config

        key = f"lambda_alpha_{domain}" if domain else "lambda_alpha"
        success = await set_user_config(user_id, key, str(value))

        if success:
            logger.info(
                "Set lambda_alpha=%s (domain=%s) for user=%s",
                value, domain or "global", user_id[:8],
            )
        return success

    except Exception as exc:
        logger.error(
            "Failed to set lambda_alpha for user=%s: %s",
            user_id[:8], exc,
        )
        return False


# =============================================================================
# Integration Helper — For Slow Path resolve_conflicts()
# =============================================================================

async def resolve_conflict_with_revision(
    existing_confidence: float,
    new_evidence_confidence: float,
    user_id: str,
    domain: Optional[str] = None,
    current_version: int = 1,
) -> Tuple[RevisionResult, float]:
    """
    Convenience wrapper that loads λ_α and applies the revision formula.

    This is the function that ``backend/worker/slow_path.py``'s
    ``resolve_conflicts()`` should call instead of "newer data wins."

    Parameters
    ----------
    existing_confidence : float
        Current belief strength in the existing memory.
    new_evidence_confidence : float
        Confidence of the new evidence.
    user_id : str
        UUID for λ_α lookup.
    domain : str, optional
        Domain context for per-domain λ_α.
    current_version : int
        Current belief version of the memory.

    Returns
    -------
    tuple[RevisionResult, float]
        The revision result and the λ_α that was used.
    """
    la = await get_lambda_alpha(user_id, domain=domain)

    # Argument force = difference between new and existing confidence
    argument_force = new_evidence_confidence - existing_confidence

    result = revise_belief(
        current_confidence=existing_confidence,
        argument_force=argument_force,
        lambda_alpha=la,
        current_version=current_version,
    )

    return result, la
