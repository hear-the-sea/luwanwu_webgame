"""
门客物品使用视图：药品等
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.exceptions import GameError
from core.utils import is_ajax_request, json_error, json_success
from core.utils.validation import safe_redirect_url, sanitize_error_message

from ..models import Guest


@login_required
@require_POST
def use_medicine_item_view(request, pk: int):
    """
    使用药品视图

    注意：此视图有自定义的 AJAX 响应格式，不使用统一装饰器
    但使用 manager 方法简化查询
    """
    from gameplay.models import InventoryItem, ItemTemplate
    from gameplay.services.inventory import consume_inventory_item
    from gameplay.services.manor.core import ensure_manor

    from ..services import heal_guest

    manor = ensure_manor(request.user)
    # 使用 manager 方法获取门客，避免重复的 select_related
    guest = get_object_or_404(Guest.objects.for_manor(manor).with_template(), pk=pk)
    item_id = request.POST.get("item_id")
    is_ajax = is_ajax_request(request)
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
            # 刷新门客数据以获取最新HP和状态
            guest.refresh_from_db()
            return json_success(
                message=msg,
                item_id=item_id,
                new_quantity=new_quantity,
                guest_id=guest.pk,
                current_hp=guest.current_hp,
                max_hp=guest.max_hp,
                status=guest.status,
                status_display=guest.get_status_display(),
            )
        messages.success(request, msg)
    except (GameError, ValueError) as exc:
        error_msg = sanitize_error_message(exc)
        if is_ajax:
            return json_error(error_msg, status=200, include_message=True)
        messages.error(request, error_msg)
    except ObjectDoesNotExist:
        # 物品可能已被删除（refresh_from_db 时）
        if is_ajax:
            return json_success(
                message="药品已使用",
                item_id=item_id,
                new_quantity=0,
            )
    return redirect(next_url)
