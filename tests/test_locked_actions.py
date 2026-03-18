from __future__ import annotations

import logging

import pytest
from django.db import DatabaseError

import core.utils.locked_actions as locked_actions

LOGGER = logging.getLogger("tests.locked_actions")


def test_build_scoped_action_lock_key_delegates_to_cache_lock_builder(monkeypatch):
    calls: list[tuple[str, str, int, str]] = []
    spec = locked_actions.ActionLockSpec(
        namespace="test:view_lock",
        timeout_seconds=5,
        logger=LOGGER,
        log_context="test action lock",
    )

    monkeypatch.setattr(
        locked_actions,
        "build_action_lock_key",
        lambda namespace, action, owner_id, scope: calls.append((namespace, action, owner_id, scope)) or "built-key",
    )

    key = locked_actions.build_scoped_action_lock_key(spec, "draw", 7, "pool_a")

    assert key == "built-key"
    assert calls == [("test:view_lock", "draw", 7, "pool_a")]


def test_acquire_scoped_action_lock_uses_spec_configuration(monkeypatch):
    calls: list[tuple[object, ...]] = []
    spec = locked_actions.ActionLockSpec(
        namespace="test:view_lock",
        timeout_seconds=9,
        logger=LOGGER,
        log_context="test action lock",
    )

    monkeypatch.setattr(
        locked_actions,
        "acquire_action_lock",
        lambda namespace, action, owner_id, scope, **kwargs: (
            calls.append((namespace, action, owner_id, scope, kwargs)) or (True, "lock-key", "lock-token")
        ),
    )

    result = locked_actions.acquire_scoped_action_lock(spec, "accept", 3, "scope-1")

    assert result == (True, "lock-key", "lock-token")
    assert calls == [
        (
            "test:view_lock",
            "accept",
            3,
            "scope-1",
            {
                "timeout_seconds": 9,
                "logger": LOGGER,
                "log_context": "test action lock",
                "allow_local_fallback": False,
            },
        )
    ]


def test_release_scoped_action_lock_uses_spec_configuration(monkeypatch):
    calls: list[tuple[object, ...]] = []
    spec = locked_actions.ActionLockSpec(
        namespace="test:view_lock",
        timeout_seconds=5,
        logger=LOGGER,
        log_context="test action lock",
    )

    monkeypatch.setattr(
        locked_actions,
        "release_action_lock",
        lambda lock_key, **kwargs: calls.append((lock_key, kwargs)),
    )

    locked_actions.release_scoped_action_lock(spec, "lock-key", "lock-token")

    assert calls == [
        (
            "lock-key",
            {
                "lock_token": "lock-token",
                "logger": LOGGER,
                "log_context": "test action lock",
            },
        )
    ]


def test_execute_locked_action_routes_known_error_and_releases_lock():
    events: list[str] = []

    result = locked_actions.execute_locked_action(
        action_name="draw",
        owner_id=1,
        scope="scope",
        acquire_lock_fn=lambda *_args: (True, "lock-key", "token"),
        release_lock_fn=lambda key, token: events.append(f"release:{key}:{token}"),
        operation=lambda: (_ for _ in ()).throw(ValueError("bad input")),
        on_lock_conflict=lambda: "conflict",
        on_success=lambda value: f"success:{value}",
        known_exceptions=(ValueError,),
        on_known_error=lambda exc: events.append(f"known:{exc}") or "known-error",
    )

    assert result == "known-error"
    assert events == ["known:bad input", "release:lock-key:token"]


def test_execute_locked_action_routes_database_error():
    events: list[str] = []

    result = locked_actions.execute_locked_action(
        action_name="draw",
        owner_id=1,
        scope="scope",
        acquire_lock_fn=lambda *_args: (True, "lock-key", "token"),
        release_lock_fn=lambda key, token: events.append(f"release:{key}:{token}"),
        operation=lambda: (_ for _ in ()).throw(DatabaseError("db down")),
        on_lock_conflict=lambda: "conflict",
        on_success=lambda value: f"success:{value}",
        on_database_error=lambda exc: events.append(f"db:{exc}") or "db-error",
    )

    assert result == "db-error"
    assert events == ["db:db down", "release:lock-key:token"]


def test_execute_locked_action_re_raises_unexpected_error_when_unhandled():
    with pytest.raises(RuntimeError, match="boom"):
        locked_actions.execute_locked_action(
            action_name="draw",
            owner_id=1,
            scope="scope",
            acquire_lock_fn=lambda *_args: (True, "lock-key", "token"),
            release_lock_fn=lambda *_args: None,
            operation=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            on_lock_conflict=lambda: "conflict",
            on_success=lambda value: f"success:{value}",
        )
