from __future__ import annotations

import logging

import core.utils.cache_lock as cache_lock


def test_cache_lock_falls_back_to_local_lock_when_cache_unavailable(monkeypatch):
    class _BrokenCache:
        def add(self, *_args, **_kwargs):
            raise RuntimeError("cache down")

        def delete(self, *_args, **_kwargs):
            raise RuntimeError("cache down")

    cache_lock._LOCAL_LOCKS.clear()
    monkeypatch.setattr(cache_lock, "cache", _BrokenCache())

    acquired_1, from_cache_1 = cache_lock.acquire_best_effort_lock(
        "lock:test:1",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    acquired_2, from_cache_2 = cache_lock.acquire_best_effort_lock(
        "lock:test:1",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )

    assert acquired_1 is True
    assert from_cache_1 is False
    assert acquired_2 is False
    assert from_cache_2 is False

    cache_lock.release_best_effort_lock(
        "lock:test:1",
        from_cache=False,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    acquired_3, from_cache_3 = cache_lock.acquire_best_effort_lock(
        "lock:test:1",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    assert acquired_3 is True
    assert from_cache_3 is False

    cache_lock._LOCAL_LOCKS.clear()


def test_cache_lock_uses_cache_when_available(monkeypatch):
    class _FakeCache:
        def __init__(self):
            self._keys: set[str] = set()
            self.deleted: list[str] = []

        def add(self, key, *_args, **_kwargs):
            if key in self._keys:
                return False
            self._keys.add(key)
            return True

        def delete(self, key):
            self.deleted.append(key)
            self._keys.discard(key)
            return True

    fake_cache = _FakeCache()
    monkeypatch.setattr(cache_lock, "cache", fake_cache)

    acquired_1, from_cache_1 = cache_lock.acquire_best_effort_lock(
        "lock:test:2",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    acquired_2, from_cache_2 = cache_lock.acquire_best_effort_lock(
        "lock:test:2",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )

    assert acquired_1 is True
    assert from_cache_1 is True
    assert acquired_2 is False
    assert from_cache_2 is True

    cache_lock.release_best_effort_lock(
        "lock:test:2",
        from_cache=True,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    assert fake_cache.deleted == ["lock:test:2"]
