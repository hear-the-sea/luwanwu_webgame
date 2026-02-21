"""Tests for manor local fallback cache cleanup logic."""

from __future__ import annotations

import gameplay.services.manor.core as manor_service


def test_cleanup_local_fallback_cache_removes_stale_entries():
    """Test that stale entries are removed during cleanup."""
    manor_service._LOCAL_REFRESH_FALLBACK.clear()

    now = 1000.0
    stale_threshold = 60.0

    # Add stale entries (older than threshold)
    manor_service._LOCAL_REFRESH_FALLBACK[1] = now - 100  # stale
    manor_service._LOCAL_REFRESH_FALLBACK[2] = now - 80  # stale
    manor_service._LOCAL_REFRESH_FALLBACK[3] = now - 30  # fresh

    manor_service._cleanup_local_fallback_cache(now, stale_threshold)

    # Stale entries should be removed
    assert 1 not in manor_service._LOCAL_REFRESH_FALLBACK
    assert 2 not in manor_service._LOCAL_REFRESH_FALLBACK
    # Fresh entry should remain
    assert 3 in manor_service._LOCAL_REFRESH_FALLBACK

    manor_service._LOCAL_REFRESH_FALLBACK.clear()


def test_cleanup_local_fallback_cache_lru_eviction_when_still_oversized():
    """Test LRU eviction when cache is still over max size after stale cleanup."""
    manor_service._LOCAL_REFRESH_FALLBACK.clear()

    original_max = manor_service._LOCAL_REFRESH_FALLBACK_MAX_SIZE
    original_evict = manor_service._LOCAL_REFRESH_FALLBACK_EVICT_COUNT

    try:
        # Temporarily set smaller limits for testing
        manor_service._LOCAL_REFRESH_FALLBACK_MAX_SIZE = 5
        manor_service._LOCAL_REFRESH_FALLBACK_EVICT_COUNT = 2

        now = 1000.0
        stale_threshold = 60.0

        # Add 8 fresh entries (all within threshold, so none are stale)
        for i in range(8):
            manor_service._LOCAL_REFRESH_FALLBACK[i] = now - (50 - i)  # all fresh

        assert len(manor_service._LOCAL_REFRESH_FALLBACK) == 8

        manor_service._cleanup_local_fallback_cache(now, stale_threshold)

        # Should have evicted the 2 oldest entries (0 and 1)
        assert 0 not in manor_service._LOCAL_REFRESH_FALLBACK
        assert 1 not in manor_service._LOCAL_REFRESH_FALLBACK
        # Newer entries should remain
        assert 7 in manor_service._LOCAL_REFRESH_FALLBACK
        assert 6 in manor_service._LOCAL_REFRESH_FALLBACK

    finally:
        manor_service._LOCAL_REFRESH_FALLBACK_MAX_SIZE = original_max
        manor_service._LOCAL_REFRESH_FALLBACK_EVICT_COUNT = original_evict
        manor_service._LOCAL_REFRESH_FALLBACK.clear()


def test_should_skip_refresh_returns_false_for_invalid_inputs():
    """Test that invalid inputs return False (allow refresh)."""
    manor_service._LOCAL_REFRESH_FALLBACK.clear()

    # Invalid manor_id
    assert manor_service._should_skip_refresh_by_local_fallback(0, 5) is False
    assert manor_service._should_skip_refresh_by_local_fallback(-1, 5) is False

    # Invalid min_interval
    assert manor_service._should_skip_refresh_by_local_fallback(1, 0) is False
    assert manor_service._should_skip_refresh_by_local_fallback(1, -1) is False

    manor_service._LOCAL_REFRESH_FALLBACK.clear()


def test_should_skip_refresh_throttles_within_interval(monkeypatch):
    """Test that refresh is throttled within the interval."""
    manor_service._LOCAL_REFRESH_FALLBACK.clear()

    monotonic_values = iter([100.0, 102.0, 103.0])
    monkeypatch.setattr(manor_service.time, "monotonic", lambda: next(monotonic_values))

    # First call: should allow (returns False)
    result1 = manor_service._should_skip_refresh_by_local_fallback(999, 5)
    assert result1 is False

    # Second call at t=102 (2s later): should skip (within 5s interval)
    result2 = manor_service._should_skip_refresh_by_local_fallback(999, 5)
    assert result2 is True

    # Third call at t=103 (3s later): should still skip
    result3 = manor_service._should_skip_refresh_by_local_fallback(999, 5)
    assert result3 is True

    manor_service._LOCAL_REFRESH_FALLBACK.clear()


def test_cleanup_respects_batch_limit():
    """Test that cleanup respects the batch limit for stale entries."""
    manor_service._LOCAL_REFRESH_FALLBACK.clear()

    original_batch = manor_service._LOCAL_REFRESH_FALLBACK_CLEANUP_BATCH

    try:
        # Set a small batch limit
        manor_service._LOCAL_REFRESH_FALLBACK_CLEANUP_BATCH = 3

        now = 1000.0
        stale_threshold = 60.0

        # Add 10 stale entries
        for i in range(10):
            manor_service._LOCAL_REFRESH_FALLBACK[i] = now - 100

        manor_service._cleanup_local_fallback_cache(now, stale_threshold)

        # Should have removed at most 3 (the batch limit)
        remaining = len(manor_service._LOCAL_REFRESH_FALLBACK)
        assert remaining >= 7  # At least 7 should remain

    finally:
        manor_service._LOCAL_REFRESH_FALLBACK_CLEANUP_BATCH = original_batch
        manor_service._LOCAL_REFRESH_FALLBACK.clear()
