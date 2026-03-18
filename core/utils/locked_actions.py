from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import TypeVar

from django.db import DatabaseError

from core.utils.cache_lock import acquire_action_lock, build_action_lock_key, release_action_lock

ResultT = TypeVar("ResultT")
ResponseT = TypeVar("ResponseT")


@dataclass(frozen=True)
class ActionLockSpec:
    namespace: str
    timeout_seconds: int
    logger: Logger
    log_context: str
    allow_local_fallback: bool = False


def build_scoped_action_lock_key(spec: ActionLockSpec, action: str, owner_id: int, scope: str) -> str:
    return build_action_lock_key(spec.namespace, action, owner_id, scope)


def acquire_scoped_action_lock(
    spec: ActionLockSpec, action: str, owner_id: int, scope: str
) -> tuple[bool, str, str | None]:
    return acquire_action_lock(
        spec.namespace,
        action,
        owner_id,
        scope,
        timeout_seconds=spec.timeout_seconds,
        logger=spec.logger,
        log_context=spec.log_context,
        allow_local_fallback=spec.allow_local_fallback,
    )


def release_scoped_action_lock(spec: ActionLockSpec, lock_key: str, lock_token: str | None) -> None:
    release_action_lock(
        lock_key,
        lock_token=lock_token,
        logger=spec.logger,
        log_context=spec.log_context,
    )


def execute_locked_action(
    *,
    action_name: str,
    owner_id: int,
    scope: str,
    acquire_lock_fn: Callable[[str, int, str], tuple[bool, str, str | None]],
    release_lock_fn: Callable[[str, str | None], None],
    operation: Callable[[], ResultT],
    on_lock_conflict: Callable[[], ResponseT],
    on_success: Callable[[ResultT], ResponseT],
    on_known_error: Callable[[Exception], ResponseT] | None = None,
    known_exceptions: tuple[type[Exception], ...] = (),
    on_database_error: Callable[[DatabaseError], ResponseT] | None = None,
    on_unexpected_error: Callable[[Exception], ResponseT] | None = None,
    unexpected_exceptions: tuple[type[Exception], ...] | None = None,
) -> ResponseT:
    lock_ok, lock_key, lock_token = acquire_lock_fn(action_name, owner_id, scope)
    if not lock_ok:
        return on_lock_conflict()

    try:
        try:
            result = operation()
        except known_exceptions as exc:
            if on_known_error is None:
                raise
            return on_known_error(exc)
        except DatabaseError as exc:
            if on_database_error is None:
                raise
            return on_database_error(exc)
        except tuple(unexpected_exceptions or ()) as exc:
            if on_unexpected_error is None:
                raise
            return on_unexpected_error(exc)
        return on_success(result)
    finally:
        release_lock_fn(lock_key, lock_token)
