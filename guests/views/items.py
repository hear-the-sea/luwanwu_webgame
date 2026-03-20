"""
门客物品使用视图：药品等
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.exceptions import GameError, GuestItemConfigurationError
from core.utils import is_ajax_request, json_error, json_success, safe_int, safe_positive_int
from core.utils.validation import safe_redirect_url, sanitize_error_message

from ..models import Guest
from ..services.health import use_medicine_item_for_guest
from .common import unexpected_action_error_response

logger = logging.getLogger(__name__)


@login_required
@require_POST
def use_medicine_item_view(request, pk: int):
    """
    使用药品视图

    注意：此视图有自定义的 AJAX 响应格式，不使用统一装饰器
    但使用 manager 方法简化查询
    """
    from gameplay.models import InventoryItem, ItemTemplate
    from gameplay.services.manor.core import get_manor

    manor = get_manor(request.user)
    # 使用 manager 方法获取门客，避免重复的 select_related
    guest = get_object_or_404(Guest.objects.for_manor(manor).with_template(), pk=pk)
    item_id = request.POST.get("item_id")
    is_ajax = is_ajax_request(request)
    default_url = reverse("guests:detail", args=[guest.pk])
    next_url = safe_redirect_url(request, request.POST.get("next"), default_url)
    item_id_int = safe_positive_int(item_id, default=None)
    if item_id_int is None:
        error_msg = "请选择药品道具"
        if is_ajax:
            return json_error(error_msg, status=400, include_message=True)
        messages.error(request, error_msg)
        return redirect(next_url)

    item = get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=item_id_int,
        template__effect_type=ItemTemplate.EffectType.MEDICINE,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    try:
        payload = item.template.effect_payload or {}
        heal_amount = safe_int(payload.get("hp"), default=None)
        if heal_amount is None or heal_amount <= 0:
            raise GuestItemConfigurationError("道具未配置有效恢复值")
        result = use_medicine_item_for_guest(manor, guest, item.pk, heal_amount)
        new_quantity = safe_int(result.get("remaining_item_quantity"), default=0, min_val=0)
        healed = safe_int(result.get("healed"), default=0, min_val=0)
        msg = f"{guest.display_name} 恢复生命 {healed} 点"
        if bool(result.get("injury_cured")):
            msg += "，重伤状态已解除"
        if is_ajax:
            return json_success(
                message=msg,
                item_id=item.pk,
                new_quantity=new_quantity,
                guest_id=guest.pk,
                current_hp=safe_int(result.get("new_hp"), default=guest.current_hp, min_val=0),
                max_hp=safe_int(result.get("max_hp"), default=guest.max_hp, min_val=1),
                guest_status=result.get("status", guest.status),
                status_display=result.get("status_display", guest.get_status_display()),
            )
        messages.success(request, msg)
    except GameError as exc:
        error_msg = sanitize_error_message(exc)
        if is_ajax:
            return json_error(error_msg, status=400, include_message=True)
        messages.error(request, error_msg)
    except DatabaseError as exc:
        logger.exception(
            "Unexpected medicine use view database error: manor_id=%s user_id=%s guest_id=%s item_id=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            pk,
            item_id_int,
        )
        error_msg = sanitize_error_message(exc)
        if is_ajax:
            return json_error(error_msg, status=500, include_message=True)
        messages.error(request, error_msg)
    except Exception as exc:
        logger.exception(
            "Unexpected medicine use view error: manor_id=%s user_id=%s guest_id=%s item_id=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            pk,
            item_id_int,
        )
        return unexpected_action_error_response(request, exc, is_ajax=is_ajax, redirect_to=next_url)
    return redirect(next_url)
