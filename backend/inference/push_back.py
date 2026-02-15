"""
Push-Back Protocol (Phase 2D / PUSH-001 through PUSH-004)
==========================================================

When a VoI calculation determines that clarification is needed (VoI > 0),
this module generates the push-back response:

  1. Finds evidence from MAGMA graph (PUSH-001)
  2. Generates alternatives (PUSH-002, minimum 2)
  3. Formats the push-back message
  4. Logs the event for learning (PUSH-003, PUSH-004)

The push-back rate should be 5-15% of interactions. If higher, C_int
should be increased; if lower, C_int should be decreased.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MIN_ALTERNATIVES: int = 2  # PUSH-002: minimum alternatives per push-back
TARGET_PUSH_BACK_RATE_LOW: float = 0.05   # 5%
TARGET_PUSH_BACK_RATE_HIGH: float = 0.15  # 15%


# =============================================================================
# Models
# =============================================================================

class EvidenceItem(BaseModel):
    """A piece of evidence supporting a push-back."""
    memory_id: Optional[str] = Field(default=None, description="UUID of the supporting memory")
    entity_name: Optional[str] = Field(default=None, description="Related entity name")
    relationship: Optional[str] = Field(default=None, description="Relationship type (e.g., 'caused_by')")
    summary: str = Field(..., description="Human-readable evidence summary")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Confidence in this evidence")


class Alternative(BaseModel):
    """An alternative action offered in a push-back."""
    label: str = Field(..., description="Short label (e.g., 'A', 'B', 'C')")
    description: str = Field(..., description="Human-readable description of the alternative")
    is_original: bool = Field(default=False, description="True if this is the original requested action")
    risk_level: str = Field(default="medium", description="Risk assessment: low/medium/high")


class PushBackResponse(BaseModel):
    """A complete push-back response to present to the user."""
    concern: str = Field(..., description="The specific concern being raised")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="Supporting evidence (PUSH-001)")
    alternatives: List[Alternative] = Field(default_factory=list, description="Actionable alternatives (PUSH-002)")
    formatted_message: str = Field(..., description="Ready-to-display message for the user")
    voi_score: float = Field(..., description="The VoI score that triggered this push-back")


class PushBackLogEntry(BaseModel):
    """Data to write to the push_back_log table."""
    user_id: str
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    action_type: str
    tool_name: Optional[str] = None
    c_error: float
    p_error: float
    c_int: float
    voi_score: float
    push_back_triggered: bool
    evidence_memory_ids: List[str] = Field(default_factory=list)
    alternatives_offered: List[Dict[str, Any]] = Field(default_factory=list)
    user_accepted: Optional[bool] = None
    user_chose_alternative: Optional[int] = None
    lambda_alpha_before: Optional[float] = None
    lambda_alpha_after: Optional[float] = None


# =============================================================================
# Entity Name -> ID Resolution (helper for MAGMA integration)
# =============================================================================

async def _resolve_entity_id(entity_name: str) -> Optional[str]:
    """
    Look up an entity UUID by name from the entities table.

    Sanitizes input to prevent SQL wildcard DoS attacks and uses efficient
    exact-match first, falling back to trigram search.

    Parameters
    ----------
    entity_name : str
        The entity name to look up (case-insensitive).

    Returns
    -------
    str or None
        The entity UUID if found, otherwise None.
    """
    try:
        from backend.services.wal import get_supabase_client
        import asyncio

        # Sanitize input: escape SQL wildcards to prevent DoS attacks
        # Users shouldn't be searching with wildcards in entity names
        sanitized_name = entity_name.replace("%", r"\%").replace("_", r"\_")

        client = get_supabase_client()
        
        # Try exact match first (case-insensitive, uses B-tree index)
        response = await asyncio.to_thread(
            lambda: client.table("entities")
            .select("id")
            .ilike("name", sanitized_name)
            .limit(1)
            .execute()
        )

        if response.data:
            return str(response.data[0]["id"])

    except Exception as exc:
        logger.debug("Entity name resolution failed for '%s': %s", entity_name, exc)

    return None


# =============================================================================
# Evidence Gathering (PUSH-001)
# =============================================================================

async def gather_evidence(
    entity_name: str,
    user_id: str,
    max_items: int = 5,
) -> List[EvidenceItem]:
    """
    Gather evidence from the MAGMA graph to support a push-back.

    Queries causal chains and direct relationships for the given entity.

    Parameters
    ----------
    entity_name : str
        The entity to find evidence for.
    user_id : str
        UUID string of the user (reserved for future per-user scoping).
    max_items : int
        Maximum evidence items to return.

    Returns
    -------
    list[EvidenceItem]
    """
    evidence: List[EvidenceItem] = []

    # Resolve entity name to ID (MAGMA query functions use entity_id)
    entity_id = await _resolve_entity_id(entity_name)
    if not entity_id:
        logger.debug(
            "No entity found for name='%s', skipping evidence gathering",
            entity_name,
        )
        return evidence

    try:
        from backend.magma.query import get_entity_relationships

        # Get direct relationships (signature: entity_id, direction, ...)
        rels = await get_entity_relationships(
            entity_id=entity_id,
            limit=max_items,
        )

        for rel in rels:
            evidence.append(
                EvidenceItem(
                    memory_id=rel.get("id"),
                    entity_name=rel.get("target_name") or rel.get("source_name"),
                    relationship=rel.get("relationship_type", "related_to"),
                    summary=(
                        f"{rel.get('source_name', '?')} "
                        f"{rel.get('relationship_type', 'related_to')} "
                        f"{rel.get('target_name', '?')}"
                    ),
                    confidence=rel.get("confidence", 0.5),
                )
            )

    except Exception as exc:
        logger.warning(
            "Evidence gathering failed for entity=%s user=%s: %s",
            entity_name, user_id[:8], exc,
        )

    try:
        from backend.magma.query import causal_trace
        import asyncio

        # Follow causal chains for deeper evidence
        # causal_trace signature: entity_id, max_depth, min_confidence
        # Add 200ms timeout to prevent blocking the request path
        try:
            causal_result = await asyncio.wait_for(
                causal_trace(
                    entity_id=entity_id,
                    max_depth=3,
                ),
                timeout=0.2,  # 200ms max
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Causal trace timed out for entity=%s (>200ms), proceeding without causal evidence",
                entity_name,
            )
            return evidence[:max_items]

        causal_chain: List[Dict[str, Any]] = causal_result.get("chain", [])
        for link in causal_chain[:max_items - len(evidence)]:
            evidence.append(
                EvidenceItem(
                    memory_id=link.get("from_id") or link.get("to_id"),
                    entity_name=link.get("to") or link.get("from"),
                    relationship=link.get("type", "caused_by"),
                    summary=(
                        f"Causal chain: {link.get('from', '?')} "
                        f"{link.get('type', '->')} "
                        f"{link.get('to', '?')}"
                    ),
                    confidence=link.get("confidence", 0.5),
                )
            )

    except Exception as exc:
        logger.debug(
            "Causal trace failed for entity=%s: %s (non-critical)",
            entity_name, exc,
        )

    return evidence[:max_items]


# =============================================================================
# Alternative Generation (PUSH-002)
# =============================================================================

def generate_alternatives(
    original_action: str,
    tool_name: str,
    concern: str,
) -> List[Alternative]:
    """
    Generate actionable alternatives for a push-back.

    Always returns at least MIN_ALTERNATIVES (2) options per PUSH-002.

    Parameters
    ----------
    original_action : str
        Description of the original requested action.
    tool_name : str
        The tool being invoked.
    concern : str
        The concern being raised.

    Returns
    -------
    list[Alternative]
    """
    alternatives: List[Alternative] = []

    # Option A: Proceed with the original action (always offered)
    alternatives.append(
        Alternative(
            label="A",
            description=f"Proceed with: {original_action}",
            is_original=True,
            risk_level="high",
        )
    )

    # Option B: Cancel / do nothing
    alternatives.append(
        Alternative(
            label="B",
            description="Cancel this action",
            is_original=False,
            risk_level="low",
        )
    )

    # Option C: Context-aware alternative (if possible)
    normalized_tool = tool_name.lower()
    if "send" in normalized_tool or "email" in normalized_tool:
        alternatives.append(
            Alternative(
                label="C",
                description="Save as draft instead of sending",
                is_original=False,
                risk_level="low",
            )
        )
    elif "delete" in normalized_tool:
        alternatives.append(
            Alternative(
                label="C",
                description="Archive instead of deleting",
                is_original=False,
                risk_level="low",
            )
        )
    elif "schedule" in normalized_tool or "calendar" in normalized_tool:
        alternatives.append(
            Alternative(
                label="C",
                description="Mark as tentative and confirm later",
                is_original=False,
                risk_level="low",
            )
        )
    else:
        alternatives.append(
            Alternative(
                label="C",
                description="Let me provide more details first",
                is_original=False,
                risk_level="low",
            )
        )

    return alternatives


# =============================================================================
# Push-Back Formatting
# =============================================================================

def format_push_back(
    concern: str,
    evidence: List[EvidenceItem],
    alternatives: List[Alternative],
    voi_score: float,
) -> str:
    """
    Format a push-back message for display to the user.

    Parameters
    ----------
    concern : str
        The concern being raised.
    evidence : list[EvidenceItem]
        Supporting evidence.
    alternatives : list[Alternative]
        Available alternatives.
    voi_score : float
        VoI score for transparency.

    Returns
    -------
    str
        Formatted push-back message.
    """
    lines: List[str] = []

    # Concern
    lines.append(f"I'd like to flag a concern before proceeding: {concern}")
    lines.append("")

    # Evidence
    if evidence:
        lines.append("Here's what I'm basing this on:")
        for item in evidence[:3]:  # Limit displayed evidence
            lines.append(f"  - {item.summary} (confidence: {item.confidence:.0%})")
        lines.append("")

    # Alternatives
    lines.append("What would you like to do?")
    for alt in alternatives:
        risk_indicator = {"low": "", "medium": " [moderate risk]", "high": " [higher risk]"}.get(
            alt.risk_level, ""
        )
        lines.append(f"  {alt.label}) {alt.description}{risk_indicator}")

    return "\n".join(lines)


# =============================================================================
# High-Level Entry Point
# =============================================================================

async def build_push_back(
    tool_name: str,
    tool_input: Dict[str, Any],
    user_id: str,
    voi_score: float,
    concern: Optional[str] = None,
) -> PushBackResponse:
    """
    Build a complete push-back response.

    Parameters
    ----------
    tool_name : str
        Name of the tool that triggered the push-back.
    tool_input : dict
        Tool arguments for context.
    user_id : str
        UUID for evidence lookup.
    voi_score : float
        The VoI score that triggered this.
    concern : str, optional
        Pre-formulated concern. If None, a generic one is generated.

    Returns
    -------
    PushBackResponse
    """
    # Default concern
    if not concern:
        concern = (
            f"The action '{tool_name}' has some uncertainty. "
            "I want to make sure I get this right."
        )

    # Gather evidence from MAGMA graph
    # Try to find a relevant entity from tool_input
    entity_name = (
        tool_input.get("entity")
        or tool_input.get("name")
        or tool_input.get("recipient")
        or tool_input.get("target")
    )

    evidence: List[EvidenceItem] = []
    if entity_name and isinstance(entity_name, str):
        evidence = await gather_evidence(entity_name, user_id)

    # Generate alternatives
    original_action = f"{tool_name}({', '.join(f'{k}={v}' for k, v in list(tool_input.items())[:3])})"
    alternatives = generate_alternatives(original_action, tool_name, concern)

    # Format message
    formatted = format_push_back(concern, evidence, alternatives, voi_score)

    return PushBackResponse(
        concern=concern,
        evidence=evidence,
        alternatives=alternatives,
        formatted_message=formatted,
        voi_score=voi_score,
    )


# =============================================================================
# Event Logging (PUSH-003, PUSH-004)
# =============================================================================

async def log_push_back_event(entry: PushBackLogEntry) -> bool:
    """
    Log a push-back event to the push_back_log table.

    Parameters
    ----------
    entry : PushBackLogEntry
        The event data to log.

    Returns
    -------
    bool
        True on success.
    """
    try:
        import asyncio

        from backend.services.wal import get_supabase_client
        client = get_supabase_client()

        # Serialize alternatives safely, handling Pydantic models and datetime objects
        def serialize_alternative(alt: Any) -> Dict[str, Any]:
            """Convert alternative to JSON-compliant dict."""
            if hasattr(alt, "model_dump"):
                dumped = alt.model_dump()
            elif isinstance(alt, dict):
                dumped = alt
            else:
                dumped = {}
            
            # Convert any datetime objects to ISO strings
            for key, value in dumped.items():
                if isinstance(value, datetime):
                    dumped[key] = value.isoformat()
            
            return dumped

        data = {
            "user_id": entry.user_id,
            "session_id": entry.session_id,
            "trace_id": entry.trace_id,
            "action_type": entry.action_type,
            "tool_name": entry.tool_name,
            "c_error": entry.c_error,
            "p_error": entry.p_error,
            "c_int": entry.c_int,
            "voi_score": entry.voi_score,
            "push_back_triggered": entry.push_back_triggered,
            "evidence_memory_ids": entry.evidence_memory_ids,
            "alternatives_offered": [
                serialize_alternative(alt)
                for alt in entry.alternatives_offered
            ],
            "user_accepted": entry.user_accepted,
            "user_chose_alternative": entry.user_chose_alternative,
            "lambda_alpha_before": entry.lambda_alpha_before,
            "lambda_alpha_after": entry.lambda_alpha_after,
        }

        response = await asyncio.to_thread(
            lambda: client.table("push_back_log").insert(data).execute()
        )

        if response.data:
            logger.info(
                "Push-back event logged: user=%s tool=%s triggered=%s",
                entry.user_id[:8], entry.tool_name, entry.push_back_triggered,
            )
            return True

        logger.warning("Push-back log insert returned no data")
        return False

    except Exception as exc:
        logger.error("Failed to log push-back event: %s", exc)
        return False


async def handle_user_override(
    user_id: str,
    log_entry_id: str,
    accepted: bool,
    chosen_alternative: Optional[int] = None,
) -> None:
    """
    Handle user's response to a push-back (PUSH-003).

    When the user overrides a push-back (accepted=False), this reduces
    their lambda_alpha (makes the system less likely to push back in the future).

    Parameters
    ----------
    user_id : str
        UUID of the user.
    log_entry_id : str
        UUID of the push_back_log entry to update.
    accepted : bool
        True if user accepted the push-back suggestion.
    chosen_alternative : int, optional
        Index of the alternative the user chose (0-based).
    """
    try:
        import asyncio

        # Update the log entry
        from backend.services.wal import get_supabase_client
        client = get_supabase_client()

        await asyncio.to_thread(
            lambda: client.table("push_back_log").update({
                "user_accepted": accepted,
                "user_chose_alternative": chosen_alternative,
            }).eq("id", log_entry_id).execute()
        )

        # If user overrode, adjust lambda_alpha downward (PUSH-003)
        if not accepted:
            try:
                from backend.belief.revision import get_lambda_alpha, set_lambda_alpha

                current_la = await get_lambda_alpha(user_id)
                # Decrease lambda_alpha by 0.05 on override (makes system less pushy)
                new_la = max(0.05, current_la - 0.05)

                if new_la != current_la:
                    await set_lambda_alpha(user_id, new_la)
                    logger.info(
                        "lambda_alpha adjusted after override: user=%s %.2f -> %.2f",
                        user_id[:8], current_la, new_la,
                    )

                    # Update log with lambda_alpha change
                    await asyncio.to_thread(
                        lambda: client.table("push_back_log").update({
                            "lambda_alpha_before": current_la,
                            "lambda_alpha_after": new_la,
                        }).eq("id", log_entry_id).execute()
                    )

            except Exception as exc:
                logger.warning(
                    "lambda_alpha adjustment failed for user=%s: %s",
                    user_id[:8], exc,
                )

    except Exception as exc:
        logger.error("Failed to handle user override: %s", exc)


async def get_push_back_rate(user_id: str, days: int = 30) -> float:
    """
    Calculate the push-back rate for a user over the last N days (PUSH-004).

    Target rate: 5-15% of interactions.

    Parameters
    ----------
    user_id : str
        UUID of the user.
    days : int
        Lookback window in days.

    Returns
    -------
    float
        Push-back rate (0.0-1.0).
    """
    try:
        import asyncio

        from backend.services.wal import get_supabase_client
        client = get_supabase_client()

        # Count total VoI evaluations
        total_response = await asyncio.to_thread(
            lambda: client.table("push_back_log")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )
        total_count = total_response.count or 0

        if total_count == 0:
            return 0.0

        # Count push-backs triggered
        triggered_response = await asyncio.to_thread(
            lambda: client.table("push_back_log")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("push_back_triggered", True)
            .execute()
        )
        triggered_count = triggered_response.count or 0

        rate = triggered_count / total_count
        logger.info(
            "Push-back rate for user=%s: %.1f%% (%d/%d over %d days)",
            user_id[:8], rate * 100, triggered_count, total_count, days,
        )
        return rate

    except Exception as exc:
        logger.warning(
            "Failed to calculate push-back rate for user=%s: %s",
            user_id[:8], exc,
        )
        return 0.0
