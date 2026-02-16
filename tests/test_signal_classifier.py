"""
Tests for Implicit Signal Classifier
======================================

Unit tests for the pattern-based signal classification service.
All classifiers are synchronous -- no mocking needed for these pure functions.

Run with: pytest tests/test_signal_classifier.py -v
"""

import pytest

from backend.services.signal_classifier import (
    classify_frustration,
    classify_gratitude,
    classify_repetition,
    classify_signals,
)


# =============================================================================
# Gratitude Classifier
# =============================================================================

class TestGratitudeClassifier:
    """Tests for gratitude signal detection."""

    def test_thank_you(self):
        """Simple 'thank you' should be detected."""
        assert classify_gratitude("Thank you!") is True

    def test_thanks_lowercase(self):
        """Case-insensitive matching."""
        assert classify_gratitude("thanks so much") is True

    def test_thx(self):
        """Internet shorthand for thanks."""
        assert classify_gratitude("thx!") is True

    def test_ty(self):
        """Shorthand 'ty'."""
        assert classify_gratitude("ty") is True

    def test_perfect(self):
        """'Perfect' as gratitude marker."""
        assert classify_gratitude("Perfect, exactly what I needed") is True

    def test_awesome(self):
        """'Awesome' as gratitude marker."""
        assert classify_gratitude("Awesome, that works great") is True

    def test_great_job(self):
        """'Great job' as gratitude marker."""
        assert classify_gratitude("Great job on that report") is True

    def test_no_thanks(self):
        """'No thanks' should NOT be gratitude."""
        assert classify_gratitude("No thanks, I don't need that") is False

    def test_thanks_but(self):
        """'Thanks but' is a negation, not gratitude."""
        assert classify_gratitude("Thanks but that's not right") is False

    def test_neutral_message(self):
        """Neutral message without gratitude signals."""
        assert classify_gratitude("Can you also check the weather?") is False

    def test_empty_message(self):
        """Empty message should return False."""
        assert classify_gratitude("") is False

    def test_question_with_thanks(self):
        """'Thank' embedded in a longer phrase should still match."""
        assert classify_gratitude("I want to thank you for your help") is True

    def test_love_it(self):
        """'Love it' as gratitude."""
        assert classify_gratitude("Love it, exactly right") is True


# =============================================================================
# Repetition Classifier
# =============================================================================

class TestRepetitionClassifier:
    """Tests for repetition/rephrasing detection."""

    def test_identical_messages(self):
        """Identical messages should be repetition."""
        assert classify_repetition("check my calendar", "check my calendar") is True

    def test_rephrased_question(self):
        """Rephrased question with shared content words."""
        assert classify_repetition(
            "what's the weather today",
            "tell me today's weather"
        ) is True

    def test_different_questions(self):
        """Completely different questions should NOT be repetition."""
        assert classify_repetition(
            "what's for dinner",
            "what's the weather"
        ) is False

    def test_similar_but_different(self):
        """Similar topic but different enough to not be repetition."""
        assert classify_repetition(
            "send an email to John",
            "what emails did John send me"
        ) is False

    def test_empty_messages(self):
        """Empty messages should not be repetition."""
        assert classify_repetition("", "") is False

    def test_stopwords_only(self):
        """Messages with only stopwords should not be repetition."""
        assert classify_repetition("the is a", "was are the") is False

    def test_one_empty(self):
        """One empty message should not be repetition."""
        assert classify_repetition("check the weather", "") is False


# =============================================================================
# Frustration Classifier
# =============================================================================

class TestFrustrationClassifier:
    """Tests for frustration signal detection."""

    def test_thats_wrong(self):
        """Explicit 'that's wrong'."""
        assert classify_frustration("That's wrong, try again") is True

    def test_try_again(self):
        """'Try again' as frustration."""
        assert classify_frustration("Try again please") is True

    def test_not_what_i_asked(self):
        """'Not what I asked' as frustration."""
        assert classify_frustration("That's not what I asked for") is True

    def test_ugh(self):
        """Exclamation of frustration."""
        assert classify_frustration("Ugh, that's not right") is True

    def test_wtf(self):
        """Strong frustration signal."""
        assert classify_frustration("WTF is this?") is True

    def test_polite_correction(self):
        """Polite correction should NOT be frustration."""
        assert classify_frustration("Actually I meant next Tuesday") is False

    def test_neutral_followup(self):
        """Neutral follow-up should NOT be frustration."""
        assert classify_frustration("Okay, now send it to John") is False

    def test_question(self):
        """Regular question should NOT be frustration."""
        assert classify_frustration("Can you check my email?") is False

    def test_empty_message(self):
        """Empty message should not be frustration."""
        assert classify_frustration("") is False

    def test_you_misunderstood(self):
        """'You misunderstood' as frustration."""
        assert classify_frustration("You misunderstood what I meant") is True

    def test_still_wrong(self):
        """'Still wrong' as frustration."""
        assert classify_frustration("Still wrong, that's not the file") is True


# =============================================================================
# Orchestrator
# =============================================================================

class TestClassifySignals:
    """Tests for the signal classification orchestrator."""

    def test_all_positive(self):
        """Gratitude message with no repetition or frustration."""
        result = classify_signals(
            current_message="Thank you, that's perfect!",
            previous_user_message="What's the weather?",
        )
        assert result["gratitude"] is True
        assert result["frustration"] is False
        assert result["repetition"] is False

    def test_frustration_with_repetition(self):
        """Frustration + repetition when user rephrases same request."""
        result = classify_signals(
            current_message="That's wrong, check the weather again",
            previous_user_message="check the weather please",
        )
        assert result["frustration"] is True
        assert result["repetition"] is True
        assert result["gratitude"] is False

    def test_no_previous_message(self):
        """Without previous message, repetition should be False."""
        result = classify_signals(
            current_message="Hello there!",
        )
        assert result["repetition"] is False
        assert result["gratitude"] is False
        assert result["frustration"] is False

    def test_skill_version_passthrough(self):
        """skill_version_id should be passed through."""
        result = classify_signals(
            current_message="Thanks!",
            agent_used_skill="version-abc-123",
        )
        assert result["skill_version_id"] == "version-abc-123"
        assert result["gratitude"] is True

    def test_neutral_message(self):
        """Completely neutral message should have all False signals."""
        result = classify_signals(
            current_message="Now schedule a meeting for Tuesday at 3pm",
            previous_user_message="What time is the meeting?",
        )
        assert result["gratitude"] is False
        assert result["frustration"] is False
        assert result["repetition"] is False
