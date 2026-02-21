"""
仓库和物品管理视图
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import is_ajax_request, json_error, json_success, safe_int, safe_positive_int, sanitize_error_message
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
    use_xidianka,
    use_xisuidan,
)


def _parse_positive_quantity(raw_quantity: str | None, default: int = 1) -> int | None:
    """Parse quantity from user input, allowing empty to fall back to default."""
    if raw_quantity is None or raw_quantity == "":
        return default
    return safe_positive_int(raw_quantity, default=None)


def _warehouse_item(manor, pk: int) -> InventoryItem:
    return get_object_or_404(
        manor.inventory_items.select_related("template"),
        pk=pk,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )


def _error_response(
    request: HttpRequest, is_ajax: bool, error: str, redirect_url: str = "gameplay:warehouse"
) -> HttpResponse:
    if is_ajax:
        return json_error(error, status=200)
    messages.error(request, error)
    return redirect(redirect_url)


def _move_item_between_storage(
    request: HttpRequest,
    pk: int,
    *,
    move_func: Callable[[Any, int, int], None],
    success_message: Callable[[int], str],
    redirect_url: str,
) -> HttpResponse:
    manor = ensure_manor(request.user)
    quantity = _parse_positive_quantity(request.POST.get("quantity"), default=1)
    is_ajax = is_ajax_request(request)
    if quantity is None:
        return _error_response(request, is_ajax, "数量参数无效", redirect_url=redirect_url)

    try:
        move_func(manor, pk, quantity)
        message = success_message(quantity)
        if is_ajax:
            return json_success(message=message)
        messages.success(request, message)
    except ValueError as exc:
        return _error_response(request, is_ajax, sanitize_error_message(exc), redirect_url=redirect_url)

    return redirect(redirect_url)


def _use_target_guest_item(
    request: HttpRequest,
    pk: int,
    *,
    expected_action: str,
    missing_guest_error: str,
    success_fallback_message: Callable[[Mapping[str, Any]], str],
    service_call: Callable[[Any, InventoryItem, int], Mapping[str, Any]],
) -> HttpResponse:
    manor = ensure_manor(request.user)
    item = _warehouse_item(manor, pk)
    is_ajax = is_ajax_request(request)

    payload = item.template.effect_payload or {}
    if payload.get("action") != expected_action:
        return _error_response(request, is_ajax, "物品类型错误")

    guest_id = safe_positive_int(request.POST.get("guest_id"), default=None)
    if guest_id is None:
        return _error_response(request, is_ajax, missing_guest_error)

    try:
        result = service_call(manor, item, guest_id)
        message = str(result.get("_message") or success_fallback_message(result))
        if is_ajax:
            return json_success(message=message)
        messages.success(request, message)
    except (GameError, ValueError) as exc:
        return _error_response(request, is_ajax, sanitize_error_message(exc))

    return redirect("gameplay:warehouse")


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
        page = safe_int(self.request.GET.get("page", 1), default=1, min_val=1)
        context.update(get_warehouse_context(manor, current_tab, selected_category, page))
        return context


@login_required
@require_POST
@rate_limit_redirect("use_item", limit=20, window_seconds=60)
def use_item_view(request: HttpRequest, pk: int) -> HttpResponse:
    """使用物品"""
    manor = ensure_manor(request.user)
    item = _warehouse_item(manor, pk)
    is_ajax = is_ajax_request(request)
    try:
        # 传入manor参数进行安全校验
        payload = use_inventory_item(item, manor=manor)
        # 优先使用 _message 字段作为人类友好的提示
        if "_message" in payload:
            summary = payload["_message"]
        else:
            summary = (
                "、".join(f"{key}+{value}" for key, value in payload.items() if not key.startswith("_")) or "效果已生效"
            )
        if is_ajax:
            return json_success(message=f"{item.template.name} 使用成功：{summary}")
        messages.success(request, f"{item.template.name} 使用成功：{summary}")
    except (GameError, ValueError) as exc:
        return _error_response(request, is_ajax, sanitize_error_message(exc))
    return redirect("gameplay:warehouse")


@login_required
@require_POST
@rate_limit_redirect("move_to_treasury", limit=30, window_seconds=60)
def move_item_to_treasury_view(request: HttpRequest, pk: int) -> HttpResponse:
    """将物品从仓库移动到藏宝阁"""
    from gameplay.services import move_item_to_treasury

    return _move_item_between_storage(
        request,
        pk,
        move_func=move_item_to_treasury,
        success_message=lambda quantity: f"已将 {quantity} 个物品移动到藏宝阁",
        redirect_url=reverse("gameplay:warehouse"),
    )


@login_required
@require_POST
@rate_limit_redirect("move_to_warehouse", limit=30, window_seconds=60)
def move_item_to_warehouse_view(request: HttpRequest, pk: int) -> HttpResponse:
    """将物品从藏宝阁移动到仓库"""
    from gameplay.services import move_item_to_warehouse

    return _move_item_between_storage(
        request,
        pk,
        move_func=move_item_to_warehouse,
        success_message=lambda quantity: f"已将 {quantity} 个物品移动到仓库",
        redirect_url=f"{reverse('gameplay:warehouse')}?tab=treasury",
    )


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
    return _use_target_guest_item(
        request,
        pk,
        expected_action="rebirth_guest",
        missing_guest_error="请选择要重生的门客",
        success_fallback_message=lambda result: f"门客 {result.get('guest_name', '')} 已重生为1级",
        service_call=use_guest_rebirth_card,
    )


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
    return _use_target_guest_item(
        request,
        pk,
        expected_action="reroll_growth",
        missing_guest_error="请选择要洗髓的门客",
        success_fallback_message=lambda _result: "洗髓完成",
        service_call=use_xisuidan,
    )


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
    return _use_target_guest_item(
        request,
        pk,
        expected_action="reset_allocation",
        missing_guest_error="请选择要洗点的门客",
        success_fallback_message=lambda _result: "洗点完成",
        service_call=use_xidianka,
    )
