"""
核心页面视图：首页、仪表盘、设置、排行榜
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from common.constants.resources import ResourceType
from core.decorators import flash_unexpected_view_error
from core.exceptions import GameError
from core.utils import sanitize_error_message
from gameplay.constants import BUILDING_MAX_LEVELS
from gameplay.models import BuildingCategory
from gameplay.selectors.home import get_home_context
from gameplay.services.manor.core import get_manor, get_rename_card_count, rename_manor
from gameplay.services.resources import project_resource_production_for_read
from gameplay.views.read_helpers import get_prepared_manor_for_read, get_prepared_manor_with_raid_activity_for_read

logger = logging.getLogger(__name__)


def _handle_unexpected_core_error(
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


def _handle_known_core_error(request: HttpRequest, exc: GameError | ValueError) -> None:
    messages.error(request, sanitize_error_message(exc))


class DashboardView(LoginRequiredMixin, TemplateView):
    """建筑仪表盘页面"""

    template_name = "gameplay/dashboard.html"

    @staticmethod
    def _prepare_building_display(buildings: Any) -> list[Any]:
        prepared: list[Any] = []
        for building in buildings:
            max_level = BUILDING_MAX_LEVELS.get(building.building_type.key)
            is_max_level = max_level is not None and building.level >= max_level
            building.max_level = max_level
            building.is_max_level = is_max_level
            building.can_upgrade = not building.is_upgrading and not is_max_level
            building.next_level_cost_display = None if is_max_level else building.next_level_cost()
            prepared.append(building)
        return prepared

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        manor = get_prepared_manor_for_read(
            self.request,
            project_fn=project_resource_production_for_read,
            logger=logger,
            source="dashboard_view",
        )

        # Get category from URL parameter, default to 'resource'
        category = self.kwargs.get("category", "resource")
        if category not in [c[0] for c in BuildingCategory.choices]:
            category = "resource"

        context["manor"] = manor
        context["current_category"] = category
        context["category_label"] = dict(BuildingCategory.choices).get(category, "资源生产")
        context["categories"] = BuildingCategory.choices
        buildings = (
            manor.buildings.select_related("building_type")
            .filter(building_type__category=category)
            .order_by("building_type__name")
        )
        context["buildings"] = self._prepare_building_display(buildings)
        context["resource_labels"] = dict(ResourceType.choices)
        return context


class HomeView(TemplateView):
    """游戏首页/着陆页"""

    template_name = "landing.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if user.is_authenticated:
            manor = get_prepared_manor_with_raid_activity_for_read(
                self.request,
                logger=logger,
                source="home_view",
                project_fn=project_resource_production_for_read,
            )
            context.update(get_home_context(manor))

        return context


class SettingsView(LoginRequiredMixin, TemplateView):
    """设置页面"""

    template_name = "gameplay/settings.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        manor = get_manor(self.request.user)

        context["manor"] = manor
        context["rename_card_count"] = get_rename_card_count(manor)

        return context


@login_required
@require_POST
def rename_manor_view(request: HttpRequest) -> HttpResponse:
    """庄园更名"""
    manor = get_manor(request.user)
    new_name = request.POST.get("new_name", "").strip()

    if not new_name:
        messages.error(request, "请输入新名称")
        return redirect("gameplay:settings")

    try:
        rename_manor(manor, new_name)
        messages.success(request, f"庄园已成功更名为「{new_name}」")
    except (GameError, ValueError) as exc:
        _handle_known_core_error(request, exc)
    except DatabaseError as exc:
        _handle_unexpected_core_error(
            request,
            exc,
            log_message="Unexpected manor rename error: manor_id=%s user_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
            ),
        )

    return redirect("gameplay:settings")


class RankingView(LoginRequiredMixin, TemplateView):
    """声望排行榜页面"""

    template_name = "gameplay/ranking.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        manor = get_manor(self.request.user)

        from gameplay.services.manor.prestige import get_prestige_progress
        from gameplay.services.ranking import get_ranking_with_player_context

        ranking_data = get_ranking_with_player_context(manor)
        prestige_info = get_prestige_progress(manor)

        context["manor"] = manor
        context["ranking"] = ranking_data["ranking"]
        context["player_rank"] = ranking_data["player_rank"]
        context["player_in_ranking"] = ranking_data["player_in_ranking"]
        context["total_players"] = ranking_data["total_players"]
        context["prestige_info"] = prestige_info

        return context
