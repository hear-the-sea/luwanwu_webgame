"""
门客装备视图：装备、卸下装备
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Count, Min
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from core.decorators import handle_game_errors
from core.exceptions import GameError
from core.utils import is_ajax_request, json_success
from core.utils.rate_limit import rate_limit_redirect
from core.utils.validation import safe_positive_int, safe_redirect_url, sanitize_error_message

from ..forms import EquipForm
from ..models import GearSlot, GearTemplate, Guest
from ..templatetags.guest_extras import gear_summary, rarity_class, rarity_label

logger = logging.getLogger(__name__)


@login_required
@require_POST
@rate_limit_redirect("equip", limit=15, window_seconds=60)
@handle_game_errors(redirect_url="gameplay:recruitment_hall")
def equip_view(request):
    """
    装备视图

    使用统一装饰器处理错误，表单验证失败时抛出 ValueError
    """
    from gameplay.services.manor.core import ensure_manor

    from ..services import ensure_inventory_gears
    from ..services import equip_guest as equip_guest_service

    manor = ensure_manor(request.user)

    slot = request.POST.get("slot") or ""
    ensure_inventory_gears(manor, slot=slot or None)
    form = EquipForm(request.POST, manor=manor)

    if not form.is_valid():
        raise ValueError("请选择门客与可用装备")

    gear = form.cleaned_data["gear"]
    guest = form.cleaned_data["guest"]

    equip_guest_service(gear, guest)
    _clear_gear_options_cache(manor.id, slots={gear.template.slot})

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
    from gameplay.services.manor.core import ensure_manor

    from ..services import unequip_guest_item

    manor = ensure_manor(request.user)
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
            unequip_guest_item(gear, guest)
            changed_slots.add(gear.template.slot)
            removed += 1
        if removed:
            messages.success(request, f"{guest.display_name} 卸下 {removed} 件装备")
            _clear_gear_options_cache(manor.id, slots=changed_slots)
        else:
            messages.info(request, "没有可卸下的装备")
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected unequip view error: manor_id=%s user_id=%s guest_id=%s gear_count=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            guest_id,
            len(gear_ids),
        )
        messages.error(request, sanitize_error_message(exc))
    return redirect(next_url)


@login_required
@require_GET
def gear_options_view(request):
    from gameplay.services.manor.core import ensure_manor
    from gameplay.services.utils.cache import CACHE_TIMEOUT_SHORT

    manor = ensure_manor(request.user)
    slot = request.GET.get("slot")
    slot_label_map = dict(GearSlot.choices)
    if not slot or slot not in slot_label_map:
        return JsonResponse({"error": "invalid_slot"}, status=400)

    cache_key = _gear_options_cache_key(manor.id, slot)
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse(cached)

    from ..services import ensure_inventory_gears

    ensure_inventory_gears(manor, slot=slot)
    rows = (
        manor.gears.filter(guest__isnull=True, template__slot=slot)
        .values("template_id", "template__name", "template__rarity")
        .annotate(count=Count("id"), gear_id=Min("id"))
        .order_by("template__name")
    )
    template_ids = [row["template_id"] for row in rows]
    templates = {
        tpl.id: tpl
        for tpl in GearTemplate.objects.filter(id__in=template_ids).only(
            "id",
            "name",
            "rarity",
            "set_key",
            "set_description",
            "set_bonus",
            "attack_bonus",
            "defense_bonus",
            "extra_stats",
        )
    }
    options = []
    for row in rows:
        template = templates.get(row["template_id"])
        if not template:
            continue
        rarity = row["template__rarity"]
        options.append(
            {
                "id": row["gear_id"],
                "name": row["template__name"],
                "rarity": rarity,
                "rarity_label": rarity_label(rarity),
                "rarity_class": rarity_class(rarity),
                "count": row["count"],
                "title": gear_summary(template),
            }
        )
    payload = {
        "slot": slot,
        "slot_label": slot_label_map.get(slot, ""),
        "options": options,
    }
    cache.set(cache_key, payload, timeout=CACHE_TIMEOUT_SHORT)
    return JsonResponse(payload)


def _gear_options_cache_key(manor_id: int, slot: str) -> str:
    return f"gear_options:{manor_id}:{slot}"


def _clear_gear_options_cache(manor_id: int, slots: set[str] | None = None) -> None:
    slot_values = slots or {choice.value for choice in GearSlot}
    keys = [_gear_options_cache_key(manor_id, value) for value in slot_values]
    cache.delete_many(keys)
