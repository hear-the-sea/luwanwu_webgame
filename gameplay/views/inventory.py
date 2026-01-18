"""
仓库和物品管理视图
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import safe_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect

from gameplay.constants import UIConstants
from gameplay.models import InventoryItem
from gameplay.selectors.recruitment import get_recruitment_hall_context
from gameplay.selectors.warehouse import get_warehouse_context
from gameplay.services import (
    ensure_manor,
    refresh_manor_state,
    use_guest_rebirth_card,
    use_inventory_item,
    use_xisuidan,
    use_xidianka,
)


class RecruitmentHallView(LoginRequiredMixin, TemplateView):
    """招募大厅页面"""

    template_name = "gameplay/recruitment_hall.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        context.update(get_recruitment_hall_context(manor, UIConstants.RECRUIT_RECORDS_DISPLAY))
        return context


class WarehouseView(LoginRequiredMixin, TemplateView):
    """仓库页面"""

    template_name = "gameplay/warehouse.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)
        context["manor"] = manor

        current_tab = self.request.GET.get("tab", "warehouse")
        selected_category = self.request.GET.get("category", "all")
        context.update(get_warehouse_context(manor, current_tab, selected_category))
        return context


@login_required
@require_POST
@rate_limit_redirect("use_item", limit=20, window_seconds=60)
def use_item_view(request: HttpRequest, pk: int) -> HttpResponse:
    """使用物品"""
    manor = ensure_manor(request.user)
    item = get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=pk,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    try:
        # 传入manor参数进行安全校验
        payload = use_inventory_item(item, manor=manor)
        # 优先使用 _message 字段作为人类友好的提示
        if "_message" in payload:
            summary = payload["_message"]
        else:
            summary = "、".join(f"{key}+{value}" for key, value in payload.items() if not key.startswith("_")) or "效果已生效"
        if is_ajax:
            return JsonResponse({"success": True, "message": f"{item.template.name} 使用成功：{summary}"})
        messages.success(request, f"{item.template.name} 使用成功：{summary}")
    except (GameError, ValueError) as exc:
        if is_ajax:
            return JsonResponse({"success": False, "error": sanitize_error_message(exc)})
        messages.error(request, sanitize_error_message(exc))
    return redirect("gameplay:warehouse")


@login_required
@require_POST
@rate_limit_redirect("move_to_treasury", limit=30, window_seconds=60)
def move_item_to_treasury_view(request: HttpRequest, pk: int) -> HttpResponse:
    """将物品从仓库移动到藏宝阁"""
    manor = ensure_manor(request.user)
    quantity = safe_int(request.POST.get("quantity", 1), default=1, min_val=1)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    try:
        from gameplay.services import move_item_to_treasury
        move_item_to_treasury(manor, pk, quantity)
        if is_ajax:
            return JsonResponse({"success": True, "message": f"已将 {quantity} 个物品移动到藏宝阁"})
        messages.success(request, f"已将 {quantity} 个物品移动到藏宝阁")
    except ValueError as exc:
        if is_ajax:
            return JsonResponse({"success": False, "error": sanitize_error_message(exc)})
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:warehouse")


@login_required
@require_POST
@rate_limit_redirect("move_to_warehouse", limit=30, window_seconds=60)
def move_item_to_warehouse_view(request: HttpRequest, pk: int) -> HttpResponse:
    """将物品从藏宝阁移动到仓库"""
    manor = ensure_manor(request.user)
    quantity = safe_int(request.POST.get("quantity", 1), default=1, min_val=1)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    try:
        from gameplay.services import move_item_to_warehouse
        move_item_to_warehouse(manor, pk, quantity)
        if is_ajax:
            return JsonResponse({"success": True, "message": f"已将 {quantity} 个物品移动到仓库"})
        messages.success(request, f"已将 {quantity} 个物品移动到仓库")
    except ValueError as exc:
        if is_ajax:
            return JsonResponse({"success": False, "error": sanitize_error_message(exc)})
        messages.error(request, sanitize_error_message(exc))

    # 返回仓库页并定位到 treasury 标签
    return redirect(f"{reverse('gameplay:warehouse')}?tab=treasury")


@login_required
@require_POST
@rate_limit_redirect("use_rebirth_card", limit=10, window_seconds=60)
def use_guest_rebirth_card_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    使用门客重生卡（需要选择目标门客）

    Args:
        pk: 物品ID
        guest_id: 目标门客ID（通过POST传入）
    """
    manor = ensure_manor(request.user)
    item = get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=pk,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # 验证物品类型
    payload = item.template.effect_payload or {}
    if payload.get("action") != "rebirth_guest":
        if is_ajax:
            return JsonResponse({"success": False, "error": "物品类型错误"})
        messages.error(request, "物品类型错误")
        return redirect("gameplay:warehouse")

    # 获取目标门客ID
    from core.utils import safe_int
    guest_id = safe_int(request.POST.get("guest_id"), default=0)
    if not guest_id:
        if is_ajax:
            return JsonResponse({"success": False, "error": "请选择要重生的门客"})
        messages.error(request, "请选择要重生的门客")
        return redirect("gameplay:warehouse")

    try:
        result = use_guest_rebirth_card(manor, item, guest_id)
        message = result.get("_message", f"门客 {result.get('guest_name', '')} 已重生为1级")
        if is_ajax:
            return JsonResponse({"success": True, "message": message})
        messages.success(request, message)
    except (GameError, ValueError) as exc:
        if is_ajax:
            return JsonResponse({"success": False, "error": sanitize_error_message(exc)})
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:warehouse")


@login_required
@require_POST
@rate_limit_redirect("use_xisuidan", limit=10, window_seconds=60)
def use_xisuidan_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    使用洗髓丹（需要选择目标门客）

    Args:
        pk: 物品ID
        guest_id: 目标门客ID（通过POST传入）
    """
    manor = ensure_manor(request.user)
    item = get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=pk,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # 验证物品类型
    payload = item.template.effect_payload or {}
    if payload.get("action") != "reroll_growth":
        if is_ajax:
            return JsonResponse({"success": False, "error": "物品类型错误"})
        messages.error(request, "物品类型错误")
        return redirect("gameplay:warehouse")

    # 获取目标门客ID
    guest_id = safe_int(request.POST.get("guest_id"), default=0)
    if not guest_id:
        if is_ajax:
            return JsonResponse({"success": False, "error": "请选择要洗髓的门客"})
        messages.error(request, "请选择要洗髓的门客")
        return redirect("gameplay:warehouse")

    try:
        result = use_xisuidan(manor, item, guest_id)
        message = result.get("_message", "洗髓完成")
        if is_ajax:
            return JsonResponse({"success": True, "message": message})
        messages.success(request, message)
    except (GameError, ValueError) as exc:
        if is_ajax:
            return JsonResponse({"success": False, "error": sanitize_error_message(exc)})
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:warehouse")


@login_required
@require_POST
@rate_limit_redirect("use_xidianka", limit=10, window_seconds=60)
def use_xidianka_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    使用洗点卡（需要选择目标门客）

    Args:
        pk: 物品ID
        guest_id: 目标门客ID（通过POST传入）
    """
    manor = ensure_manor(request.user)
    item = get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=pk,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # 验证物品类型
    payload = item.template.effect_payload or {}
    if payload.get("action") != "reset_allocation":
        if is_ajax:
            return JsonResponse({"success": False, "error": "物品类型错误"})
        messages.error(request, "物品类型错误")
        return redirect("gameplay:warehouse")

    # 获取目标门客ID
    guest_id = safe_int(request.POST.get("guest_id"), default=0)
    if not guest_id:
        if is_ajax:
            return JsonResponse({"success": False, "error": "请选择要洗点的门客"})
        messages.error(request, "请选择要洗点的门客")
        return redirect("gameplay:warehouse")

    try:
        result = use_xidianka(manor, item, guest_id)
        message = result.get("_message", "洗点完成")
        if is_ajax:
            return JsonResponse({"success": True, "message": message})
        messages.success(request, message)
    except (GameError, ValueError) as exc:
        if is_ajax:
            return JsonResponse({"success": False, "error": sanitize_error_message(exc)})
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:warehouse")
