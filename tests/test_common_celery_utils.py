from __future__ import annotations

import logging

from common.utils import celery as celery_utils


class _Task:
    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail
        self.called = 0
        self.last_kwargs = None

    def apply_async(self, **kwargs):
        self.called += 1
        self.last_kwargs = kwargs
        if self.should_fail:
            raise RuntimeError("dispatch failed")


# ============ safe_apply_async tests ============


def test_safe_apply_async_returns_true_on_success():
    """Test that safe_apply_async returns True when dispatch succeeds."""
    task = _Task()

    ok = celery_utils.safe_apply_async(task, args=[1, 2], kwargs={"key": "value"})

    assert ok is True
    assert task.called == 1
    assert task.last_kwargs == {"args": [1, 2], "kwargs": {"key": "value"}, "countdown": None}


def test_safe_apply_async_returns_false_on_failure():
    """Test that safe_apply_async returns False when dispatch fails."""
    task = _Task(should_fail=True)

    ok = celery_utils.safe_apply_async(task, args=[1])

    assert ok is False
    assert task.called == 1


def test_safe_apply_async_logs_on_failure_when_logger_provided(caplog):
    """Test that safe_apply_async logs warning when dispatch fails and logger is provided."""
    task = _Task(should_fail=True)
    test_logger = logging.getLogger("test_celery")

    with caplog.at_level(logging.WARNING):
        ok = celery_utils.safe_apply_async(
            task,
            args=[1],
            logger=test_logger,
            log_message="custom error message",
        )

    assert ok is False
    assert "custom error message" in caplog.text


def test_safe_apply_async_handles_none_args_and_kwargs():
    """Test that safe_apply_async handles None args and kwargs correctly."""
    task = _Task()

    ok = celery_utils.safe_apply_async(task)

    assert ok is True
    assert task.last_kwargs == {"args": [], "kwargs": {}, "countdown": None}


def test_safe_apply_async_passes_countdown():
    """Test that safe_apply_async passes countdown parameter correctly."""
    task = _Task()

    ok = celery_utils.safe_apply_async(task, args=[1], countdown=60)

    assert ok is True
    assert task.last_kwargs["countdown"] == 60


# ============ safe_apply_async_with_dedup tests ============


def test_safe_apply_async_with_dedup_skips_when_key_already_exists(monkeypatch):
    task = _Task()
    monkeypatch.setattr(celery_utils.cache, "add", lambda *_args, **_kwargs: False)

    ok = celery_utils.safe_apply_async_with_dedup(
        task,
        dedup_key="test:key",
        dedup_timeout=5,
        args=[1],
    )

    assert ok is True
    assert task.called == 0


def test_safe_apply_async_with_dedup_dispatches_when_gate_open(monkeypatch):
    task = _Task()
    monkeypatch.setattr(celery_utils.cache, "add", lambda *_args, **_kwargs: True)

    ok = celery_utils.safe_apply_async_with_dedup(
        task,
        dedup_key="test:key2",
        dedup_timeout=5,
        args=[2],
        countdown=3,
    )

    assert ok is True
    assert task.called == 1
    assert task.last_kwargs == {"args": [2], "kwargs": {}, "countdown": 3}


def test_safe_apply_async_with_dedup_returns_false_on_dispatch_error(monkeypatch):
    task = _Task(should_fail=True)
    deleted = {"keys": []}
    monkeypatch.setattr(celery_utils.cache, "add", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(celery_utils.cache, "delete", lambda key: deleted["keys"].append(key))

    ok = celery_utils.safe_apply_async_with_dedup(
        task,
        dedup_key="test:key3",
        dedup_timeout=5,
        args=[3],
    )

    assert ok is False
    assert task.called == 1
    assert deleted["keys"] == ["test:key3"]


def test_safe_apply_async_with_dedup_falls_back_when_cache_unavailable(monkeypatch):
    task = _Task()

    def _raise(*_args, **_kwargs):
        raise RuntimeError("cache down")

    monkeypatch.setattr(celery_utils.cache, "add", _raise)

    ok = celery_utils.safe_apply_async_with_dedup(
        task,
        dedup_key="test:key4",
        dedup_timeout=5,
        args=[4],
    )

    assert ok is True
    assert task.called == 1


def test_safe_apply_async_with_dedup_skips_dedup_when_key_empty(monkeypatch):
    """Test that dedup is skipped when dedup_key is empty."""
    task = _Task()
    cache_add_called = {"count": 0}

    def _track_add(*_args, **_kwargs):
        cache_add_called["count"] += 1
        return True

    monkeypatch.setattr(celery_utils.cache, "add", _track_add)

    ok = celery_utils.safe_apply_async_with_dedup(
        task,
        dedup_key="",  # Empty key
        dedup_timeout=5,
        args=[5],
    )

    assert ok is True
    assert task.called == 1
    assert cache_add_called["count"] == 0  # cache.add should not be called


def test_safe_apply_async_with_dedup_skips_dedup_when_timeout_zero(monkeypatch):
    """Test that dedup is skipped when dedup_timeout is zero."""
    task = _Task()
    cache_add_called = {"count": 0}

    def _track_add(*_args, **_kwargs):
        cache_add_called["count"] += 1
        return True

    monkeypatch.setattr(celery_utils.cache, "add", _track_add)

    ok = celery_utils.safe_apply_async_with_dedup(
        task,
        dedup_key="test:key6",
        dedup_timeout=0,  # Zero timeout
        args=[6],
    )

    assert ok is True
    assert task.called == 1
    assert cache_add_called["count"] == 0  # cache.add should not be called


def test_safe_apply_async_with_dedup_passes_kwargs(monkeypatch):
    """Test that kwargs are passed correctly through dedup wrapper."""
    task = _Task()
    monkeypatch.setattr(celery_utils.cache, "add", lambda *_args, **_kwargs: True)

    ok = celery_utils.safe_apply_async_with_dedup(
        task,
        dedup_key="test:key7",
        dedup_timeout=5,
        args=[7],
        kwargs={"foo": "bar"},
        countdown=10,
    )

    assert ok is True
    assert task.last_kwargs == {"args": [7], "kwargs": {"foo": "bar"}, "countdown": 10}
