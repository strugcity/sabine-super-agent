"""
Implicit Signal Classifier
============================

Classifies user messages for implicit reward/punishment signals
after an agent response. These signals feed into the skill
effectiveness scoring system.

PRD Requirements: TRAIN-001, TRAIN-004

Note: This uses keyword/pattern matching, NOT LLM calls.
TRAIN-004 explicitly says "no direct model fine-tuning" —
we optimize retrieval and prompts, not weights.
"""

import logging
import re
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

# ---- Stopwords for Jaccard similarity ----
STOPWORDS: Set[str] = {
    "the", "a", "an", "is", "was", "are", "were", "do", "does", "did",
    "can", "could", "would", "should", "please", "just", "me", "my", "i",
    "to", "for", "of", "in", "on", "at", "and", "or", "but", "not",
    "it", "this", "that", "with", "be", "have", "has", "had",
}

# ---- Gratitude patterns ----
GRATITUDE_PATTERNS: list[str] = [
    "thank", "thanks", "thx", "ty",
    "perfect", "great job", "awesome",
    "exactly what i needed", "love it", "nice work",
    "well done", "excellent", "amazing",
    "that's great", "that's perfect",
    "you're the best", "appreciate it",
]

# Negation prefixes that cancel gratitude
GRATITUDE_NEGATIONS: list[str] = [
    "no thanks", "no thank", "thanks but", "thank you but",
    "thanks however", "thanks, but", "thanks, however",
]

# ---- Frustration patterns ----
FRUSTRATION_PATTERNS: list[str] = [
    "that's wrong", "that is wrong",
    "no that's not", "no that is not",
    "you misunderstood", "you misunderstand",
    "try again", "not what i asked",
    "still wrong", "wrong again",
    "ugh", "come on", "wtf", "seriously?",
    "that's not right", "that is not right",
    "that's incorrect", "that is incorrect",
    "you got it wrong", "completely wrong",
    "not even close", "way off",
]


def classify_gratitude(message: str) -> bool:
    """
    Classify whether a message expresses gratitude.

    Returns True if the message is a "thank you" or equivalent.
    Handles negation prefixes like "no thanks" or "thanks but".

    Parameters
    ----------
    message : str
        The user's message text.

    Returns
    -------
    bool
        True if gratitude detected, False otherwise.
    """
    lower = message.lower().strip()

    # Check for negation prefixes first
    for neg in GRATITUDE_NEGATIONS:
        if lower.startswith(neg):
            return False

    # Check for gratitude patterns
    for pattern in GRATITUDE_PATTERNS:
        if pattern in lower:
            return True

    return False


def classify_repetition(current_message: str, previous_message: str) -> bool:
    """
    Classify whether the current message is a rephrased version of the previous.

    Uses Jaccard similarity on word sets (lowercase, stripped of stopwords).
    Threshold: > 0.5 similarity = repetition.

    Parameters
    ----------
    current_message : str
        The user's current message.
    previous_message : str
        The user's previous message.

    Returns
    -------
    bool
        True if messages appear to be repetitions.
    """
    def _tokenize(text: str) -> Set[str]:
        """Tokenize and remove stopwords."""
        words = set(re.findall(r'\w+', text.lower()))
        return words - STOPWORDS

    current_words = _tokenize(current_message)
    previous_words = _tokenize(previous_message)

    if not current_words and not previous_words:
        return False
    if not current_words or not previous_words:
        return False

    intersection = current_words & previous_words
    union = current_words | previous_words

    if not union:
        return False

    similarity = len(intersection) / len(union)
    return similarity > 0.5


def classify_frustration(message: str) -> bool:
    """
    Classify whether a message expresses frustration.

    Looks for explicit frustration signals. Does NOT flag polite
    corrections like "actually I meant...".

    Parameters
    ----------
    message : str
        The user's message text.

    Returns
    -------
    bool
        True if frustration detected, False otherwise.
    """
    lower = message.lower().strip()

    for pattern in FRUSTRATION_PATTERNS:
        if pattern in lower:
            return True

    return False


def classify_signals(
    current_message: str,
    previous_user_message: Optional[str] = None,
    agent_used_skill: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Orchestrator: classify all implicit signals in a user message.

    Parameters
    ----------
    current_message : str
        The user's current message.
    previous_user_message : str, optional
        The user's previous message (for repetition detection).
    agent_used_skill : str, optional
        The skill_version_id if a promoted skill was used.

    Returns
    -------
    dict
        Signal classification results with keys:
        - gratitude: bool
        - repetition: bool (only if previous_user_message provided)
        - frustration: bool
        - skill_version_id: str or None
    """
    result: Dict[str, Any] = {
        "gratitude": classify_gratitude(current_message),
        "frustration": classify_frustration(current_message),
        "skill_version_id": agent_used_skill,
    }

    if previous_user_message is not None:
        result["repetition"] = classify_repetition(current_message, previous_user_message)
    else:
        result["repetition"] = False

    logger.debug(
        "Signal classification: gratitude=%s, repetition=%s, frustration=%s",
        result["gratitude"], result["repetition"], result["frustration"],
    )

    return result
