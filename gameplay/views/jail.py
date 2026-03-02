"""
监牢与结义林 API 视图
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import json_error, json_success, parse_json_object, safe_positive_int
from core.utils.cache_lock import acquire_best_effort_lock, release_best_effort_lock
from core.utils.rate_limit import rate_limit_json
from core.utils.validation import sanitize_error_message
from gameplay.constants import PVPConstants, get_raid_capture_guest_rate
from gameplay.services import (
    add_oath_bond,
    draw_pie,
    ensure_manor,
    list_held_prisoners,
    list_oath_bonds,
    recruit_prisoner,
    release_prisoner,
    remove_oath_bond,
)
from guests.query_utils import guest_template_rarity_rank_case

logger = logging.getLogger(__name__)
JAIL_ACTION_LOCK_SECONDS = 5
_LOCAL_LOCK_PREFIX = "local:"


def _jail_action_lock_key(action: str, manor_id: int, scope: str) -> str:
    return f"jail:view_lock:{action}:{manor_id}:{scope}"


def _acquire_jail_action_lock(action: str, manor_id: int, scope: str) -> tuple[bool, str, str | None]:
    key = _jail_action_lock_key(action, manor_id, scope)
    acquired, from_cache, lock_token = acquire_best_effort_lock(
        key,
        timeout_seconds=JAIL_ACTION_LOCK_SECONDS,
        logger=logger,
        log_context="jail action lock",
    )
    if not acquired:
        return False, "", None
    if from_cache:
        return True, key, lock_token
    return True, f"{_LOCAL_LOCK_PREFIX}{key}", lock_token


def _release_jail_action_lock(lock_key: str, lock_token: str | None) -> None:
    if not lock_key:
        return
    if lock_key.startswith(_LOCAL_LOCK_PREFIX):
        release_best_effort_lock(
            lock_key[len(_LOCAL_LOCK_PREFIX) :],
            from_cache=False,
            lock_token=lock_token,
            logger=logger,
            log_context="jail action lock",
        )
        return
    release_best_effort_lock(
        lock_key,
        from_cache=True,
        lock_token=lock_token,
        logger=logger,
        log_context="jail action lock",
    )


def _oath_guest_id_from_json_or_error(request: HttpRequest) -> tuple[int | None, JsonResponse | None]:
    data = parse_json_object(request.body, empty_as_object=True)
    if data is None:
        return None, json_error("无效的请求数据")
    guest_id = safe_positive_int(data.get("guest_id"), default=None)
    if guest_id is None:
        return None, json_error("请指定门客")
    return guest_id, None


class JailView(LoginRequiredMixin, TemplateView):
    template_name = "gameplay/jail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        prisoners = list_held_prisoners(manor)
        context.update(
            {
                "manor": manor,
                "jail_capacity": int(getattr(manor, "jail_capacity", 0) or 0),
                "prisoners": prisoners,
                "capture_rate_percent": int(round(get_raid_capture_guest_rate() * 100)),
                "recruit_loyalty_threshold": int(PVPConstants.JAIL_RECRUIT_LOYALTY_THRESHOLD),
                "recruit_cost_gold_bar": int(PVPConstants.JAIL_RECRUIT_GOLD_BAR_COST),
            }
        )
        return context


class OathGroveView(LoginRequiredMixin, TemplateView):
    template_name = "gameplay/oath_grove.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        bonds = list_oath_bonds(manor)
        oathed_ids = {b.guest_id for b in bonds}
        available_guests = (
            manor.guests.select_related("template")
            .exclude(id__in=oathed_ids)
            .annotate(_template_rarity_rank=guest_template_rarity_rank_case("template__rarity"))
            .order_by("-_template_rarity_rank", "-level", "id")
        )
        context.update(
            {
                "manor": manor,
                "oath_capacity": int(getattr(manor, "oath_capacity", 0) or 0),
                "bonds": bonds,
                "available_guests": list(available_guests)[:50],
            }
        )
        return context


@login_required
def jail_status_api(request: HttpRequest) -> JsonResponse:
    manor = ensure_manor(request.user)
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
    manor = ensure_manor(request.user)
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
def recruit_prisoner_view(request: HttpRequest, prisoner_id: int):
    manor = ensure_manor(request.user)
    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("recruit_view", int(manor.id), str(prisoner_id))
    if not lock_ok:
        messages.warning(request, "请求处理中，请稍候重试")
        return redirect("gameplay:jail")

    try:
        try:
            guest = recruit_prisoner(manor, int(prisoner_id))
            messages.success(request, f"成功招募：{guest.display_name}（等级已重置，装备已清空）")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected jail recruit error: manor_id=%s prisoner_id=%s",
                getattr(manor, "id", None),
                prisoner_id,
            )
            messages.error(request, sanitize_error_message(exc))
    finally:
        _release_jail_action_lock(lock_key, lock_token)
    return redirect("gameplay:jail")


@login_required
@require_POST
def draw_pie_view(request: HttpRequest, prisoner_id: int):
    manor = ensure_manor(request.user)
    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("draw_pie_view", int(manor.id), str(prisoner_id))
    if not lock_ok:
        messages.warning(request, "请求处理中，请稍候重试")
        return redirect("gameplay:jail")

    try:
        try:
            prisoner = draw_pie(manor, int(prisoner_id))
            reduction = 0
            if hasattr(prisoner, "_reduction"):
                reduction = prisoner._reduction
            messages.success(request, f"画饼成功！{prisoner.display_name} 忠诚度 -{reduction}")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected jail draw_pie error: manor_id=%s prisoner_id=%s",
                getattr(manor, "id", None),
                prisoner_id,
            )
            messages.error(request, sanitize_error_message(exc))
    finally:
        _release_jail_action_lock(lock_key, lock_token)
    return redirect("gameplay:jail")


@login_required
@require_POST
def release_prisoner_view(request: HttpRequest, prisoner_id: int):
    manor = ensure_manor(request.user)
    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("release_view", int(manor.id), str(prisoner_id))
    if not lock_ok:
        messages.warning(request, "请求处理中，请稍候重试")
        return redirect("gameplay:jail")

    try:
        try:
            prisoner = release_prisoner(manor, int(prisoner_id))
            messages.success(request, f"已释放：{prisoner.display_name}")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected jail release error: manor_id=%s prisoner_id=%s",
                getattr(manor, "id", None),
                prisoner_id,
            )
            messages.error(request, sanitize_error_message(exc))
    finally:
        _release_jail_action_lock(lock_key, lock_token)
    return redirect("gameplay:jail")


@login_required
@require_POST
def add_oath_bond_view(request: HttpRequest):
    manor = ensure_manor(request.user)
    guest_id = safe_positive_int(request.POST.get("guest_id"), default=None)
    if guest_id is None:
        messages.error(request, "请指定门客")
        return redirect("gameplay:oath_grove")
    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("oath_add_view", int(manor.id), str(guest_id))
    if not lock_ok:
        messages.warning(request, "请求处理中，请稍候重试")
        return redirect("gameplay:oath_grove")

    try:
        try:
            bond = add_oath_bond(manor, guest_id)
            messages.success(request, f"结义成功：{bond.guest.display_name}")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected oath add error: manor_id=%s guest_id=%s",
                getattr(manor, "id", None),
                guest_id,
            )
            messages.error(request, sanitize_error_message(exc))
    finally:
        _release_jail_action_lock(lock_key, lock_token)
    return redirect("gameplay:oath_grove")


@login_required
@require_POST
def remove_oath_bond_view(request: HttpRequest, guest_id: int):
    manor = ensure_manor(request.user)
    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("oath_remove_view", int(manor.id), str(guest_id))
    if not lock_ok:
        messages.warning(request, "请求处理中，请稍候重试")
        return redirect("gameplay:oath_grove")

    try:
        try:
            deleted = remove_oath_bond(manor, int(guest_id))
            if not deleted:
                messages.error(request, "该门客未结义")
            else:
                messages.success(request, "已解除结义")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected oath remove error: manor_id=%s guest_id=%s",
                getattr(manor, "id", None),
                guest_id,
            )
            messages.error(request, sanitize_error_message(exc))
    finally:
        _release_jail_action_lock(lock_key, lock_token)
    return redirect("gameplay:oath_grove")


@login_required
@require_POST
@rate_limit_json("jail_recruit", limit=10, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def recruit_prisoner_api(request: HttpRequest, prisoner_id: int) -> JsonResponse:
    manor = ensure_manor(request.user)
    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("recruit_api", int(manor.id), str(prisoner_id))
    if not lock_ok:
        return json_error("请求处理中，请稍候重试", status=409)

    try:
        try:
            guest = recruit_prisoner(manor, int(prisoner_id))
            return json_success(message=f"成功招募：{guest.display_name}（等级已重置，装备已清空）", guest_id=guest.id)
        except (GameError, ValueError) as exc:
            return json_error(sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected jail recruit API error: manor_id=%s prisoner_id=%s",
                getattr(manor, "id", None),
                prisoner_id,
            )
            return json_error(sanitize_error_message(exc), status=500)
    finally:
        _release_jail_action_lock(lock_key, lock_token)


@login_required
@require_POST
@rate_limit_json("jail_draw_pie", limit=30, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def draw_pie_api(request: HttpRequest, prisoner_id: int) -> JsonResponse:
    manor = ensure_manor(request.user)
    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("draw_pie_api", int(manor.id), str(prisoner_id))
    if not lock_ok:
        return json_error("请求处理中，请稍候重试", status=409)

    try:
        try:
            prisoner = draw_pie(manor, int(prisoner_id))
            reduction = getattr(prisoner, "_reduction", 0)
            return json_success(
                message=f"画饼成功！{prisoner.display_name} 忠诚度 -{reduction}",
                prisoner_id=prisoner.id,
                new_loyalty=prisoner.loyalty,
                reduction=reduction,
            )
        except (GameError, ValueError) as exc:
            return json_error(sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected jail draw_pie API error: manor_id=%s prisoner_id=%s",
                getattr(manor, "id", None),
                prisoner_id,
            )
            return json_error(sanitize_error_message(exc), status=500)
    finally:
        _release_jail_action_lock(lock_key, lock_token)


@login_required
@require_POST
@rate_limit_json("jail_release", limit=20, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def release_prisoner_api(request: HttpRequest, prisoner_id: int) -> JsonResponse:
    manor = ensure_manor(request.user)
    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("release_api", int(manor.id), str(prisoner_id))
    if not lock_ok:
        return json_error("请求处理中，请稍候重试", status=409)

    try:
        try:
            prisoner = release_prisoner(manor, int(prisoner_id))
            return json_success(message=f"已释放：{prisoner.display_name}", prisoner_id=prisoner.id)
        except (GameError, ValueError) as exc:
            return json_error(sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected jail release API error: manor_id=%s prisoner_id=%s",
                getattr(manor, "id", None),
                prisoner_id,
            )
            return json_error(sanitize_error_message(exc), status=500)
    finally:
        _release_jail_action_lock(lock_key, lock_token)


@login_required
@require_POST
@rate_limit_json("oath_add", limit=10, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def add_oath_bond_api(request: HttpRequest) -> JsonResponse:
    manor = ensure_manor(request.user)
    guest_id, error = _oath_guest_id_from_json_or_error(request)
    if error is not None:
        return error
    if guest_id is None:
        return json_error("请指定门客")

    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("oath_add_api", int(manor.id), str(guest_id))
    if not lock_ok:
        return json_error("请求处理中，请稍候重试", status=409)

    try:
        try:
            bond = add_oath_bond(manor, guest_id)
            return json_success(message=f"结义成功：{bond.guest.display_name}")
        except (GameError, ValueError) as exc:
            return json_error(sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected oath add API error: manor_id=%s guest_id=%s",
                getattr(manor, "id", None),
                guest_id,
            )
            return json_error(sanitize_error_message(exc), status=500)
    finally:
        _release_jail_action_lock(lock_key, lock_token)


@login_required
@require_POST
@rate_limit_json("oath_remove", limit=10, window_seconds=60, error_message="操作过于频繁，请稍后再试")
def remove_oath_bond_api(request: HttpRequest) -> JsonResponse:
    manor = ensure_manor(request.user)
    guest_id, error = _oath_guest_id_from_json_or_error(request)
    if error is not None:
        return error
    if guest_id is None:
        return json_error("请指定门客")

    lock_ok, lock_key, lock_token = _acquire_jail_action_lock("oath_remove_api", int(manor.id), str(guest_id))
    if not lock_ok:
        return json_error("请求处理中，请稍候重试", status=409)

    try:
        try:
            deleted = remove_oath_bond(manor, guest_id)
            if not deleted:
                return json_error("该门客未结义")
            return json_success(message="已解除结义")
        except (GameError, ValueError) as exc:
            return json_error(sanitize_error_message(exc))
        except Exception as exc:
            logger.exception(
                "Unexpected oath remove API error: manor_id=%s guest_id=%s",
                getattr(manor, "id", None),
                guest_id,
            )
            return json_error(sanitize_error_message(exc), status=500)
    finally:
        _release_jail_action_lock(lock_key, lock_token)
