"""
Tests for backend.services.salience
====================================

Covers every public function and Pydantic model in the salience module:
    - compute_recency
    - compute_frequency
    - compute_emotional_weight  (stub)
    - compute_causal_centrality (stub)
    - SalienceWeights validation
    - SalienceComponents / SalienceResult construction
    - calculate_salience (end-to-end composite score)
"""

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.services.salience import (
    DECAY_LAMBDA,
    DEFAULT_MAX_ACCESS_COUNT,
    SalienceComponents,
    SalienceResult,
    SalienceWeights,
    calculate_salience,
    compute_causal_centrality,
    compute_emotional_weight,
    compute_frequency,
    compute_recency,
)
from lib.db.models import Memory


# =========================================================================
# Helpers
# =========================================================================

def _make_memory(
    last_accessed_at: Optional[datetime] = None,
    access_count: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
    entity_links: Optional[List[UUID]] = None,
    memory_id: Optional[UUID] = None,
) -> Memory:
    """Build a minimal Memory instance for testing."""
    return Memory(
        id=memory_id,
        content="test memory",
        last_accessed_at=last_accessed_at,
        access_count=access_count,
        metadata=metadata or {},
        entity_links=entity_links or [],
    )


# =========================================================================
# compute_recency
# =========================================================================

class TestComputeRecency:
    """Tests for the recency exponential-decay scorer."""

    def test_none_last_accessed_returns_zero(self) -> None:
        assert compute_recency(None) == 0.0

    def test_just_accessed_returns_one(self) -> None:
        now = datetime.now(timezone.utc)
        score = compute_recency(now, now=now)
        assert math.isclose(score, 1.0, abs_tol=1e-6)

    def test_one_day_ago(self) -> None:
        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        score = compute_recency(one_day_ago, now=now)
        expected = math.exp(-DECAY_LAMBDA * 1.0)
        assert math.isclose(score, expected, abs_tol=1e-5)

    def test_seven_days_half_life(self) -> None:
        """At ~6.93 days the score should be ~0.5 (half-life)."""
        now = datetime.now(timezone.utc)
        half_life_days = math.log(2) / DECAY_LAMBDA
        past = now - timedelta(days=half_life_days)
        score = compute_recency(past, now=now)
        assert math.isclose(score, 0.5, abs_tol=0.01)

    def test_thirty_days_very_low(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=30)
        score = compute_recency(past, now=now)
        assert score < 0.1

    def test_future_access_clamped(self) -> None:
        """If last_accessed_at is in the future, days_since is clamped to 0."""
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=5)
        score = compute_recency(future, now=now)
        assert math.isclose(score, 1.0, abs_tol=1e-6)

    def test_naive_datetime_treated_as_utc(self) -> None:
        """Naive datetimes should be treated as UTC without raising."""
        naive_now = datetime(2025, 6, 1, 12, 0, 0)
        naive_past = datetime(2025, 5, 31, 12, 0, 0)
        score = compute_recency(naive_past, now=naive_now)
        expected = math.exp(-DECAY_LAMBDA * 1.0)
        assert math.isclose(score, expected, abs_tol=1e-5)

    def test_custom_decay_lambda(self) -> None:
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=10)
        score = compute_recency(past, now=now, decay_lambda=0.5)
        expected = math.exp(-0.5 * 10)
        assert math.isclose(score, expected, abs_tol=1e-5)

    def test_return_between_zero_and_one(self) -> None:
        now = datetime.now(timezone.utc)
        for days in [0, 0.5, 1, 3, 7, 14, 30, 100, 365]:
            past = now - timedelta(days=days)
            score = compute_recency(past, now=now)
            assert 0.0 <= score <= 1.0, f"Out of range for {days} days: {score}"


# =========================================================================
# compute_frequency
# =========================================================================

class TestComputeFrequency:
    """Tests for the log-normalised frequency scorer."""

    def test_zero_access_count(self) -> None:
        assert compute_frequency(0) == 0.0

    def test_negative_access_count(self) -> None:
        assert compute_frequency(-5) == 0.0

    def test_max_access_equals_count(self) -> None:
        """When count == max, score should be 1.0."""
        score = compute_frequency(10, max_access_count=10)
        assert math.isclose(score, 1.0, abs_tol=1e-5)

    def test_count_exceeds_max(self) -> None:
        """When count > max the score can exceed 1.0 before clamping."""
        score = compute_frequency(20, max_access_count=10)
        assert score == 1.0  # clamped

    def test_half_of_max(self) -> None:
        score = compute_frequency(5, max_access_count=10)
        expected = math.log(1 + 5) / math.log(1 + 10)
        assert math.isclose(score, expected, abs_tol=1e-5)

    def test_single_access(self) -> None:
        score = compute_frequency(1, max_access_count=10)
        expected = math.log(2) / math.log(11)
        assert math.isclose(score, expected, abs_tol=1e-5)

    def test_max_access_count_zero_or_negative_safe(self) -> None:
        """max_access_count < 1 should be clamped to 1, not crash."""
        score = compute_frequency(5, max_access_count=0)
        assert 0.0 <= score <= 1.0

    def test_default_max_access_count(self) -> None:
        score = compute_frequency(5)
        expected = math.log(6) / math.log(1 + DEFAULT_MAX_ACCESS_COUNT)
        assert math.isclose(score, expected, abs_tol=1e-5)

    def test_return_between_zero_and_one(self) -> None:
        for count in range(0, 50):
            score = compute_frequency(count, max_access_count=20)
            assert 0.0 <= score <= 1.0, f"Out of range for count={count}: {score}"


# =========================================================================
# Stubs: emotional weight & causal centrality
# =========================================================================

class TestComputeEmotionalWeight:
    """Tests for the keyword-based emotional weight scorer."""

    def test_no_metadata_returns_neutral(self) -> None:
        assert compute_emotional_weight() == 0.3

    def test_none_metadata_returns_neutral(self) -> None:
        assert compute_emotional_weight(None) == 0.3

    def test_no_content_returns_neutral(self) -> None:
        assert compute_emotional_weight({"key": "val"}) == 0.3

    def test_cached_emotional_valence_returned(self) -> None:
        result = compute_emotional_weight({"emotional_valence": 0.82})
        assert result == 0.82

    def test_single_emotion_keyword(self) -> None:
        result = compute_emotional_weight({"content": "I am so excited about this"})
        assert result >= 0.5

    def test_strong_emotion_keyword(self) -> None:
        result = compute_emotional_weight({"content": "There was a death in the family"})
        assert result >= 0.7

    def test_no_emotion_keywords(self) -> None:
        result = compute_emotional_weight({"content": "The meeting is at 3pm"})
        assert result == 0.3


class TestComputeCausalCentrality:
    """Tests for the graph degree-based causal centrality scorer."""

    def test_no_args_returns_low(self) -> None:
        assert compute_causal_centrality() == 0.1

    def test_none_args_returns_low(self) -> None:
        assert compute_causal_centrality(None, None) == 0.1

    def test_empty_entity_links_returns_low(self) -> None:
        assert compute_causal_centrality(None, []) == 0.1


# =========================================================================
# SalienceWeights Pydantic model
# =========================================================================

class TestSalienceWeights:
    """Tests for weight validation."""

    def test_defaults_sum_to_one(self) -> None:
        w = SalienceWeights()
        total = w.w_recency + w.w_frequency + w.w_emotional + w.w_causal
        assert math.isclose(total, 1.0)

    def test_custom_weights_valid(self) -> None:
        w = SalienceWeights(
            w_recency=0.1, w_frequency=0.3,
            w_emotional=0.4, w_causal=0.2,
        )
        assert w.w_recency == 0.1

    def test_weights_not_summing_to_one_raises(self) -> None:
        with pytest.raises(ValidationError, match="must sum to 1.0"):
            SalienceWeights(
                w_recency=0.5, w_frequency=0.5,
                w_emotional=0.5, w_causal=0.5,
            )

    def test_negative_weight_raises(self) -> None:
        with pytest.raises(ValidationError):
            SalienceWeights(
                w_recency=-0.1, w_frequency=0.4,
                w_emotional=0.4, w_causal=0.3,
            )

    def test_weight_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            SalienceWeights(
                w_recency=1.5, w_frequency=0.0,
                w_emotional=0.0, w_causal=-0.5,
            )

    def test_all_weight_on_recency(self) -> None:
        w = SalienceWeights(
            w_recency=1.0, w_frequency=0.0,
            w_emotional=0.0, w_causal=0.0,
        )
        assert w.w_recency == 1.0


# =========================================================================
# SalienceComponents & SalienceResult
# =========================================================================

class TestSalienceModels:
    """Tests for result model construction."""

    def test_components_valid(self) -> None:
        c = SalienceComponents(
            recency=0.9, frequency=0.5,
            emotional_weight=0.5, causal_centrality=0.3,
        )
        assert c.recency == 0.9

    def test_components_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            SalienceComponents(
                recency=1.5, frequency=0.5,
                emotional_weight=0.5, causal_centrality=0.3,
            )

    def test_result_construction(self) -> None:
        c = SalienceComponents(
            recency=0.9, frequency=0.5,
            emotional_weight=0.5, causal_centrality=0.3,
        )
        w = SalienceWeights()
        r = SalienceResult(
            memory_id="abc-123",
            score=0.65,
            components=c,
            weights=w,
        )
        assert r.score == 0.65
        assert r.memory_id == "abc-123"

    def test_result_none_memory_id(self) -> None:
        c = SalienceComponents(
            recency=0.5, frequency=0.5,
            emotional_weight=0.5, causal_centrality=0.3,
        )
        r = SalienceResult(score=0.5, components=c, weights=SalienceWeights())
        assert r.memory_id is None


# =========================================================================
# calculate_salience (end-to-end)
# =========================================================================

class TestCalculateSalience:
    """End-to-end tests for the composite salience calculator."""

    def test_just_accessed_high_frequency(self) -> None:
        """Recently accessed + high frequency = high salience."""
        now = datetime.now(timezone.utc)
        mem = _make_memory(last_accessed_at=now, access_count=10)
        result = calculate_salience(mem, max_access_count=10, now=now)
        # recency~1.0, frequency~1.0, emotional=0.3 (no content), causal=0.1 (no links)
        # S = 0.4*1 + 0.2*1 + 0.2*0.3 + 0.2*0.1 = 0.68
        assert math.isclose(result.score, 0.68, abs_tol=0.02)

    def test_never_accessed_zero_count(self) -> None:
        """Never accessed + zero count = low salience (only baseline contributes)."""
        mem = _make_memory(last_accessed_at=None, access_count=0)
        result = calculate_salience(mem)
        # recency=0, frequency=0, emotional=0.3 (no content), causal=0.1 (no links)
        # S = 0.4*0 + 0.2*0 + 0.2*0.3 + 0.2*0.1 = 0.08
        assert math.isclose(result.score, 0.08, abs_tol=0.02)

    def test_old_memory_high_frequency(self) -> None:
        """Old but frequently accessed memory."""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=30)
        mem = _make_memory(last_accessed_at=past, access_count=10)
        result = calculate_salience(mem, max_access_count=10, now=now)
        # recency very low, frequency=1.0
        assert result.score < 0.6
        assert result.components.frequency == 1.0

    def test_custom_weights(self) -> None:
        """Custom weights change the result."""
        now = datetime.now(timezone.utc)
        mem = _make_memory(last_accessed_at=now, access_count=5)
        w = SalienceWeights(
            w_recency=1.0, w_frequency=0.0,
            w_emotional=0.0, w_causal=0.0,
        )
        result = calculate_salience(mem, weights=w, now=now)
        # Only recency matters, and it's ~1.0
        assert math.isclose(result.score, 1.0, abs_tol=0.01)

    def test_memory_id_string_in_result(self) -> None:
        mid = uuid.uuid4()
        mem = _make_memory(memory_id=mid)
        result = calculate_salience(mem)
        assert result.memory_id == str(mid)

    def test_memory_id_none_in_result(self) -> None:
        mem = _make_memory(memory_id=None)
        result = calculate_salience(mem)
        assert result.memory_id is None

    def test_components_populated(self) -> None:
        now = datetime.now(timezone.utc)
        mem = _make_memory(last_accessed_at=now, access_count=3)
        result = calculate_salience(mem, now=now)
        c = result.components
        assert 0.0 <= c.recency <= 1.0
        assert 0.0 <= c.frequency <= 1.0
        assert c.emotional_weight == 0.3  # no content in metadata
        assert c.causal_centrality == 0.1  # no entity_links

    def test_weights_echoed_in_result(self) -> None:
        w = SalienceWeights(
            w_recency=0.1, w_frequency=0.3,
            w_emotional=0.3, w_causal=0.3,
        )
        mem = _make_memory()
        result = calculate_salience(mem, weights=w)
        assert result.weights == w

    def test_default_weights_used_when_none(self) -> None:
        mem = _make_memory()
        result = calculate_salience(mem, weights=None)
        assert result.weights == SalienceWeights()

    def test_score_clamped_to_unit_interval(self) -> None:
        """Score should always be in [0, 1] regardless of inputs."""
        now = datetime.now(timezone.utc)
        for days in [0, 1, 7, 30, 365]:
            for count in [0, 1, 5, 10, 100]:
                past = now - timedelta(days=days) if days > 0 else now
                mem = _make_memory(last_accessed_at=past, access_count=count)
                result = calculate_salience(mem, now=now)
                assert 0.0 <= result.score <= 1.0, (
                    f"Score {result.score} out of range for "
                    f"days={days}, count={count}"
                )

    def test_max_access_count_forwarded(self) -> None:
        """Passing a different max_access_count changes frequency component."""
        now = datetime.now(timezone.utc)
        mem = _make_memory(last_accessed_at=now, access_count=5)
        r1 = calculate_salience(mem, max_access_count=5, now=now)
        r2 = calculate_salience(mem, max_access_count=100, now=now)
        assert r1.components.frequency > r2.components.frequency
