from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, cast

from django.http import JsonResponse

from core.exceptions import GameError
from core.utils.locked_actions import execute_locked_action
from core.utils.view_error_mapping import DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS, json_error_response_for_exception

MapActionResult = TypeVar("MapActionResult")


def run_locked_map_json_action(
    *,
    owner_id: int,
    action_name: str,
    scope: str,
    operation: Callable[[], MapActionResult],
    success_response: Callable[[MapActionResult], JsonResponse],
    conflict_response: Callable[[], JsonResponse],
    error_response: Callable[[Exception, str, tuple[object, ...]], JsonResponse],
    acquire_lock_fn: Callable[[str, int, str], tuple[bool, str, str | None]],
    release_lock_fn: Callable[[str, str | None], None],
    logger_instance,
    log_message: str,
    log_args: tuple[object, ...],
    known_exceptions: tuple[type[Exception], ...] = (GameError,),
) -> JsonResponse:
    return execute_locked_action(
        action_name=action_name,
        owner_id=owner_id,
        scope=scope,
        acquire_lock_fn=acquire_lock_fn,
        release_lock_fn=release_lock_fn,
        operation=operation,
        on_lock_conflict=conflict_response,
        on_success=success_response,
        known_exceptions=known_exceptions,
        on_known_error=lambda exc: cast(
            JsonResponse,
            json_error_response_for_exception(
                exc,
                logger_instance=logger_instance,
                known_exceptions=known_exceptions,
            ),
        ),
        on_database_error=lambda exc: error_response(exc, log_message, log_args),
        on_unexpected_error=lambda exc: error_response(exc, log_message, log_args),
        unexpected_exceptions=DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS,
    )
