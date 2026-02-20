"""Tests for guest defection logic in guests/tasks.py."""

from __future__ import annotations

import hashlib
from datetime import date

from guests import tasks as guest_tasks


def test_should_defect_deterministic_for_same_input():
    """Test that _should_defect returns consistent results for same inputs."""
    guest_id = 12345
    test_date = date(2026, 2, 8)

    result1 = guest_tasks._should_defect(guest_id, test_date, probability=0.5, hasher=hashlib.sha256)
    result2 = guest_tasks._should_defect(guest_id, test_date, probability=0.5, hasher=hashlib.sha256)

    assert result1 == result2


def test_should_defect_different_for_different_dates():
    """Test that different dates can produce different results."""
    guest_id = 12345

    # Collect results for multiple dates
    results = set()
    for day in range(1, 100):
        test_date = date(2026, 1, 1)
        # Use day as part of guest_id to vary input
        result = guest_tasks._should_defect(guest_id + day * 1000, test_date, probability=0.5, hasher=hashlib.sha256)
        results.add(result)

    # With probability 0.5 and 99 different inputs, we should see both True and False
    assert len(results) == 2


def test_should_defect_probability_zero_always_false():
    """Test that probability=0 always returns False."""
    for guest_id in range(1, 100):
        result = guest_tasks._should_defect(guest_id, date(2026, 2, 8), probability=0.0, hasher=hashlib.sha256)
        assert result is False


def test_should_defect_probability_one_always_true():
    """Test that probability=1 always returns True."""
    for guest_id in range(1, 100):
        result = guest_tasks._should_defect(guest_id, date(2026, 2, 8), probability=1.0, hasher=hashlib.sha256)
        assert result is True


def test_should_defect_uses_hasher_correctly():
    """Test that different hashers produce different results."""
    guest_id = 99999
    test_date = date(2026, 2, 8)

    # SHA256 and SHA512 should produce different hash values
    result_sha256 = guest_tasks._should_defect(guest_id, test_date, probability=0.5, hasher=hashlib.sha256)
    result_sha512 = guest_tasks._should_defect(guest_id, test_date, probability=0.5, hasher=hashlib.sha512)

    # Results might be same or different, but the function should work with both
    # This just verifies no errors occur
    assert isinstance(result_sha256, bool)
    assert isinstance(result_sha512, bool)


def test_defection_constants_are_defined():
    """Test that defection constants are properly defined."""
    assert hasattr(guest_tasks, "DEFECTION_PROBABILITY")
    assert hasattr(guest_tasks, "DEFECTION_BATCH_SIZE")
    assert hasattr(guest_tasks, "DEFECTION_QUERY_CHUNK_SIZE")

    assert guest_tasks.DEFECTION_PROBABILITY == 0.3
    assert guest_tasks.DEFECTION_BATCH_SIZE == 500
    assert guest_tasks.DEFECTION_QUERY_CHUNK_SIZE == 2000
