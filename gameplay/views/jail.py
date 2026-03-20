"""
监牢与结义林 API 视图
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import json_error, json_success, parse_json_object, safe_positive_int
from core.utils.locked_actions import (
    ActionLockSpec,
    acquire_scoped_action_lock,
    build_scoped_action_lock_key,
    execute_locked_action,
    release_scoped_action_lock,
)
from core.utils.rate_limit import rate_limit_json
from core.utils.validation import sanitize_error_message
from gameplay.models import Manor
from gameplay.selectors.jail import get_jail_page_context, get_oath_grove_page_context
from gameplay.services.jail import (
    add_oath_bond,
    draw_pie,
    list_held_prisoners,
    list_oath_bonds,
    recruit_prisoner,
    release_prisoner,
    remove_oath_bond,
)
from gameplay.services.manor.core import get_manor
from gameplay.services.resources import project_resource_production_for_read
from gameplay.views.read_helpers import get_prepared_manor_for_read

logger = logging.getLogger(__name__)
JAIL_ACTION_LOCK_SECONDS = 5
JAIL_ACTION_LOCK_NAMESPACE = "jail:view_lock"
JAIL_ACTION_LOCK_SPEC = ActionLockSpec(
    namespace=JAIL_ACTION_LOCK_NAMESPACE,
    timeout_seconds=JAIL_ACTION_LOCK_SECONDS,
    logger=logger,
    log_context="jail action lock",
)
JailActionResult = TypeVar("JailActionResult")
JailResponseT = TypeVar("JailResponseT", bound=HttpResponse)


def _jail_action_lock_key(action: str, manor_id: int, scope: str) -> str:
    return build_scoped_action_lock_key(JAIL_ACTION_LOCK_SPEC, action, manor_id, scope)


def _acquire_jail_action_lock(action: str, manor_id: int, scope: str) -> tuple[bool, str, str | None]:
    return acquire_scoped_action_lock(JAIL_ACTION_LOCK_SPEC, action, manor_id, scope)


def _release_jail_action_lock(lock_key: str, lock_token: str | None) -> None:
    release_scoped_action_lock(JAIL_ACTION_LOCK_SPEC, lock_key, lock_token)


def _oath_guest_id_from_json_or_error(request: HttpRequest) -> tuple[int | None, JsonResponse | None]:
    data = parse_json_object(request.body, empty_as_object=True)
    if data is None:
        return None, json_error("无效的请求数据")
    guest_id = safe_positive_int(data.get("guest_id"), default=None)
    if guest_id is None:
        return None, json_error("请指定门客")
    return guest_id, None


def _message_redirect(
    request: HttpRequest,
    redirect_name: str,
    *,
    level: Callable[[HttpRequest, str], None],
    message: str,
) -> HttpResponse:
    level(request, message)
    return redirect(redirect_name)


def _redirect_exception_response(
    request: HttpRequest,
    redirect_name: str,
    exc: GameError | ValueError | DatabaseError,
) -> HttpResponse:
    return _message_redirect(
        request,
        redirect_name,
        level=messages.error,
        message=sanitize_error_message(exc),
    )


def _json_exception_response(exc: GameError | ValueError | DatabaseError, *, status: int = 400) -> JsonResponse:
    return json_error(sanitize_error_message(exc), status=status)


def _raise_or_handle_known_jail_exception(
    exc: Exception,
    *,
    handler: Callable[[GameError | ValueError], JailResponseT],
) -> JailResponseT:
    if not isinstance(exc, (GameError, ValueError)):
        raise exc
    return handler(exc)


def _execute_locked_jail_action(
    *,
    request: HttpRequest,
    manor: Manor,
    action_name: str,
    scope: str,
    operation: Callable[[], JailActionResult],
    on_lock_conflict: Callable[[], JailResponseT],
    on_success: Callable[[JailActionResult], JailResponseT],
    on_known_error: Callable[[Exception], JailResponseT],
    on_database_error: Callable[[DatabaseError], JailResponseT],
    log_message: str,
    log_args: tuple[object, ...],
) -> JailResponseT:
    def _handle_database_error(exc: DatabaseError) -> JailResponseT:
        logger.exception(log_message, *log_args)
        return on_database_error(exc)

    return execute_locked_action(
        action_name=action_name,
        owner_id=int(manor.id),
        scope=scope,
        acquire_lock_fn=_acquire_jail_action_lock,
        release_lock_fn=_release_jail_action_lock,
        operation=operation,
        on_lock_conflict=on_lock_conflict,
        on_success=on_success,
        known_exceptions=(GameError, ValueError),
        on_known_error=on_known_error,
        on_database_error=_handle_database_error,
    )


def _run_locked_redirect_action(
    *,
    request: HttpRequest,
    manor: Manor,
    action_name: str,
    scope: str,
    operation: Callable[[], JailActionResult],
    success_response: Callable[[JailActionResult], HttpResponse],
    redirect_name: str,
    log_message: str,
    log_args: tuple[object, ...],
) -> HttpResponse:
    return _execute_locked_jail_action(
        request=request,
        manor=manor,
        action_name=action_name,
        scope=scope,
        operation=operation,
        on_lock_conflict=lambda: _message_redirect(
            request,
            redirect_name,
            level=messages.warning,
            message="请求处理中，请稍候重试",
        ),
        on_success=success_response,
        on_known_error=lambda exc: _raise_or_handle_known_jail_exception(
            exc,
            handler=lambda known_exc: _redirect_exception_response(request, redirect_name, known_exc),
        ),
        on_database_error=lambda exc: _redirect_exception_response(request, redirect_name, exc),
        log_message=log_message,
        log_args=log_args,
    )


def _run_locked_json_action(
    *,
    request: HttpRequest,
    manor: Manor,
    action_name: str,
    scope: str,
    operation: Callable[[], JailActionResult],
    success_response: Callable[[JailActionResult], JsonResponse],
    log_message: str,
    log_args: tuple[object, ...],
) -> JsonResponse:
    return _execute_locked_jail_action(
        request=request,
        manor=manor,
        action_name=action_name,
        scope=scope,
        operation=operation,
        on_lock_conflict=lambda: json_error("请求处理中，请稍候重试", status=409),
        on_success=success_response,
        on_known_error=lambda exc: _raise_or_handle_known_jail_exception(
            exc,
            handler=lambda known_exc: _json_exception_response(known_exc),
        ),
        on_database_error=lambda exc: _json_exception_response(exc, status=500),
        log_message=log_message,
        log_args=log_args,
    )


class JailView(LoginRequiredMixin, TemplateView):
    template_name = "gameplay/jail.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        manor = get_prepared_manor_for_read(
            self.request,
            project_fn=project_resource_production_for_read,
            logger=logger,
            source="jail_view",
        )
        context["manor"] = manor
        context.update(get_jail_page_context(manor))
        return context


class OathGroveView(LoginRequiredMixin, TemplateView):
    template_name = "gameplay/oath_grove.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        manor = get_prepared_manor_for_read(
            self.request,
            project_fn=project_resource_production_for_read,
            logger=logger,
            source="oath_grove_view",
        )
        context["manor"] = manor
        context.update(get_oath_grove_page_context(manor))
        return context


@login_required
def jail_status_api(request: HttpRequest) -> JsonResponse:
    manor = get_manor(request.user)
    prisoners = list_held_prisoners(manor)
    return json_success(
        jail={
            "capacity": int(getattr(manor, "jail_capacity", 0) or 0),
            "count": len(prisoners),
            "prisoners": [
                {
                    "id": p.id,
                    "name": p.display_name,
                    "template_key": getattr(p.guest_template, "key", ""),
                    "rarity": getattr(p.guest_template, "rarity", ""),
                    "loyalty": int(p.loyalty),
                    "captured_at": p.captured_at.isoformat() if p.captured_at else "",
                    "original_manor": getattr(getattr(p, "original_manor", None), "display_name", ""),
                }
                for p in prisoners
            ],
        }
    )


@login_required
def oath_status_api(request: HttpRequest) -> JsonResponse:
    manor = get_manor(request.user)
    bonds = list_oath_bonds(manor)
    return json_success(
        oath_grove={
            "capacity": int(getattr(manor, "oath_capacity", 0) or 0),
            "count": len(bonds),
            "bonds": [
                {
                    "guest_id": b.guest_id,
                    "name": b.guest.display_name,
                    "template_key": getattr(b.guest.template, "key", ""),
                    "rarity": getattr(b.guest.template, "rarity", ""),
                    "created_at": b.created_at.isoformat() if b.created_at else "",
                }
                for b in bonds
            ],
        }
    )


@login_required
@require_POST
def recruit_prisoner_view(request: HttpRequest, prisoner_id: int) -> HttpResponse:
    manor = get_manor(request.user)
    return _run_locked_redirect_action(
        request=request,
        manor=manor,
        action_name="recruit_view",
        scope=str(prisoner_id),
        operation=lambda: recruit_prisoner(manor, int(prisoner_id)),
        success_response=lambda guest: _message_redirect(
            request,
            "gameplay:jail",
            level=messages.success,
            message=f"成功招募：{guest.display_name}（等级已重置，装备已清空）",
        ),
        redirect_name="gameplay:jail",
        log_message="Unexpected jail recruit error: manor_id=%s prisoner_id=%s",
        log_args=(getattr(manor, "id", None), prisoner_id),
    )


@login_required
@require_POST
def draw_pie_view(request: HttpRequest, prisoner_id: int) -> HttpResponse:
    manor = get_manor(request.user)
    return _run_locked_redirect_action(
        request=request,
        manor=manor,
        action_name="draw_pie_view",
        scope=str(prisoner_id),
        operation=lambda: draw_pie(manor, int(prisoner_id)),
        success_response=lambda prisoner: _message_redirect(
            request,
            "gameplay:jail",
            level=messages.success,
            message=f"画饼成功！{prisoner.display_name} 忠诚度 -{getattr(prisoner, '_reduction', 0)}",
        ),
        redirect_name="gameplay:jail",
        log_message="Unexpected jail draw_pie error: manor_id=%s prisoner_id=%s",
        log_args=(getattr(manor, "id", None), prisoner_id),
    )


@login_required
@require_POST
def release_prisoner_view(request: HttpRequest, prisoner_id: int) -> HttpResponse:
    manor = get_manor(request.user)
    return _run_locked_redirect_action(
        request=request,
        manor=manor,
        action_name="release_view",
        scope=str(prisoner_id),
        operation=lambda: release_prisoner(manor, int(prisoner_id)),
        success_response=lambda prisoner: _message_redirect(
            request,
            "gameplay:jail",
            level=messages.success,
            message=f"已释放：{prisoner.display_name}",
        ),
        redirect_name="gameplay:jail",
        log_message="Unexpected jail release error: manor_id=%s prisoner_id=%s",
        log_args=(getattr(manor, "id", None), prisoner_id),
    )


@login_required
@require_POST
def add_oath_bond_view(request: HttpRequest) -> HttpResponse:
    manor = get_manor(request.user)
    guest_id = safe_positive_int(request.POST.get("guest_id"), default=None)
    if guest_id is None:
        messages.error(request, "请指定门客")
        return redirect("gameplay:oath_grove")
    return _run_locked_redirect_action(
        request=request,
        manor=manor,
        action_name="oath_add_view",
        scope=str(guest_id),
        operation=lambda: add_oath_bond(manor, guest_id),
        success_response=lambda bond: _message_redirect(
            request,
            "gameplay:oath_grove",
            level=messages.success,
            message=f"结义成功：{bond.guest.display_name}",
        ),
        redirect_name="gameplay:oath_grove",
        log_message="Unexpected oath add error: manor_id=%s guest_id=%s",
        log_args=(getattr(manor, "id", None), guest_id),
    )


@login_required
@require_POST
def remove_oath_bond_view(request: HttpRequest, guest_id: int) -> HttpResponse:
    manor = get_manor(request.user)
    return _run_locked_redirect_action(
        request=request,
        manor=manor,
        action_name="oath_remove_view",
        scope=str(guest_id),
        operation=lambda: remove_oath_bond(manor, int(guest_id)),
        success_response=lambda deleted: _message_redirect(
            request,
            "gameplay:oath_grove",
            level=messages.error if not deleted else messages.success,
            message="该门客未结义" if not deleted else "已解除结义",
        ),
        redirect_name="gameplay:oath_grove",
        log_message="Unexpected oath remove error: manor_id=%s guest_id=%s",
        log_args=(getattr(manor, "id", None), guest_id),
    )


@login_required
@require_POST
@rate_limit_json("jail_recruit", limit=10, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def recruit_prisoner_api(request: HttpRequest, prisoner_id: int) -> JsonResponse:
    manor = get_manor(request.user)
    return _run_locked_json_action(
        request=request,
        manor=manor,
        action_name="recruit_api",
        scope=str(prisoner_id),
        operation=lambda: recruit_prisoner(manor, int(prisoner_id)),
        success_response=lambda guest: json_success(
            message=f"成功招募：{guest.display_name}（等级已重置，装备已清空）",
            guest_id=guest.id,
        ),
        log_message="Unexpected jail recruit API error: manor_id=%s prisoner_id=%s",
        log_args=(getattr(manor, "id", None), prisoner_id),
    )


@login_required
@require_POST
@rate_limit_json("jail_draw_pie", limit=30, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def draw_pie_api(request: HttpRequest, prisoner_id: int) -> JsonResponse:
    manor = get_manor(request.user)
    return _run_locked_json_action(
        request=request,
        manor=manor,
        action_name="draw_pie_api",
        scope=str(prisoner_id),
        operation=lambda: draw_pie(manor, int(prisoner_id)),
        success_response=lambda prisoner: json_success(
            message=f"画饼成功！{prisoner.display_name} 忠诚度 -{getattr(prisoner, '_reduction', 0)}",
            prisoner_id=prisoner.id,
            new_loyalty=prisoner.loyalty,
            reduction=getattr(prisoner, "_reduction", 0),
        ),
        log_message="Unexpected jail draw_pie API error: manor_id=%s prisoner_id=%s",
        log_args=(getattr(manor, "id", None), prisoner_id),
    )


@login_required
@require_POST
@rate_limit_json("jail_release", limit=20, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def release_prisoner_api(request: HttpRequest, prisoner_id: int) -> JsonResponse:
    manor = get_manor(request.user)
    return _run_locked_json_action(
        request=request,
        manor=manor,
        action_name="release_api",
        scope=str(prisoner_id),
        operation=lambda: release_prisoner(manor, int(prisoner_id)),
        success_response=lambda prisoner: json_success(
            message=f"已释放：{prisoner.display_name}", prisoner_id=prisoner.id
        ),
        log_message="Unexpected jail release API error: manor_id=%s prisoner_id=%s",
        log_args=(getattr(manor, "id", None), prisoner_id),
    )


@login_required
@require_POST
@rate_limit_json("oath_add", limit=10, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def add_oath_bond_api(request: HttpRequest) -> JsonResponse:
    manor = get_manor(request.user)
    guest_id, error = _oath_guest_id_from_json_or_error(request)
    if error is not None:
        return error
    if guest_id is None:
        return json_error("请指定门客")

    return _run_locked_json_action(
        request=request,
        manor=manor,
        action_name="oath_add_api",
        scope=str(guest_id),
        operation=lambda: add_oath_bond(manor, guest_id),
        success_response=lambda bond: json_success(message=f"结义成功：{bond.guest.display_name}"),
        log_message="Unexpected oath add API error: manor_id=%s guest_id=%s",
        log_args=(getattr(manor, "id", None), guest_id),
    )


@login_required
@require_POST
@rate_limit_json("oath_remove", limit=10, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def remove_oath_bond_api(request: HttpRequest) -> JsonResponse:
    manor = get_manor(request.user)
    guest_id, error = _oath_guest_id_from_json_or_error(request)
    if error is not None:
        return error
    if guest_id is None:
        return json_error("请指定门客")

    return _run_locked_json_action(
        request=request,
        manor=manor,
        action_name="oath_remove_api",
        scope=str(guest_id),
        operation=lambda: remove_oath_bond(manor, guest_id),
        success_response=lambda deleted: (
            json_error("该门客未结义") if not deleted else json_success(message="已解除结义")
        ),
        log_message="Unexpected oath remove API error: manor_id=%s guest_id=%s",
        log_args=(getattr(manor, "id", None), guest_id),
    )
