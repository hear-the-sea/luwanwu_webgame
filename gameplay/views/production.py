"""
生产系统视图：马房、畜牧、冶炼、锻造
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.decorators import flash_unexpected_view_error
from core.exceptions import GameError
from core.utils import safe_positive_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect
from gameplay.constants import UIConstants
from gameplay.services import ensure_manor, get_player_technology_level, refresh_manor_state

logger = logging.getLogger(__name__)


def _parse_positive_quantity(raw_quantity: str | None) -> int | None:
    return safe_positive_int(raw_quantity, default=None)


def _handle_unexpected_production_error(
    request: HttpRequest,
    exc: Exception,
    *,
    log_message: str,
    log_args: tuple[object, ...],
) -> None:
    flash_unexpected_view_error(
        request,
        exc,
        log_message=log_message,
        log_args=log_args,
        logger_instance=logger,
    )


def _run_basic_production_start(
    request: HttpRequest,
    *,
    item_key: str,
    raw_quantity: str | None,
    redirect_name: str,
    missing_key_message: str,
    start_operation: Callable[[object, str, int], Any],
    success_message: Callable[[Any, str], str],
    log_message: str,
) -> HttpResponse:
    manor = ensure_manor(request.user)
    quantity = _parse_positive_quantity(raw_quantity)

    if not item_key:
        messages.error(request, missing_key_message)
        return redirect(redirect_name)
    if quantity is None:
        messages.error(request, "无效的数量")
        return redirect(redirect_name)

    try:
        production = start_operation(manor, item_key, quantity)
        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        messages.success(request, success_message(production, quantity_text))
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        _handle_unexpected_production_error(
            request,
            exc,
            log_message=log_message,
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                item_key,
                raw_quantity,
            ),
        )

    return redirect(redirect_name)


def _normalize_forge_mode(raw_mode: str | None, *, default: str = "synthesize") -> str:
    mode = (raw_mode or default).strip()
    if mode not in {"synthesize", "decompose"}:
        return default
    return mode


def _run_forge_post_action(
    request: HttpRequest,
    *,
    item_key: str,
    raw_quantity: str | None,
    category: str,
    raw_mode: str | None,
    default_mode: str,
    missing_key_message: str,
    operation: Callable[[object, str, int], Any],
    success_message: Callable[[Any], str],
    log_message: str,
) -> HttpResponse:
    manor = ensure_manor(request.user)
    quantity = _parse_positive_quantity(raw_quantity)
    mode = _normalize_forge_mode(raw_mode, default=default_mode)
    redirect_url = _forge_redirect_url(category, mode)

    if not item_key:
        messages.error(request, missing_key_message)
        return redirect(redirect_url)
    if quantity is None:
        messages.error(request, "无效的数量")
        return redirect(redirect_url)

    try:
        result = operation(manor, item_key, quantity)
        messages.success(request, success_message(result))
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        _handle_unexpected_production_error(
            request,
            exc,
            log_message=log_message,
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                item_key,
                raw_quantity,
            ),
        )

    return redirect(redirect_url)


class StableView(LoginRequiredMixin, TemplateView):
    """马房页面"""

    template_name = "gameplay/stable.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)

        from gameplay.services import (
            get_active_productions,
            get_horse_options,
            get_stable_speed_bonus,
            refresh_horse_productions,
        )
        from gameplay.services.buildings.stable import get_max_production_quantity, has_active_production

        # 刷新马匹生产状态
        refresh_horse_productions(manor)

        horsemanship_level = get_player_technology_level(manor, "horsemanship")
        max_quantity = get_max_production_quantity(manor)
        is_producing = has_active_production(manor)

        context["manor"] = manor
        context["horse_options"] = get_horse_options(manor)
        speed_bonus = get_stable_speed_bonus(manor)
        context["active_productions"] = get_active_productions(manor)
        context["speed_bonus"] = speed_bonus
        context["speed_bonus_percent"] = int(speed_bonus * 100)
        context["horsemanship_level"] = horsemanship_level
        context["max_production_quantity"] = max_quantity
        context["is_producing"] = is_producing

        return context


@login_required
@require_POST
@rate_limit_redirect("horse_production", limit=10, window_seconds=60)
def start_horse_production_view(request: HttpRequest) -> HttpResponse:
    """开始马匹生产"""
    from gameplay.services import start_horse_production

    horse_key = (request.POST.get("horse_key") or "").strip()
    return _run_basic_production_start(
        request,
        item_key=horse_key,
        raw_quantity=request.POST.get("quantity"),
        redirect_name="gameplay:stable",
        missing_key_message="请选择马匹类型",
        start_operation=start_horse_production,
        success_message=lambda production, quantity_text: (
            f"{production.horse_name}{quantity_text} 开始生产，预计 {production.actual_duration} 秒后完成"
        ),
        log_message="Unexpected horse production start error: manor_id=%s user_id=%s horse_key=%s quantity=%s",
    )


class RanchView(LoginRequiredMixin, TemplateView):
    """畜牧场页面"""

    template_name = "gameplay/ranch.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)

        from gameplay.services.buildings.ranch import (
            get_active_livestock_productions,
            get_livestock_options,
            get_max_livestock_quantity,
            get_ranch_speed_bonus,
            has_active_livestock_production,
            refresh_livestock_productions,
        )

        # 刷新家畜养殖状态
        refresh_livestock_productions(manor)

        animal_husbandry_level = get_player_technology_level(manor, "animal_husbandry")
        max_quantity = get_max_livestock_quantity(manor)
        is_producing = has_active_livestock_production(manor)

        context["manor"] = manor
        context["livestock_options"] = get_livestock_options(manor)
        speed_bonus = get_ranch_speed_bonus(manor)
        context["active_productions"] = get_active_livestock_productions(manor)
        context["speed_bonus"] = speed_bonus
        context["speed_bonus_percent"] = int(speed_bonus * 100)
        context["animal_husbandry_level"] = animal_husbandry_level
        context["max_livestock_quantity"] = max_quantity
        context["is_producing"] = is_producing

        return context


@login_required
@require_POST
@rate_limit_redirect("livestock_production", limit=10, window_seconds=60)
def start_livestock_production_view(request: HttpRequest) -> HttpResponse:
    """开始家畜养殖"""
    from gameplay.services.buildings.ranch import start_livestock_production

    livestock_key = (request.POST.get("livestock_key") or "").strip()
    return _run_basic_production_start(
        request,
        item_key=livestock_key,
        raw_quantity=request.POST.get("quantity"),
        redirect_name="gameplay:ranch",
        missing_key_message="请选择家畜类型",
        start_operation=start_livestock_production,
        success_message=lambda production, quantity_text: (
            f"{production.livestock_name}{quantity_text} 开始养殖，预计 {production.actual_duration} 秒后完成"
        ),
        log_message="Unexpected livestock production start error: manor_id=%s user_id=%s livestock_key=%s quantity=%s",
    )


class SmithyView(LoginRequiredMixin, TemplateView):
    """冶炼坊页面"""

    template_name = "gameplay/smithy.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)

        from gameplay.services.buildings.smithy import (
            get_active_smelting_productions,
            get_max_smelting_quantity,
            get_metal_options,
            get_smithy_speed_bonus,
            has_active_smelting_production,
            refresh_smelting_productions,
        )

        # 刷新金属冶炼状态
        refresh_smelting_productions(manor)

        smelting_level = get_player_technology_level(manor, "smelting")
        max_quantity = get_max_smelting_quantity(manor)
        is_producing = has_active_smelting_production(manor)

        context["manor"] = manor
        context["metal_options"] = get_metal_options(manor)
        speed_bonus = get_smithy_speed_bonus(manor)
        context["active_productions"] = get_active_smelting_productions(manor)
        context["speed_bonus"] = speed_bonus
        context["speed_bonus_percent"] = int(speed_bonus * 100)
        context["smelting_level"] = smelting_level
        context["max_smelting_quantity"] = max_quantity
        context["is_producing"] = is_producing

        return context


@login_required
@require_POST
@rate_limit_redirect("smelting_production", limit=10, window_seconds=60)
def start_smelting_production_view(request: HttpRequest) -> HttpResponse:
    """开始冶炼坊制作"""
    from gameplay.services.buildings.smithy import start_smelting_production

    metal_key = (request.POST.get("metal_key") or "").strip()
    return _run_basic_production_start(
        request,
        item_key=metal_key,
        raw_quantity=request.POST.get("quantity"),
        redirect_name="gameplay:smithy",
        missing_key_message="请选择物品类型",
        start_operation=start_smelting_production,
        success_message=lambda production, quantity_text: (
            f"{production.metal_name}{quantity_text} 开始制作，预计 {production.actual_duration} 秒后完成"
        ),
        log_message="Unexpected smelting production start error: manor_id=%s user_id=%s metal_key=%s quantity=%s",
    )


class ForgeView(LoginRequiredMixin, TemplateView):
    """铁匠铺装备锻造页面"""

    template_name = "gameplay/forge.html"
    ITEMS_PER_PAGE = UIConstants.FORGE_ITEMS_PER_PAGE
    DECOMPOSE_ITEMS_PER_PAGE = 9

    @staticmethod
    def _sort_equipment_options(equipment_options):
        """装备排序：可锻造优先，其次按需求等级降序。"""
        return sorted(
            equipment_options,
            key=lambda item: (
                item.get("is_unlocked", False) and item.get("can_afford", False),
                item.get("required_forging", 0),
            ),
            reverse=True,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)

        from gameplay.services.buildings.forge import (
            DECOMPOSE_CATEGORIES,
            DECOMPOSE_WEAPON_CATEGORIES,
            get_active_forgings,
            get_blueprint_synthesis_options,
            get_decomposable_equipment_options,
            get_equipment_options,
            get_forge_speed_bonus,
            get_max_forging_quantity,
            has_active_forging,
            infer_equipment_category,
            refresh_equipment_forgings,
            to_decompose_category,
        )

        # 刷新装备锻造状态
        refresh_equipment_forgings(manor)

        forging_level = get_player_technology_level(manor, "forging")
        max_quantity = get_max_forging_quantity(manor)
        is_forging = has_active_forging(manor)

        current_mode = _normalize_forge_mode(self.request.GET.get("mode"), default="synthesize")

        # 获取当前选中的类别（支持"all"表示全部）
        current_category = self.request.GET.get("category", "all")
        if current_category in DECOMPOSE_WEAPON_CATEGORIES:
            current_category = "weapon"
        active_categories = DECOMPOSE_CATEGORIES

        valid_categories = ["all"] + list(active_categories.keys())
        if current_category not in valid_categories:
            current_category = "all"

        # 获取装备列表（按类别过滤或全部）
        if current_category == "all":
            equipment_list = get_equipment_options(manor)
        elif current_category == "weapon":
            equipment_list = [
                opt for opt in get_equipment_options(manor) if opt.get("category") in DECOMPOSE_WEAPON_CATEGORIES
            ]
        else:
            equipment_list = get_equipment_options(manor, category=current_category)
        equipment_list = self._sort_equipment_options(equipment_list)

        # 分页处理
        paginator = Paginator(equipment_list, self.ITEMS_PER_PAGE)
        page_number = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # 构建带"全部"选项的类别字典
        categories_with_all = {"all": "全部"}
        categories_with_all.update(active_categories)

        blueprint_synthesis_options = get_blueprint_synthesis_options(manor)
        for recipe in blueprint_synthesis_options:
            result_category = infer_equipment_category(
                recipe.get("result_key", ""),
                recipe.get("result_effect_type", ""),
            )
            merged_result_category = to_decompose_category(result_category)
            recipe["result_category"] = merged_result_category
            recipe["result_category_name"] = active_categories.get(merged_result_category, merged_result_category)
        if current_category != "all":
            blueprint_synthesis_options = [
                recipe for recipe in blueprint_synthesis_options if recipe.get("result_category") == current_category
            ]

        decompose_category = None if current_category == "all" else current_category
        decomposable_equipment = get_decomposable_equipment_options(manor, category=decompose_category)
        decompose_paginator = Paginator(decomposable_equipment, self.DECOMPOSE_ITEMS_PER_PAGE)
        decompose_page_obj = decompose_paginator.get_page(page_number)

        context["manor"] = manor
        context["current_mode"] = current_mode
        context["equipment_categories"] = categories_with_all
        context["current_category"] = current_category
        context["equipment_list"] = page_obj
        context["page_obj"] = page_obj
        context["decompose_page_obj"] = decompose_page_obj
        context["active_forgings"] = get_active_forgings(manor)
        context["blueprint_synthesis_options"] = blueprint_synthesis_options
        speed_bonus = get_forge_speed_bonus(manor)
        context["decomposable_equipment"] = decompose_page_obj
        context["speed_bonus"] = speed_bonus
        context["speed_bonus_percent"] = int(speed_bonus * 100)
        context["forging_level"] = forging_level
        context["max_forging_quantity"] = max_quantity
        context["is_forging"] = is_forging

        return context


def _forge_redirect_url(category: str, mode: str) -> str:
    return f"{reverse('gameplay:forge')}?mode={mode}&category={category}"


def _build_decompose_reward_text(result: dict[str, Any], item_template_model: Any) -> str:
    reward_map = result.get("rewards", {}) or {}
    reward_templates = {
        template.key: template.name
        for template in item_template_model.objects.filter(key__in=reward_map.keys()).only("key", "name")
    }
    reward_parts = [f"{reward_templates.get(key, key)}x{amount}" for key, amount in reward_map.items() if amount > 0]
    return f"，获得：{'、'.join(reward_parts)}" if reward_parts else ""


@login_required
@require_POST
@rate_limit_redirect("equipment_forging", limit=10, window_seconds=60)
def start_equipment_forging_view(request: HttpRequest) -> HttpResponse:
    """开始装备锻造"""
    from gameplay.services.buildings.forge import start_equipment_forging

    equipment_key = (request.POST.get("equipment_key") or "").strip()
    category = request.POST.get("category", "all")
    return _run_forge_post_action(
        request,
        item_key=equipment_key,
        raw_quantity=request.POST.get("quantity"),
        category=category,
        raw_mode=request.POST.get("mode"),
        default_mode="synthesize",
        missing_key_message="请选择装备类型",
        operation=start_equipment_forging,
        success_message=lambda production: (
            f"{production.equipment_name}"
            f"{'x' + str(production.quantity) if production.quantity > 1 else ''} 开始锻造，预计 {production.actual_duration} 秒后完成"
        ),
        log_message="Unexpected equipment forging start error: manor_id=%s user_id=%s equipment_key=%s quantity=%s",
    )


@login_required
@require_POST
@rate_limit_redirect("equipment_decompose", limit=10, window_seconds=60)
def decompose_equipment_view(request: HttpRequest) -> HttpResponse:
    """分解装备"""
    from gameplay.models import ItemTemplate
    from gameplay.services.buildings.forge import decompose_equipment

    equipment_key = (request.POST.get("equipment_key") or "").strip()
    category = request.POST.get("category", "all")
    return _run_forge_post_action(
        request,
        item_key=equipment_key,
        raw_quantity=request.POST.get("quantity"),
        category=category,
        raw_mode=request.POST.get("mode"),
        default_mode="decompose",
        missing_key_message="请选择要分解的装备",
        operation=decompose_equipment,
        success_message=lambda result: (
            f"{result['equipment_name']}"
            f"{'x' + str(result['quantity']) if result['quantity'] > 1 else ''} 分解完成"
            f"{_build_decompose_reward_text(result, ItemTemplate)}"
        ),
        log_message="Unexpected equipment decompose error: manor_id=%s user_id=%s equipment_key=%s quantity=%s",
    )


@login_required
@require_POST
@rate_limit_redirect("blueprint_synthesize", limit=10, window_seconds=60)
def synthesize_blueprint_equipment_view(request: HttpRequest) -> HttpResponse:
    """按图纸合成装备"""
    from gameplay.services.buildings.forge import synthesize_equipment_with_blueprint

    blueprint_key = (request.POST.get("blueprint_key") or "").strip()
    category = request.POST.get("category", "all")
    return _run_forge_post_action(
        request,
        item_key=blueprint_key,
        raw_quantity=request.POST.get("quantity"),
        category=category,
        raw_mode=request.POST.get("mode"),
        default_mode="synthesize",
        missing_key_message="请选择图纸",
        operation=synthesize_equipment_with_blueprint,
        success_message=lambda result: (
            f"{result['result_name']}" f"{'x' + str(result['quantity']) if result['quantity'] > 1 else ''} 合成完成"
        ),
        log_message="Unexpected blueprint synthesize error: manor_id=%s user_id=%s blueprint_key=%s quantity=%s",
    )
