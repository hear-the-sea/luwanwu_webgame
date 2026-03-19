from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponse

from core.exceptions import GameError
from core.utils import sanitize_error_message
from core.utils.locked_actions import (
    ActionLockSpec,
    acquire_scoped_action_lock,
    execute_locked_action,
    release_scoped_action_lock,
)
from core.utils.view_error_mapping import (
    DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS,
    LEGACY_VALUE_ERROR_VIEW_EXCEPTIONS,
    classify_view_error,
)

logger = logging.getLogger(__name__)
RECRUIT_ACTION_LOCK_SECONDS = 5
RECRUIT_ACTION_LOCK_NAMESPACE = "recruit:view_lock"
RECRUIT_ACTION_LOCK_SPEC = ActionLockSpec(
    namespace=RECRUIT_ACTION_LOCK_NAMESPACE,
    timeout_seconds=RECRUIT_ACTION_LOCK_SECONDS,
    logger=logger,
    log_context="recruit action lock",
)


def _acquire_recruit_action_lock(action: str, manor_id: int, scope: str) -> tuple[bool, str, str | None]:
    return acquire_scoped_action_lock(RECRUIT_ACTION_LOCK_SPEC, action, manor_id, scope)


def _release_recruit_action_lock(lock_key: str, lock_token: str | None) -> None:
    release_scoped_action_lock(RECRUIT_ACTION_LOCK_SPEC, lock_key, lock_token)


def run_locked_recruit_action(
    *,
    request: HttpRequest,
    manor: Any,
    is_ajax: bool,
    lock_action: str,
    lock_scope: str,
    operation: Callable[[], HttpResponse],
    database_log_message: str,
    unexpected_log_message: str,
    log_args: tuple[object, ...],
    recruitment_hall_response: Callable[..., HttpResponse],
    acquire_lock_fn: Callable[[str, int, str], tuple[bool, str, str | None]] = _acquire_recruit_action_lock,
    release_lock_fn: Callable[[str, str | None], None] = _release_recruit_action_lock,
) -> HttpResponse:
    def _conflict_response() -> HttpResponse:
        return recruitment_hall_response(
            request,
            manor,
            "请求处理中，请稍候重试",
            is_ajax=is_ajax,
            status=409,
            message_level="warning",
        )

    def _on_error(exc: Exception, *, log_message: str | None) -> HttpResponse:
        category = classify_view_error(exc, known_exceptions=LEGACY_VALUE_ERROR_VIEW_EXCEPTIONS)
        if category == "unexpected":
            raise exc
        if category != "known" and log_message is not None:
            logger.exception(log_message, *log_args)
        status = 400 if category == "known" else 500
        return recruitment_hall_response(
            request,
            manor,
            sanitize_error_message(exc),
            is_ajax=is_ajax,
            status=status,
            message_level="error",
        )

    return execute_locked_action(
        action_name=lock_action,
        owner_id=int(manor.id),
        scope=lock_scope,
        acquire_lock_fn=acquire_lock_fn,
        release_lock_fn=release_lock_fn,
        operation=operation,
        on_lock_conflict=_conflict_response,
        on_success=lambda response: response,
        known_exceptions=(GameError, ValueError),
        on_known_error=lambda exc: _on_error(exc, log_message=None),
        on_database_error=lambda exc: _on_error(exc, log_message=database_log_message),
        on_unexpected_error=lambda exc: _on_error(exc, log_message=unexpected_log_message),
        unexpected_exceptions=DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS,
    )
