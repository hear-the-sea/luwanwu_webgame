"""
生产系统视图：马房、畜牧、冶炼、锻造
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import safe_positive_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect
from gameplay.constants import UIConstants
from gameplay.services import ensure_manor, get_player_technology_level, refresh_manor_state

logger = logging.getLogger(__name__)


def _parse_positive_quantity(raw_quantity: str | None) -> int | None:
    return safe_positive_int(raw_quantity, default=None)


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
        context["active_productions"] = get_active_productions(manor)
        context["speed_bonus"] = get_stable_speed_bonus(manor)
        context["speed_bonus_percent"] = int(get_stable_speed_bonus(manor) * 100)
        context["horsemanship_level"] = horsemanship_level
        context["max_production_quantity"] = max_quantity
        context["is_producing"] = is_producing

        return context


@login_required
@require_POST
@rate_limit_redirect("horse_production", limit=10, window_seconds=60)
def start_horse_production_view(request: HttpRequest) -> HttpResponse:
    """开始马匹生产"""
    manor = ensure_manor(request.user)
    horse_key = (request.POST.get("horse_key") or "").strip()
    quantity = _parse_positive_quantity(request.POST.get("quantity"))

    if not horse_key:
        messages.error(request, "请选择马匹类型")
        return redirect("gameplay:stable")
    if quantity is None:
        messages.error(request, "无效的数量")
        return redirect("gameplay:stable")

    try:
        from gameplay.services import start_horse_production

        production = start_horse_production(manor, horse_key, quantity)
        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        messages.success(
            request, f"{production.horse_name}{quantity_text} 开始生产，预计 {production.actual_duration} 秒后完成"
        )
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected horse production start error: manor_id=%s user_id=%s horse_key=%s quantity=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            horse_key,
            request.POST.get("quantity"),
        )
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:stable")


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
        context["active_productions"] = get_active_livestock_productions(manor)
        context["speed_bonus"] = get_ranch_speed_bonus(manor)
        context["speed_bonus_percent"] = int(get_ranch_speed_bonus(manor) * 100)
        context["animal_husbandry_level"] = animal_husbandry_level
        context["max_livestock_quantity"] = max_quantity
        context["is_producing"] = is_producing

        return context


@login_required
@require_POST
@rate_limit_redirect("livestock_production", limit=10, window_seconds=60)
def start_livestock_production_view(request: HttpRequest) -> HttpResponse:
    """开始家畜养殖"""
    manor = ensure_manor(request.user)
    livestock_key = (request.POST.get("livestock_key") or "").strip()
    quantity = _parse_positive_quantity(request.POST.get("quantity"))

    if not livestock_key:
        messages.error(request, "请选择家畜类型")
        return redirect("gameplay:ranch")
    if quantity is None:
        messages.error(request, "无效的数量")
        return redirect("gameplay:ranch")

    try:
        from gameplay.services.buildings.ranch import start_livestock_production

        production = start_livestock_production(manor, livestock_key, quantity)
        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        messages.success(
            request, f"{production.livestock_name}{quantity_text} 开始养殖，预计 {production.actual_duration} 秒后完成"
        )
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected livestock production start error: manor_id=%s user_id=%s livestock_key=%s quantity=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            livestock_key,
            request.POST.get("quantity"),
        )
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:ranch")


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
        context["active_productions"] = get_active_smelting_productions(manor)
        context["speed_bonus"] = get_smithy_speed_bonus(manor)
        context["speed_bonus_percent"] = int(get_smithy_speed_bonus(manor) * 100)
        context["smelting_level"] = smelting_level
        context["max_smelting_quantity"] = max_quantity
        context["is_producing"] = is_producing

        return context


@login_required
@require_POST
@rate_limit_redirect("smelting_production", limit=10, window_seconds=60)
def start_smelting_production_view(request: HttpRequest) -> HttpResponse:
    """开始冶炼坊制作"""
    manor = ensure_manor(request.user)
    metal_key = (request.POST.get("metal_key") or "").strip()
    quantity = _parse_positive_quantity(request.POST.get("quantity"))

    if not metal_key:
        messages.error(request, "请选择物品类型")
        return redirect("gameplay:smithy")
    if quantity is None:
        messages.error(request, "无效的数量")
        return redirect("gameplay:smithy")

    try:
        from gameplay.services.buildings.smithy import start_smelting_production

        production = start_smelting_production(manor, metal_key, quantity)
        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        messages.success(
            request, f"{production.metal_name}{quantity_text} 开始制作，预计 {production.actual_duration} 秒后完成"
        )
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected smelting production start error: manor_id=%s user_id=%s metal_key=%s quantity=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            metal_key,
            request.POST.get("quantity"),
        )
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:smithy")


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

        current_mode = self.request.GET.get("mode", "synthesize")
        if current_mode not in {"synthesize", "decompose"}:
            current_mode = "synthesize"

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
        context["decomposable_equipment"] = decompose_page_obj
        context["speed_bonus"] = get_forge_speed_bonus(manor)
        context["speed_bonus_percent"] = int(get_forge_speed_bonus(manor) * 100)
        context["forging_level"] = forging_level
        context["max_forging_quantity"] = max_quantity
        context["is_forging"] = is_forging

        return context


def _forge_redirect_url(category: str, mode: str) -> str:
    return f"{reverse('gameplay:forge')}?mode={mode}&category={category}"


@login_required
@require_POST
@rate_limit_redirect("equipment_forging", limit=10, window_seconds=60)
def start_equipment_forging_view(request: HttpRequest) -> HttpResponse:
    """开始装备锻造"""
    manor = ensure_manor(request.user)
    equipment_key = (request.POST.get("equipment_key") or "").strip()
    quantity = _parse_positive_quantity(request.POST.get("quantity"))
    category = request.POST.get("category", "all")
    mode = request.POST.get("mode", "synthesize")
    if mode not in {"synthesize", "decompose"}:
        mode = "synthesize"

    if not equipment_key:
        messages.error(request, "请选择装备类型")
        return redirect(_forge_redirect_url(category, mode))
    if quantity is None:
        messages.error(request, "无效的数量")
        return redirect(_forge_redirect_url(category, mode))

    try:
        from gameplay.services.buildings.forge import start_equipment_forging

        production = start_equipment_forging(manor, equipment_key, quantity)
        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        messages.success(
            request, f"{production.equipment_name}{quantity_text} 开始锻造，预计 {production.actual_duration} 秒后完成"
        )
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected equipment forging start error: manor_id=%s user_id=%s equipment_key=%s quantity=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            equipment_key,
            request.POST.get("quantity"),
        )
        messages.error(request, sanitize_error_message(exc))

    return redirect(_forge_redirect_url(category, mode))


@login_required
@require_POST
@rate_limit_redirect("equipment_decompose", limit=10, window_seconds=60)
def decompose_equipment_view(request: HttpRequest) -> HttpResponse:
    """分解装备"""
    manor = ensure_manor(request.user)
    equipment_key = (request.POST.get("equipment_key") or "").strip()
    quantity = _parse_positive_quantity(request.POST.get("quantity"))
    category = request.POST.get("category", "all")
    mode = request.POST.get("mode", "decompose")
    if mode not in {"synthesize", "decompose"}:
        mode = "decompose"

    if not equipment_key:
        messages.error(request, "请选择要分解的装备")
        return redirect(_forge_redirect_url(category, mode))
    if quantity is None:
        messages.error(request, "无效的数量")
        return redirect(_forge_redirect_url(category, mode))

    try:
        from gameplay.models import ItemTemplate
        from gameplay.services.buildings.forge import decompose_equipment

        result = decompose_equipment(manor, equipment_key, quantity)
        reward_map = result.get("rewards", {}) or {}
        reward_templates = {
            t.key: t.name for t in ItemTemplate.objects.filter(key__in=reward_map.keys()).only("key", "name")
        }
        reward_parts = [
            f"{reward_templates.get(key, key)}x{amount}" for key, amount in reward_map.items() if amount > 0
        ]
        reward_text = f"，获得：{'、'.join(reward_parts)}" if reward_parts else ""
        quantity_text = f"x{result['quantity']}" if result["quantity"] > 1 else ""
        messages.success(request, f"{result['equipment_name']}{quantity_text} 分解完成{reward_text}")
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected equipment decompose error: manor_id=%s user_id=%s equipment_key=%s quantity=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            equipment_key,
            request.POST.get("quantity"),
        )
        messages.error(request, sanitize_error_message(exc))

    return redirect(_forge_redirect_url(category, mode))


@login_required
@require_POST
@rate_limit_redirect("blueprint_synthesize", limit=10, window_seconds=60)
def synthesize_blueprint_equipment_view(request: HttpRequest) -> HttpResponse:
    """按图纸合成装备"""
    manor = ensure_manor(request.user)
    blueprint_key = (request.POST.get("blueprint_key") or "").strip()
    quantity = _parse_positive_quantity(request.POST.get("quantity"))
    category = request.POST.get("category", "all")
    mode = request.POST.get("mode", "synthesize")
    if mode not in {"synthesize", "decompose"}:
        mode = "synthesize"

    if not blueprint_key:
        messages.error(request, "请选择图纸")
        return redirect(_forge_redirect_url(category, mode))
    if quantity is None:
        messages.error(request, "无效的数量")
        return redirect(_forge_redirect_url(category, mode))

    try:
        from gameplay.services.buildings.forge import synthesize_equipment_with_blueprint

        result = synthesize_equipment_with_blueprint(manor, blueprint_key, quantity)
        quantity_text = f"x{result['quantity']}" if result["quantity"] > 1 else ""
        messages.success(request, f"{result['result_name']}{quantity_text} 合成完成")
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "Unexpected blueprint synthesize error: manor_id=%s user_id=%s blueprint_key=%s quantity=%s",
            getattr(manor, "id", None),
            getattr(request.user, "id", None),
            blueprint_key,
            request.POST.get("quantity"),
        )
        messages.error(request, sanitize_error_message(exc))

    return redirect(_forge_redirect_url(category, mode))
