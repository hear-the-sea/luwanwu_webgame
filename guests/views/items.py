"""
门客物品使用视图：药品等
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.exceptions import GameError
from core.utils import safe_redirect_url, sanitize_error_message
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services import ensure_manor, consume_inventory_item


@login_required
@require_POST
def use_medicine_item_view(request, pk: int):
    from ..services import heal_guest

    manor = ensure_manor(request.user)
    guest = get_object_or_404(manor.guests.select_related("template"), pk=pk)
    item_id = request.POST.get("item_id")
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    default_url = reverse("guests:detail", args=[guest.pk])
    next_url = safe_redirect_url(request, request.POST.get("next"), default_url)
    item = get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=item_id,
        template__effect_type=ItemTemplate.EffectType.MEDICINE,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    try:
        payload = item.template.effect_payload or {}
        heal_amount = int(payload.get("hp", 0))
        result = heal_guest(guest, heal_amount)
        # consume item
        consume_inventory_item(item)
        # 重新获取物品数量
        item.refresh_from_db()
        new_quantity = item.quantity if item.pk else 0
        msg = f"{guest.display_name} 恢复生命 {result['healed']} 点"
        if result["injury_cured"]:
            msg += "，重伤状态已解除"
        if is_ajax:
            return JsonResponse({
                "success": True,
                "message": msg,
                "item_id": item_id,
                "new_quantity": new_quantity,
            })
        messages.success(request, msg)
    except (GameError, ValueError) as exc:
        error_msg = sanitize_error_message(exc)
        if is_ajax:
            return JsonResponse({"success": False, "message": error_msg})
        messages.error(request, error_msg)
    except Exception:
        # 物品可能已被删除
        if is_ajax:
            return JsonResponse({
                "success": True,
                "message": "药品已使用",
                "item_id": item_id,
                "new_quantity": 0,
            })
    return redirect(next_url)
