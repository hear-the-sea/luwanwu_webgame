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
from guests.services import list_candidates, list_pools

from ..constants import UIConstants
from ..models import InventoryItem
from ..services import (
    ensure_manor,
    refresh_manor_state,
    use_inventory_item,
)


class RecruitmentHallView(LoginRequiredMixin, TemplateView):
    """招募大厅页面"""

    template_name = "gameplay/recruitment_hall.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)
        context["manor"] = manor
        context["pools"] = list_pools(core_only=True)
        context["candidates"] = list_candidates(manor)
        context["records"] = manor.recruit_records.select_related("guest", "pool")[:UIConstants.RECRUIT_RECORDS_DISPLAY]
        # 预加载门客列表并复用，避免重复查询
        guests_qs = manor.guests.select_related("template").prefetch_related("gear_items__template")
        guests_list = list(guests_qs)
        context["guests"] = guests_list
        # 复用已加载的列表计算数量
        context["capacity"] = (len(guests_list), manor.guest_capacity)
        context["retainer_capacity"] = (manor.retainer_count, manor.retainer_capacity)
        context["available_gears"] = manor.gears.filter(guest__isnull=True).select_related("template")
        # 获取放大镜道具
        magnifying_glass_items = manor.inventory_items.filter(
            template__key="fangdajing",
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        ).select_related("template")
        context["magnifying_glass_items"] = list(magnifying_glass_items)
        return context


class WarehouseView(LoginRequiredMixin, TemplateView):
    """仓库页面"""

    template_name = "gameplay/warehouse.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)
        context["manor"] = manor

        # Get frozen gold bars for display adjustment
        from trade.services.auction_service import get_frozen_gold_bars

        context["frozen_gold_bars"] = get_frozen_gold_bars(manor)

        # active tab
        current_tab = self.request.GET.get("tab", "warehouse")
        context["current_tab"] = current_tab

        # category filter
        selected_category = self.request.GET.get("category", "all")
        tool_effect_types = {"tool", "magnifying_glass", "peace_shield", "manor_rename"}
        tool_category_key = "tool"
        if selected_category == "tools":  # 兼容旧参数
            selected_category = tool_category_key

        if current_tab == "treasury":
            items = manor.inventory_items.filter(
                storage_location=InventoryItem.StorageLocation.TREASURY,
                quantity__gt=0
            ).select_related("template").order_by("template__name")

            from ..services import get_treasury_capacity, get_treasury_used_space
            treasury_capacity = get_treasury_capacity(manor)
            treasury_used = get_treasury_used_space(manor)
            context["treasury_capacity"] = treasury_capacity
            context["treasury_used"] = treasury_used
            context["treasury_remaining"] = treasury_capacity - treasury_used
        else:
            items = manor.inventory_items.filter(
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                quantity__gt=0
            ).select_related("template").order_by("template__name")

        all_items = items
        if selected_category != "all":
            if selected_category in tool_effect_types:
                selected_category = tool_category_key
                items = items.filter(template__effect_type__in=tool_effect_types)
            else:
                items = items.filter(template__effect_type=selected_category)

        categories = []
        seen = set()
        has_tools = False
        for entry in all_items:
            key = entry.template.effect_type or "other"
            if key in tool_effect_types:
                has_tools = True
                continue
            label = entry.category_display or key
            if key not in seen:
                seen.add(key)
                categories.append({"key": key, "label": label})
        if has_tools:
            categories.append({"key": tool_category_key, "label": "道具"})
        categories.sort(key=lambda x: x["label"])

        # Process items to add display_quantity (adjusting gold_bar for frozen amount)
        # Only adjust for warehouse tab, treasury items are not affected by frozen gold
        frozen_gold = context["frozen_gold_bars"] if current_tab == "warehouse" else 0
        items_list = list(items)
        for item in items_list:
            if item.template.key == "gold_bar" and frozen_gold > 0:
                item.display_quantity = max(0, item.quantity - frozen_gold)
            else:
                item.display_quantity = item.quantity

        context["inventory_items"] = items_list
        context["categories"] = categories
        context["selected_category"] = selected_category
        return context


@login_required
@require_POST
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
        payload = use_inventory_item(item)
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
def move_item_to_treasury_view(request: HttpRequest, pk: int) -> HttpResponse:
    """将物品从仓库移动到藏宝阁"""
    manor = ensure_manor(request.user)
    quantity = safe_int(request.POST.get("quantity", 1), default=1, min_val=1)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    try:
        from ..services import move_item_to_treasury
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
def move_item_to_warehouse_view(request: HttpRequest, pk: int) -> HttpResponse:
    """将物品从藏宝阁移动到仓库"""
    manor = ensure_manor(request.user)
    quantity = safe_int(request.POST.get("quantity", 1), default=1, min_val=1)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    try:
        from ..services import move_item_to_warehouse
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
