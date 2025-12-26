"""
核心页面视图：首页、仪表盘、设置、排行榜
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from guests.models import GuestStatus, RARITY_SALARY

from ..models import BuildingCategory, MissionRun, ResourceType
from ..services import (
    can_retreat,
    ensure_manor,
    get_technology_template,
    refresh_manor_state,
    refresh_technology_upgrades,
)


class DashboardView(LoginRequiredMixin, TemplateView):
    """建筑仪表盘页面"""

    template_name = "gameplay/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)

        # Get category from URL parameter, default to 'resource'
        category = self.kwargs.get("category", "resource")
        if category not in [c[0] for c in BuildingCategory.choices]:
            category = "resource"

        context["manor"] = manor
        context["current_category"] = category
        context["category_label"] = dict(BuildingCategory.choices).get(category, "资源生产")
        context["categories"] = BuildingCategory.choices
        context["buildings"] = (
            manor.buildings.select_related("building_type")
            .filter(building_type__category=category)
            .order_by("building_type__name")
        )
        context["resource_labels"] = dict(ResourceType.choices)
        return context


class HomeView(TemplateView):
    """游戏首页/着陆页"""

    template_name = "landing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if user.is_authenticated:
            manor = ensure_manor(user)
            refresh_manor_state(manor)
            refresh_technology_upgrades(manor)
            context["manor"] = manor
            resources = [
                ("grain", "粮食", manor.grain),
                ("silver", "银两", manor.silver),
            ]
            resources.append(("retainer", "家丁", f"{manor.retainer_count} / {manor.retainer_capacity}"))
            context["resources"] = resources
            context["resource_labels"] = dict(ResourceType.choices)

            # 门客列表（包含状态）- 优化：预加载关联数据避免 N+1 查询
            guests = list(
                manor.guests
                .select_related("template")
                .prefetch_related("gear_items__template", "guest_skills__skill")
                .order_by("template__name")
            )
            guest_status_display = dict(GuestStatus.choices)
            for guest in guests:
                guest.status_display = guest_status_display.get(guest.status, guest.status)
            context["guests"] = guests
            # 复用已加载的门客列表计算数量，避免额外的 count() 查询
            context["guest_count"] = len(guests)

            # 优化：使用预加载配置获取活动任务
            runs = list(
                manor.mission_runs.select_related("mission")
                .prefetch_related("guests__template")
                .filter(status=MissionRun.Status.ACTIVE, return_at__isnull=False)
            )
            now = timezone.now()
            for run in runs:
                run.can_retreat = can_retreat(run, now=now)
            context["active_runs"] = runs

            # 事件栏：正在升级的建筑（使用预加载配置）
            context["upgrading_buildings"] = list(
                manor.buildings.select_related("building_type")
                .filter(is_upgrading=True, upgrade_complete_at__isnull=False)
                .order_by("upgrade_complete_at")
            )

            # 事件栏：正在升级的科技
            upgrading_techs = list(
                manor.technologies.filter(
                    is_upgrading=True,
                    upgrade_complete_at__isnull=False
                ).order_by("upgrade_complete_at")
            )
            for tech in upgrading_techs:
                tpl = get_technology_template(tech.tech_key) or {}
                tech.display_name = tpl.get("name", tech.tech_key)
            context["upgrading_technologies"] = upgrading_techs

            # 收支状况：门客工资总计（复用已加载的门客列表）
            total_guest_salary = sum(RARITY_SALARY.get(g.rarity, 1000) for g in guests)
            context["total_guest_salary"] = total_guest_salary

            # 收支状况：各建筑产量
            from ..utils.resource_calculator import get_hourly_rates
            hourly_rates = get_hourly_rates(manor)
            resource_labels = dict(ResourceType.choices)
            building_income = []
            for res_type, rate in hourly_rates.items():
                if rate > 0:
                    label = resource_labels.get(res_type, res_type)
                    building_income.append({"resource": res_type, "label": label, "rate": int(rate)})
            context["building_income"] = building_income

            # 粮食产量单独提取
            context["grain_production"] = int(hourly_rates.get("grain", 0))

            # 人员耗粮（家丁消耗）
            context["personnel_grain_cost"] = manor.retainer_count

            # 护院状况：只显示拥有的护院及数量
            player_troops = list(
                manor.troops.select_related("troop_template")
                .filter(count__gt=0)
                .order_by("troop_template__priority")
            )
            context["player_troops"] = player_troops

            # 事件栏：侦察和踢馆出征
            from ..services.raid import (
                get_active_scouts,
                get_active_raids,
                get_incoming_raids,
                refresh_scout_records,
                refresh_raid_runs,
            )
            refresh_scout_records(manor)
            refresh_raid_runs(manor)
            context["active_scouts"] = get_active_scouts(manor)
            context["active_raids"] = get_active_raids(manor)
            context["incoming_raids"] = get_incoming_raids(manor)

        return context


class SettingsView(LoginRequiredMixin, TemplateView):
    """设置页面"""

    template_name = "gameplay/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)

        from ..services import get_rename_card_count

        context["manor"] = manor
        context["rename_card_count"] = get_rename_card_count(manor)

        return context


@login_required
@require_POST
def rename_manor_view(request: HttpRequest) -> HttpResponse:
    """庄园更名"""
    from ..services import rename_manor

    manor = ensure_manor(request.user)
    new_name = request.POST.get("new_name", "").strip()

    if not new_name:
        messages.error(request, "请输入新名称")
        return redirect("gameplay:settings")

    try:
        rename_manor(manor, new_name)
        messages.success(request, f"庄园已成功更名为「{new_name}」")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect("gameplay:settings")


class RankingView(LoginRequiredMixin, TemplateView):
    """声望排行榜页面"""

    template_name = "gameplay/ranking.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)

        from ..services.ranking import get_ranking_with_player_context
        from ..services.prestige import get_prestige_progress

        ranking_data = get_ranking_with_player_context(manor)
        prestige_info = get_prestige_progress(manor)

        context["manor"] = manor
        context["ranking"] = ranking_data["ranking"]
        context["player_rank"] = ranking_data["player_rank"]
        context["player_in_ranking"] = ranking_data["player_in_ranking"]
        context["total_players"] = ranking_data["total_players"]
        context["prestige_info"] = prestige_info

        return context
