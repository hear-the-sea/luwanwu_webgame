"""
生产系统视图：马房、畜牧、冶炼、锻造
"""

from __future__ import annotations

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
from core.utils import sanitize_error_message
from gameplay.constants import UIConstants
from gameplay.services import ensure_manor, get_player_technology_level, refresh_manor_state


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
def start_horse_production_view(request: HttpRequest) -> HttpResponse:
    """开始马匹生产"""
    manor = ensure_manor(request.user)
    horse_key = request.POST.get("horse_key")
    quantity_str = request.POST.get("quantity", "1")

    if not horse_key:
        messages.error(request, "请选择马匹类型")
        return redirect("gameplay:stable")

    try:
        quantity = int(quantity_str)
    except ValueError:
        messages.error(request, "无效的数量")
        return redirect("gameplay:stable")

    try:
        from gameplay.services import start_horse_production

        production = start_horse_production(manor, horse_key, quantity)
        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        messages.success(
            request, f"{production.horse_name}{quantity_text} 开始生产，预计 {production.actual_duration} 秒后完成"
        )
    except (GameError, ValueError) as e:
        messages.error(request, sanitize_error_message(e))

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
def start_livestock_production_view(request: HttpRequest) -> HttpResponse:
    """开始家畜养殖"""
    manor = ensure_manor(request.user)
    livestock_key = request.POST.get("livestock_key")
    quantity_str = request.POST.get("quantity", "1")

    if not livestock_key:
        messages.error(request, "请选择家畜类型")
        return redirect("gameplay:ranch")

    try:
        quantity = int(quantity_str)
    except ValueError:
        messages.error(request, "无效的数量")
        return redirect("gameplay:ranch")

    try:
        from gameplay.services.buildings.ranch import start_livestock_production

        production = start_livestock_production(manor, livestock_key, quantity)
        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        messages.success(
            request, f"{production.livestock_name}{quantity_text} 开始养殖，预计 {production.actual_duration} 秒后完成"
        )
    except (GameError, ValueError) as e:
        messages.error(request, sanitize_error_message(e))

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
def start_smelting_production_view(request: HttpRequest) -> HttpResponse:
    """开始金属冶炼"""
    manor = ensure_manor(request.user)
    metal_key = request.POST.get("metal_key")
    quantity_str = request.POST.get("quantity", "1")

    if not metal_key:
        messages.error(request, "请选择金属类型")
        return redirect("gameplay:smithy")

    try:
        quantity = int(quantity_str)
    except ValueError:
        messages.error(request, "无效的数量")
        return redirect("gameplay:smithy")

    try:
        from gameplay.services.buildings.smithy import start_smelting_production

        production = start_smelting_production(manor, metal_key, quantity)
        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        messages.success(
            request, f"{production.metal_name}{quantity_text} 开始冶炼，预计 {production.actual_duration} 秒后完成"
        )
    except (GameError, ValueError) as e:
        messages.error(request, sanitize_error_message(e))

    return redirect("gameplay:smithy")


class ForgeView(LoginRequiredMixin, TemplateView):
    """铁匠铺装备锻造页面"""

    template_name = "gameplay/forge.html"
    ITEMS_PER_PAGE = UIConstants.FORGE_ITEMS_PER_PAGE

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)

        from gameplay.services.buildings.forge import (
            EQUIPMENT_CATEGORIES,
            get_active_forgings,
            get_equipment_options,
            get_forge_speed_bonus,
            get_max_forging_quantity,
            has_active_forging,
            refresh_equipment_forgings,
        )

        # 刷新装备锻造状态
        refresh_equipment_forgings(manor)

        forging_level = get_player_technology_level(manor, "forging")
        max_quantity = get_max_forging_quantity(manor)
        is_forging = has_active_forging(manor)

        # 获取当前选中的类别（支持"all"表示全部）
        current_category = self.request.GET.get("category", "all")
        valid_categories = ["all"] + list(EQUIPMENT_CATEGORIES.keys())
        if current_category not in valid_categories:
            current_category = "all"

        # 获取装备列表（按类别过滤或全部）
        if current_category == "all":
            equipment_list = get_equipment_options(manor)
        else:
            equipment_list = get_equipment_options(manor, category=current_category)

        # 分页处理
        paginator = Paginator(equipment_list, self.ITEMS_PER_PAGE)
        page_number = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # 构建带"全部"选项的类别字典
        categories_with_all = {"all": "全部"}
        categories_with_all.update(EQUIPMENT_CATEGORIES)

        context["manor"] = manor
        context["equipment_categories"] = categories_with_all
        context["current_category"] = current_category
        context["equipment_list"] = page_obj
        context["page_obj"] = page_obj
        context["active_forgings"] = get_active_forgings(manor)
        context["speed_bonus"] = get_forge_speed_bonus(manor)
        context["speed_bonus_percent"] = int(get_forge_speed_bonus(manor) * 100)
        context["forging_level"] = forging_level
        context["max_forging_quantity"] = max_quantity
        context["is_forging"] = is_forging

        return context


@login_required
@require_POST
def start_equipment_forging_view(request: HttpRequest) -> HttpResponse:
    """开始装备锻造"""
    manor = ensure_manor(request.user)
    equipment_key = request.POST.get("equipment_key")
    quantity_str = request.POST.get("quantity", "1")
    category = request.POST.get("category", "helmet")

    if not equipment_key:
        messages.error(request, "请选择装备类型")
        return redirect(f"{reverse('gameplay:forge')}?category={category}")

    try:
        quantity = int(quantity_str)
    except ValueError:
        messages.error(request, "无效的数量")
        return redirect(f"{reverse('gameplay:forge')}?category={category}")

    try:
        from gameplay.services.buildings.forge import start_equipment_forging

        production = start_equipment_forging(manor, equipment_key, quantity)
        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        messages.success(
            request, f"{production.equipment_name}{quantity_text} 开始锻造，预计 {production.actual_duration} 秒后完成"
        )
    except (GameError, ValueError) as e:
        messages.error(request, sanitize_error_message(e))

    return redirect(f"{reverse('gameplay:forge')}?category={category}")
