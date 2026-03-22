"""
门客装备视图：装备、卸下装备
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import DatabaseError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from core.exceptions import EquipmentError, GameError
from core.utils import is_ajax_request, json_error, json_success
from core.utils.rate_limit import rate_limit_redirect
from core.utils.validation import safe_positive_int, safe_redirect_url, sanitize_error_message
from gameplay.services.utils.cache_exceptions import CACHE_INFRASTRUCTURE_EXCEPTIONS

from ..forms import EquipForm
from ..models import GearSlot, Guest
from ..services import equipment as equipment_service
from ..templatetags.guest_extras import gear_summary, rarity_class, rarity_label
from .common import unexpected_action_error_response

logger = logging.getLogger(__name__)


def _is_expected_cache_error(exc: Exception) -> bool:
    return isinstance(exc, CACHE_INFRASTRUCTURE_EXCEPTIONS)


def _safe_cache_get(key: str):
    try:
        return cache.get(key)
    except Exception as exc:
        if not _is_expected_cache_error(exc):
            raise
        logger.warning("Gear options cache.get failed: key=%s error=%s", key, exc, exc_info=True)
        return None


def _safe_cache_set(key: str, value, timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception as exc:
        if not _is_expected_cache_error(exc):
            raise
        logger.warning("Gear options cache.set failed: key=%s error=%s", key, exc, exc_info=True)


def _safe_cache_delete_many(keys: list[str]) -> None:
    try:
        cache.delete_many(keys)
    except Exception as exc:
        if not _is_expected_cache_error(exc):
            raise
        logger.warning("Gear options cache.delete_many failed: keys_count=%s error=%s", len(keys), exc, exc_info=True)


def _best_effort_clear_gear_options_cache(manor_id: int, *, slots: set[str] | None = None) -> None:
    try:
        _clear_gear_options_cache(manor_id, slots=slots)
    except Exception as exc:
        if not _is_expected_cache_error(exc):
            raise
        logger.warning(
            "Gear options cache invalidation skipped: manor_id=%s slots=%s error=%s",
            manor_id,
            sorted(slots) if slots else None,
            exc,
            exc_info=True,
        )


@login_required
@require_POST
@rate_limit_redirect("equip", limit=15, window_seconds=60)
def equip_view(request):
    """
    装备视图

    手动收口业务 / 基础设施异常，避免继续吞裸 ValueError
    """
    from gameplay.services.manor.core import get_manor

    manor = get_manor(request.user)

    try:
        slot = request.POST.get("slot") or ""
        form = EquipForm(request.POST, manor=manor)

        if not form.is_valid():
            raise EquipmentError("请选择门客与可用装备")

        guest = form.cleaned_data["guest"]
        gear = equipment_service.resolve_equippable_gear(
            manor,
            form.cleaned_data["gear"],
            slot=slot or None,
        )

        equipment_service.equip_guest(gear, guest)
        _best_effort_clear_gear_options_cache(manor.id, slots={gear.template.slot})
    except GameError as exc:
        error_msg = sanitize_error_message(exc)
        if is_ajax_request(request):
            return json_error(error_msg, status=400, include_message=True)
        messages.error(request, error_msg)
        return redirect("gameplay:recruitment_hall")
    except DatabaseError as exc:
        logger.exception(
            "Unexpected equip view database error: manor_id=%s user_id=%s slot=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            request.POST.get("slot"),
        )
        error_msg = sanitize_error_message(exc)
        if is_ajax_request(request):
            return json_error(error_msg, status=500, include_message=True)
        messages.error(request, error_msg)
        return redirect("gameplay:recruitment_hall")
    except Exception as exc:
        logger.exception(
            "Unexpected equip view error: manor_id=%s user_id=%s slot=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            request.POST.get("slot"),
        )
        return unexpected_action_error_response(
            request,
            exc,
            is_ajax=is_ajax_request(request),
            redirect_to="gameplay:recruitment_hall",
        )

    # AJAX 请求返回 JSON 响应
    if is_ajax_request(request):
        return json_success(message=f"{guest.display_name} 已装备 {gear.template.name}")

    messages.success(request, f"{guest.display_name} 已装备 {gear.template.name}")
    return redirect("guests:detail", pk=guest.pk)


@login_required
@require_POST
@rate_limit_redirect("unequip", limit=20, window_seconds=60)
def unequip_view(request):
    """
    卸下装备视图

    由于有复杂的验证逻辑，保持手动错误处理
    但使用 manager 方法简化查询
    """
    from gameplay.services.manor.core import get_manor

    manor = get_manor(request.user)
    guest_id = safe_positive_int(request.POST.get("guest"), default=None)
    raw_gear_ids = request.POST.getlist("gear")
    default_url = "guests:roster"
    next_url = safe_redirect_url(request, request.POST.get("next"), default_url)
    if next_url == default_url:
        next_url = safe_redirect_url(request, request.META.get("HTTP_REFERER"), default_url)

    if guest_id is None:
        messages.error(request, "参数错误")
        return redirect(next_url)

    # 使用 manager 方法获取门客，避免重复的 select_related
    guest = get_object_or_404(Guest.objects.for_manor(manor).with_template(), pk=guest_id)

    if not raw_gear_ids:
        messages.warning(request, "请先勾选需要卸下的装备")
        return redirect(next_url)

    gear_ids: list[int] = []
    seen: set[int] = set()
    for raw_gear_id in raw_gear_ids:
        gear_id = safe_positive_int(raw_gear_id, default=None)
        if gear_id is None:
            messages.error(request, "装备选择有误")
            return redirect(next_url)
        if gear_id in seen:
            continue
        seen.add(gear_id)
        gear_ids.append(gear_id)

    gears = list(manor.gears.select_related("template", "guest").filter(pk__in=gear_ids))
    if not gears:
        messages.error(request, "未找到需要卸下的装备")
        return redirect(next_url)

    invalid = [g for g in gears if g.guest_id != guest.id]
    if invalid:
        messages.error(request, "存在不属于该门客的装备，无法卸下")
        return redirect(next_url)

    try:
        removed = 0
        changed_slots = set()
        for gear in gears:
            equipment_service.unequip_guest_item(gear, guest)
            changed_slots.add(gear.template.slot)
            removed += 1
        if removed:
            messages.success(request, f"{guest.display_name} 卸下 {removed} 件装备")
            _best_effort_clear_gear_options_cache(manor.id, slots=changed_slots)
        else:
            messages.info(request, "没有可卸下的装备")
    except GameError as exc:
        messages.error(request, sanitize_error_message(exc))
    except DatabaseError as exc:
        logger.exception(
            "Unexpected unequip view database error: manor_id=%s user_id=%s guest_id=%s gear_count=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            guest_id,
            len(gear_ids),
        )
        messages.error(request, sanitize_error_message(exc))
    except Exception:
        logger.exception(
            "Unexpected unequip view error: manor_id=%s user_id=%s guest_id=%s gear_count=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            guest_id,
            len(gear_ids),
        )
        raise
    return redirect(next_url)


@login_required
@require_GET
def gear_options_view(request):
    from gameplay.services.manor.core import get_manor
    from gameplay.services.utils.cache import CACHE_TIMEOUT_SHORT

    manor = get_manor(request.user)
    slot = request.GET.get("slot")
    slot_label_map = dict(GearSlot.choices)
    if not slot or slot not in slot_label_map:
        return JsonResponse({"error": "invalid_slot"}, status=400)

    cache_key = _gear_options_cache_key(manor.id, slot)
    cached = _safe_cache_get(cache_key)
    if cached is not None:
        return JsonResponse(cached)

    options = []
    for entry in equipment_service.list_available_equippable_gear_options(manor, slot=slot):
        template = entry["template"]
        rarity = template.rarity
        options.append(
            {
                "id": entry["id"],
                "template_key": entry["template_key"],
                "name": template.name,
                "rarity": rarity,
                "rarity_label": rarity_label(rarity),
                "rarity_class": rarity_class(rarity),
                "count": entry["count"],
                "title": gear_summary(template),
            }
        )
    payload = {
        "slot": slot,
        "slot_label": slot_label_map.get(slot, ""),
        "options": options,
    }
    _safe_cache_set(cache_key, payload, timeout=CACHE_TIMEOUT_SHORT)
    return JsonResponse(payload)


def _clear_gear_options_cache(manor_id: int, slots: set[str] | None = None) -> None:
    slot_values = slots or {choice.value for choice in GearSlot}
    keys = [_gear_options_cache_key(manor_id, value) for value in slot_values]
    _safe_cache_delete_many(keys)


def _gear_options_cache_key(manor_id: int, slot: str) -> str:
    return f"gear_options:{manor_id}:{slot}"
