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

    acquired_1, from_cache_1, token_1 = cache_lock.acquire_best_effort_lock(
        "lock:test:1",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    acquired_2, from_cache_2, token_2 = cache_lock.acquire_best_effort_lock(
        "lock:test:1",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )

    assert acquired_1 is True
    assert from_cache_1 is False
    assert bool(token_1)
    assert acquired_2 is False
    assert from_cache_2 is False
    assert token_2 is None

    cache_lock.release_best_effort_lock(
        "lock:test:1",
        from_cache=False,
        lock_token=token_1,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    acquired_3, from_cache_3, token_3 = cache_lock.acquire_best_effort_lock(
        "lock:test:1",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    assert acquired_3 is True
    assert from_cache_3 is False
    assert bool(token_3)

    cache_lock._LOCAL_LOCKS.clear()


def test_cache_lock_can_fail_closed_when_local_fallback_disabled(monkeypatch):
    class _BrokenCache:
        def add(self, *_args, **_kwargs):
            raise RuntimeError("cache down")

    cache_lock._LOCAL_LOCKS.clear()
    monkeypatch.setattr(cache_lock, "cache", _BrokenCache())

    acquired, from_cache, token = cache_lock.acquire_best_effort_lock(
        "lock:test:fail-closed",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
        allow_local_fallback=False,
    )

    assert acquired is False
    assert from_cache is False
    assert token is None
    assert cache_lock._LOCAL_LOCKS == {}


def test_cache_lock_uses_cache_when_available(monkeypatch):
    class _FakeCache:
        def __init__(self):
            self._keys: dict[str, str] = {}
            self.deleted: list[str] = []

        def add(self, key, value, *_args, **_kwargs):
            if key in self._keys:
                return False
            self._keys[key] = value
            return True

        def get(self, key, default=None):
            return self._keys.get(key, default)

        def make_key(self, key):
            return key

        def delete(self, key):
            self.deleted.append(key)
            self._keys.pop(key, None)
            return True

    fake_cache = _FakeCache()
    monkeypatch.setattr(cache_lock, "cache", fake_cache)

    acquired_1, from_cache_1, token_1 = cache_lock.acquire_best_effort_lock(
        "lock:test:2",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    acquired_2, from_cache_2, token_2 = cache_lock.acquire_best_effort_lock(
        "lock:test:2",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )

    assert acquired_1 is True
    assert from_cache_1 is True
    assert bool(token_1)
    assert acquired_2 is False
    assert from_cache_2 is True
    assert token_2 is None

    cache_lock.release_best_effort_lock(
        "lock:test:2",
        from_cache=True,
        lock_token=token_1,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    assert fake_cache.deleted == ["lock:test:2"]


def test_cache_lock_release_skips_on_token_mismatch(monkeypatch):
    class _FakeCache:
        def __init__(self):
            self._keys: dict[str, str] = {}
            self.deleted: list[str] = []

        def add(self, key, value, *_args, **_kwargs):
            if key in self._keys:
                return False
            self._keys[key] = value
            return True

        def get(self, key, default=None):
            return self._keys.get(key, default)

        def make_key(self, key):
            return key

        def delete(self, key):
            self.deleted.append(key)
            self._keys.pop(key, None)
            return True

    fake_cache = _FakeCache()
    monkeypatch.setattr(cache_lock, "cache", fake_cache)

    acquired, from_cache, token = cache_lock.acquire_best_effort_lock(
        "lock:test:mismatch",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    assert acquired is True
    assert from_cache is True
    assert bool(token)

    cache_lock.release_best_effort_lock(
        "lock:test:mismatch",
        from_cache=True,
        lock_token="wrong-token",
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    assert fake_cache.deleted == []

    acquired_again, from_cache_again, token_again = cache_lock.acquire_best_effort_lock(
        "lock:test:mismatch",
        timeout_seconds=5,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    assert acquired_again is False
    assert from_cache_again is True
    assert token_again is None

    cache_lock.release_best_effort_lock(
        "lock:test:mismatch",
        from_cache=True,
        lock_token=token,
        logger=logging.getLogger(__name__),
        log_context="test lock",
    )
    assert fake_cache.deleted == ["lock:test:mismatch"]


def test_release_cache_key_if_owner_prefers_atomic_path(monkeypatch):
    logger = logging.getLogger(__name__)
    called = {"atomic": 0, "fallback": 0}

    def _atomic(*_args, **_kwargs):
        called["atomic"] += 1
        return True

    def _fallback(*_args, **_kwargs):
        called["fallback"] += 1
        return True

    monkeypatch.setattr(cache_lock, "_release_cache_lock_atomic_if_owner", _atomic)
    monkeypatch.setattr(cache_lock, "_release_cache_lock_non_atomic_if_owner", _fallback)

    released = cache_lock.release_cache_key_if_owner(
        "lock:test:atomic",
        lock_token="token",
        logger=logger,
        log_context="test release",
    )

    assert released is True
    assert called["atomic"] == 1
    assert called["fallback"] == 0


def test_release_cache_key_if_owner_falls_back_when_atomic_unavailable(monkeypatch):
    logger = logging.getLogger(__name__)
    called = {"atomic": 0, "fallback": 0}

    def _atomic(*_args, **_kwargs):
        called["atomic"] += 1
        return None

    def _fallback(*_args, **_kwargs):
        called["fallback"] += 1
        return True

    monkeypatch.setattr(cache_lock, "_release_cache_lock_atomic_if_owner", _atomic)
    monkeypatch.setattr(cache_lock, "_release_cache_lock_non_atomic_if_owner", _fallback)

    released = cache_lock.release_cache_key_if_owner(
        "lock:test:fallback",
        lock_token="token",
        logger=logger,
        log_context="test release",
    )

    assert released is True
    assert called["atomic"] == 1
    assert called["fallback"] == 1
