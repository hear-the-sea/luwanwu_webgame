from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Any, Literal

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from core.exceptions import GameError
from core.utils import json_error, sanitize_error_message
from core.utils.infrastructure import DATABASE_INFRASTRUCTURE_EXCEPTIONS, is_expected_infrastructure_error

ViewErrorCategory = Literal["known", "infrastructure", "unexpected"]
KNOWN_VIEW_EXCEPTIONS = (GameError,)
DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS = DATABASE_INFRASTRUCTURE_EXCEPTIONS


def classify_view_error(
    exc: Exception,
    *,
    known_exceptions: tuple[type[Exception], ...] = KNOWN_VIEW_EXCEPTIONS,
    infrastructure_exceptions: tuple[type[Exception], ...] = DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS,
    allow_runtime_markers: bool = False,
) -> ViewErrorCategory:
    if isinstance(exc, known_exceptions):
        return "known"
    if is_expected_infrastructure_error(
        exc,
        exceptions=infrastructure_exceptions,
        allow_runtime_markers=allow_runtime_markers,
    ):
        return "infrastructure"
    return "unexpected"


def _log_non_business_error(
    category: ViewErrorCategory,
    *,
    log_message: str | None,
    log_args: tuple[object, ...],
    logger_instance: logging.Logger | None,
) -> None:
    if category != "infrastructure" or log_message is None:
        return
    active_logger = logger_instance or logging.getLogger(__name__)
    active_logger.exception(log_message, *log_args)


def _raise_original_exception(exc: Exception) -> None:
    active_exc = sys.exc_info()[1]
    if active_exc is exc:
        raise
    if exc.__traceback__ is not None:
        raise exc.with_traceback(exc.__traceback__)
    raise exc


def flash_view_error(
    request: HttpRequest,
    exc: Exception,
    *,
    log_message: str | None = None,
    log_args: tuple[object, ...] = (),
    logger_instance: logging.Logger | None = None,
    known_exceptions: tuple[type[Exception], ...] = KNOWN_VIEW_EXCEPTIONS,
    infrastructure_exceptions: tuple[type[Exception], ...] = DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS,
    allow_runtime_markers: bool = False,
) -> ViewErrorCategory:
    category = classify_view_error(
        exc,
        known_exceptions=known_exceptions,
        infrastructure_exceptions=infrastructure_exceptions,
        allow_runtime_markers=allow_runtime_markers,
    )
    _log_non_business_error(
        category,
        log_message=log_message,
        log_args=log_args,
        logger_instance=logger_instance,
    )
    if category == "unexpected":
        _raise_original_exception(exc)
    messages.error(request, sanitize_error_message(exc))
    return category


def json_error_response_for_exception(
    exc: Exception,
    *,
    known_status: int = 400,
    fallback_status: int = 500,
    log_message: str | None = None,
    log_args: tuple[object, ...] = (),
    logger_instance: logging.Logger | None = None,
    known_exceptions: tuple[type[Exception], ...] = KNOWN_VIEW_EXCEPTIONS,
    infrastructure_exceptions: tuple[type[Exception], ...] = DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS,
    allow_runtime_markers: bool = False,
    include_message: bool = False,
    **payload: Any,
) -> HttpResponse:
    category = classify_view_error(
        exc,
        known_exceptions=known_exceptions,
        infrastructure_exceptions=infrastructure_exceptions,
        allow_runtime_markers=allow_runtime_markers,
    )
    _log_non_business_error(
        category,
        log_message=log_message,
        log_args=log_args,
        logger_instance=logger_instance,
    )
    if category == "unexpected":
        _raise_original_exception(exc)
    status = known_status if category == "known" else fallback_status
    return json_error(
        sanitize_error_message(exc),
        status=status,
        include_message=include_message,
        **payload,
    )


def action_error_response(
    request: HttpRequest,
    exc: Exception,
    *,
    is_ajax: bool,
    redirect_to: str | Callable[[], HttpResponse],
    known_status: int = 400,
    fallback_status: int = 500,
    log_message: str | None = None,
    log_args: tuple[object, ...] = (),
    logger_instance: logging.Logger | None = None,
    known_exceptions: tuple[type[Exception], ...] = KNOWN_VIEW_EXCEPTIONS,
    infrastructure_exceptions: tuple[type[Exception], ...] = DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS,
    allow_runtime_markers: bool = False,
    include_message: bool = False,
    **payload: Any,
) -> HttpResponse:
    if is_ajax:
        return json_error_response_for_exception(
            exc,
            known_status=known_status,
            fallback_status=fallback_status,
            log_message=log_message,
            log_args=log_args,
            logger_instance=logger_instance,
            known_exceptions=known_exceptions,
            infrastructure_exceptions=infrastructure_exceptions,
            allow_runtime_markers=allow_runtime_markers,
            include_message=include_message,
            **payload,
        )

    flash_view_error(
        request,
        exc,
        log_message=log_message,
        log_args=log_args,
        logger_instance=logger_instance,
        known_exceptions=known_exceptions,
        infrastructure_exceptions=infrastructure_exceptions,
        allow_runtime_markers=allow_runtime_markers,
    )
    if callable(redirect_to):
        return redirect_to()
    return redirect(redirect_to)


__all__ = [
    "DEFAULT_VIEW_INFRASTRUCTURE_EXCEPTIONS",
    "KNOWN_VIEW_EXCEPTIONS",
    "ViewErrorCategory",
    "action_error_response",
    "classify_view_error",
    "flash_view_error",
    "json_error_response_for_exception",
]
