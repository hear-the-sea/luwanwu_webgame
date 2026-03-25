from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from django.contrib import messages
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect

from core.exceptions import GameError
from core.utils import json_error
from core.utils.locked_actions import execute_locked_action
from core.utils.validation import sanitize_error_message

JailActionResult = TypeVar("JailActionResult")
JailResponseT = TypeVar("JailResponseT", bound=HttpResponse)


def message_redirect(
    request: HttpRequest,
    redirect_name: str,
    *,
    level: Callable[[HttpRequest, str], None],
    message: str,
) -> HttpResponse:
    level(request, message)
    return redirect(redirect_name)


def redirect_exception_response(
    request: HttpRequest,
    redirect_name: str,
    exc: GameError | DatabaseError,
) -> HttpResponse:
    return message_redirect(
        request,
        redirect_name,
        level=messages.error,
        message=sanitize_error_message(exc),
    )


def json_exception_response(exc: GameError | DatabaseError, *, status: int = 400) -> JsonResponse:
    return json_error(sanitize_error_message(exc), status=status)


def raise_or_handle_known_jail_exception(
    exc: Exception,
    *,
    handler: Callable[[GameError], JailResponseT],
) -> JailResponseT:
    if not isinstance(exc, GameError):
        raise exc
    return handler(exc)


def execute_locked_jail_action(
    *,
    owner_id: int,
    action_name: str,
    scope: str,
    operation: Callable[[], JailActionResult],
    on_lock_conflict: Callable[[], JailResponseT],
    on_success: Callable[[JailActionResult], JailResponseT],
    on_known_error: Callable[[Exception], JailResponseT],
    on_database_error: Callable[[DatabaseError], JailResponseT],
    log_message: str,
    log_args: tuple[object, ...],
    acquire_lock_fn: Callable[[str, int, str], tuple[bool, str, str | None]],
    release_lock_fn: Callable[[str, str | None], None],
    logger_instance: logging.Logger,
) -> JailResponseT:
    def _handle_database_error(exc: DatabaseError) -> JailResponseT:
        logger_instance.exception(log_message, *log_args)
        return on_database_error(exc)

    return execute_locked_action(
        action_name=action_name,
        owner_id=owner_id,
        scope=scope,
        acquire_lock_fn=acquire_lock_fn,
        release_lock_fn=release_lock_fn,
        operation=operation,
        on_lock_conflict=on_lock_conflict,
        on_success=on_success,
        known_exceptions=(GameError,),
        on_known_error=on_known_error,
        on_database_error=_handle_database_error,
    )


def run_locked_redirect_action(
    *,
    request: HttpRequest,
    owner_id: int,
    action_name: str,
    scope: str,
    operation: Callable[[], JailActionResult],
    success_response: Callable[[JailActionResult], HttpResponse],
    redirect_name: str,
    log_message: str,
    log_args: tuple[object, ...],
    acquire_lock_fn: Callable[[str, int, str], tuple[bool, str, str | None]],
    release_lock_fn: Callable[[str, str | None], None],
    logger_instance: logging.Logger,
) -> HttpResponse:
    return execute_locked_jail_action(
        owner_id=owner_id,
        action_name=action_name,
        scope=scope,
        operation=operation,
        on_lock_conflict=lambda: message_redirect(
            request,
            redirect_name,
            level=messages.warning,
            message="请求处理中，请稍候重试",
        ),
        on_success=success_response,
        on_known_error=lambda exc: raise_or_handle_known_jail_exception(
            exc,
            handler=lambda known_exc: redirect_exception_response(request, redirect_name, known_exc),
        ),
        on_database_error=lambda exc: redirect_exception_response(request, redirect_name, exc),
        log_message=log_message,
        log_args=log_args,
        acquire_lock_fn=acquire_lock_fn,
        release_lock_fn=release_lock_fn,
        logger_instance=logger_instance,
    )


def run_locked_json_action(
    *,
    owner_id: int,
    action_name: str,
    scope: str,
    operation: Callable[[], JailActionResult],
    success_response: Callable[[JailActionResult], JsonResponse],
    log_message: str,
    log_args: tuple[object, ...],
    acquire_lock_fn: Callable[[str, int, str], tuple[bool, str, str | None]],
    release_lock_fn: Callable[[str, str | None], None],
    logger_instance: logging.Logger,
) -> JsonResponse:
    return execute_locked_jail_action(
        owner_id=owner_id,
        action_name=action_name,
        scope=scope,
        operation=operation,
        on_lock_conflict=lambda: json_error("请求处理中，请稍候重试", status=409),
        on_success=success_response,
        on_known_error=lambda exc: raise_or_handle_known_jail_exception(
            exc,
            handler=lambda known_exc: json_exception_response(known_exc),
        ),
        on_database_error=lambda exc: json_exception_response(exc, status=500),
        log_message=log_message,
        log_args=log_args,
        acquire_lock_fn=acquire_lock_fn,
        release_lock_fn=release_lock_fn,
        logger_instance=logger_instance,
    )
