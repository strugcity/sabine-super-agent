"""
Salience Settings Router (MEM-004)
====================================

API endpoints for managing per-user salience scoring weights.

Endpoints:
- GET  /api/settings/salience — Get current weights for user (or defaults)
- PUT  /api/settings/salience — Update weights for user

Weights are stored in Redis: ``sabine:salience_weights:{user_id}``

PRD Reference: MEM-004 (Salience Settings API)
"""

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.agent.shared import verify_api_key

logger = logging.getLogger(__name__)

# Redis key prefix for user-level salience weights
_REDIS_KEY_PREFIX: str = "sabine:salience_weights"

# TTL for cached weights in Redis (30 days)
_WEIGHTS_TTL: int = 30 * 86_400

# Create router with /api/settings prefix
router = APIRouter(prefix="/api/settings", tags=["salience-settings"])


# =============================================================================
# Request/Response Models
# =============================================================================

class SalienceWeightsRequest(BaseModel):
    """Request body for updating salience weights."""
    w_recency: float = Field(
        ..., ge=0.0, le=1.0,
        description="Weight for recency component",
    )
    w_frequency: float = Field(
        ..., ge=0.0, le=1.0,
        description="Weight for frequency component",
    )
    w_emotional: float = Field(
        ..., ge=0.0, le=1.0,
        description="Weight for emotional weight component",
    )
    w_causal: float = Field(
        ..., ge=0.0, le=1.0,
        description="Weight for causal centrality component",
    )


class SalienceWeightsResponse(BaseModel):
    """Response body for salience weight queries."""
    user_id: str = Field(
        ..., description="User UUID these weights belong to",
    )
    w_recency: float = Field(
        ..., description="Weight for recency component",
    )
    w_frequency: float = Field(
        ..., description="Weight for frequency component",
    )
    w_emotional: float = Field(
        ..., description="Weight for emotional weight component",
    )
    w_causal: float = Field(
        ..., description="Weight for causal centrality component",
    )
    is_default: bool = Field(
        ..., description="True if these are default weights (no custom override stored)",
    )


# =============================================================================
# Default Weights (matching backend/services/salience.py)
# =============================================================================

_DEFAULT_WEIGHTS: Dict[str, float] = {
    "w_recency": 0.4,
    "w_frequency": 0.2,
    "w_emotional": 0.2,
    "w_causal": 0.2,
}


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/salience", response_model=SalienceWeightsResponse)
async def get_salience_weights(
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> SalienceWeightsResponse:
    """
    Get current salience weights for a user.

    Returns the user-specific weights stored in Redis, or the default
    weights if no custom weights have been set.

    Parameters
    ----------
    user_id : str
        User UUID to look up weights for.

    Returns
    -------
    SalienceWeightsResponse
        Current weights with ``is_default`` flag.
    """
    logger.info("Getting salience weights for user %s", user_id)

    try:
        redis_client = _get_redis()
        key = f"{_REDIS_KEY_PREFIX}:{user_id}"
        raw: Optional[str] = redis_client.get(key)

        if raw is not None:
            data: Dict[str, Any] = json.loads(raw)
            logger.debug("Found custom weights for user %s: %s", user_id, data)
            return SalienceWeightsResponse(
                user_id=user_id,
                w_recency=data.get("w_recency", _DEFAULT_WEIGHTS["w_recency"]),
                w_frequency=data.get("w_frequency", _DEFAULT_WEIGHTS["w_frequency"]),
                w_emotional=data.get("w_emotional", _DEFAULT_WEIGHTS["w_emotional"]),
                w_causal=data.get("w_causal", _DEFAULT_WEIGHTS["w_causal"]),
                is_default=False,
            )

        logger.debug("No custom weights for user %s; returning defaults", user_id)
        return SalienceWeightsResponse(
            user_id=user_id,
            **_DEFAULT_WEIGHTS,
            is_default=True,
        )

    except Exception as exc:
        logger.error("Failed to get salience weights: %s", exc, exc_info=True)
        # Fall back to defaults on Redis failure
        return SalienceWeightsResponse(
            user_id=user_id,
            **_DEFAULT_WEIGHTS,
            is_default=True,
        )


@router.put("/salience", response_model=SalienceWeightsResponse)
async def update_salience_weights(
    request: SalienceWeightsRequest,
    user_id: str = Query(..., description="User UUID"),
    _: bool = Depends(verify_api_key),
) -> SalienceWeightsResponse:
    """
    Update salience weights for a user.

    Validates that weights sum to 1.0, then persists to Redis.

    Parameters
    ----------
    request : SalienceWeightsRequest
        New weights (must sum to 1.0).
    user_id : str
        User UUID.

    Returns
    -------
    SalienceWeightsResponse
        Updated weights.

    Raises
    ------
    HTTPException (400)
        If weights do not sum to 1.0.
    HTTPException (500)
        If Redis write fails.
    """
    logger.info("Updating salience weights for user %s", user_id)

    # Validate weights sum to 1.0
    total = request.w_recency + request.w_frequency + request.w_emotional + request.w_causal
    if abs(total - 1.0) > 1e-6:
        raise HTTPException(
            status_code=400,
            detail=f"Weights must sum to 1.0, got {total:.6f}",
        )

    weights_data: Dict[str, float] = {
        "w_recency": request.w_recency,
        "w_frequency": request.w_frequency,
        "w_emotional": request.w_emotional,
        "w_causal": request.w_causal,
    }

    try:
        redis_client = _get_redis()
        key = f"{_REDIS_KEY_PREFIX}:{user_id}"
        redis_client.setex(key, _WEIGHTS_TTL, json.dumps(weights_data))

        logger.info(
            "Saved salience weights for user %s: %s",
            user_id, weights_data,
        )

        return SalienceWeightsResponse(
            user_id=user_id,
            **weights_data,
            is_default=False,
        )

    except Exception as exc:
        logger.error("Failed to save salience weights: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save salience weights: {str(exc)}",
        )


# =============================================================================
# Internal Helpers
# =============================================================================

def _get_redis() -> Any:
    """Lazy-load the Redis client singleton."""
    from backend.services.redis_client import get_redis_client
    return get_redis_client()
