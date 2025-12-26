"""
门客培养视图：训练、经验道具、属性加点
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import safe_redirect_url, sanitize_error_message
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services import ensure_manor, consume_inventory_item

from ..forms import AllocateSkillPointsForm, TrainGuestForm
from ..services import (
    allocate_attribute_points,
    train_guest,
    reduce_training_time_for_guest,
)


@method_decorator(require_POST, name="dispatch")
class TrainView(LoginRequiredMixin, TemplateView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        manor = ensure_manor(request.user)
        form = TrainGuestForm(request.POST, manor=manor)
        default_url = "gameplay:recruitment_hall"
        next_url = safe_redirect_url(request, request.POST.get("next"), default_url)
        if not form.is_valid():
            messages.error(request, "培养参数有误")
            return redirect(next_url)
        guest = form.cleaned_data["guest"]
        levels = form.cleaned_data["levels"]
        try:
            train_guest(guest, levels)
            eta = guest.training_complete_at
            eta_str = eta.strftime("%H:%M:%S") if eta else ""
            messages.success(request, f"{guest.display_name} 正在升级，预计 {eta_str} 完成")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
        return redirect(next_url)


@login_required
@require_POST
def use_experience_item_view(request, pk: int):
    manor = ensure_manor(request.user)
    guest = get_object_or_404(manor.guests.select_related("template"), pk=pk)
    item_id = request.POST.get("item_id")
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    default_url = reverse("guests:detail", args=[guest.pk])
    next_url = safe_redirect_url(request, request.POST.get("next"), default_url)
    item = get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=item_id,
        template__effect_type=ItemTemplate.EffectType.EXPERIENCE_ITEM,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    try:
        payload = item.template.effect_payload or {}
        reduce_seconds = int(payload.get("time", 0))
        if reduce_seconds <= 0:
            raise ValueError("道具未配置有效时间")
        result = reduce_training_time_for_guest(guest, reduce_seconds)
        # consume item
        consume_inventory_item(item)
        # 重新获取物品数量和门客最新状态
        item.refresh_from_db()
        guest.refresh_from_db()
        new_quantity = item.quantity if item.pk else 0
        reduced_hours = round(result.get("time_reduced", 0) / 3600, 2)
        eta = guest.training_complete_at
        eta_str = eta.strftime("%H:%M:%S") if eta else "已完成升级"
        msg = f"{item.template.name} 已使用，缩短 {reduced_hours} 小时。预计完成：{eta_str}"
        if is_ajax:
            return JsonResponse({
                "success": True,
                "message": msg,
                "item_id": item_id,
                "new_quantity": new_quantity,
                "guest_id": guest.pk,
                "new_level": guest.level,
                "current_hp": guest.current_hp,
                "max_hp": guest.max_hp,
                "training_eta": eta.isoformat() if eta else None,
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
                "message": "道具已使用",
                "item_id": item_id,
                "new_quantity": 0,
            })
    return redirect(next_url)


@login_required
@require_POST
def check_training_view(request, pk: int):
    """
    检查门客训练状态，如果已完成则结算训练并返回最新数据。

    用于前端倒计时结束后主动检查，避免页面刷新时数据未更新的问题。
    """
    from ..services import finalize_guest_training

    manor = ensure_manor(request.user)
    guest = get_object_or_404(manor.guests.select_related("template"), pk=pk)

    # 尝试完成训练（如果时间已到）
    finalize_guest_training(guest)
    guest.refresh_from_db()

    # 返回最新的门客状态
    return JsonResponse({
        "success": True,
        "guest_id": guest.pk,
        "level": guest.level,
        "current_hp": guest.current_hp,
        "max_hp": guest.max_hp,
        "training_eta": guest.training_complete_at.isoformat() if guest.training_complete_at else None,
        "status": guest.status,
        "attribute_points": guest.attribute_points,
    })


@login_required
@require_POST
def allocate_points_view(request, pk: int):
    manor = ensure_manor(request.user)
    guest = get_object_or_404(manor.guests.select_related("template"), pk=pk)
    form = AllocateSkillPointsForm(request.POST, manor=manor)
    default_url = reverse("guests:detail", args=[guest.pk])
    next_url = safe_redirect_url(request, request.POST.get("next"), default_url)
    if not form.is_valid():
        errors = []
        for field_errors in form.errors.values():
            errors.extend(field_errors)
        messages.error(request, "; ".join(errors) or "加点参数有误")
        return redirect(next_url)
    form_guest = form.cleaned_data["guest"]
    if form_guest.pk != guest.pk:
        messages.error(request, "非法的加点请求")
        return redirect(next_url)
    attribute = form.cleaned_data["attribute"]
    points = form.cleaned_data["points"]
    try:
        allocate_attribute_points(guest, attribute, points)
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    return redirect(next_url)
