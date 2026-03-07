"""
核心页面视图：首页、仪表盘、设置、排行榜
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from common.constants.resources import ResourceType
from core.decorators import flash_unexpected_view_error
from core.exceptions import GameError
from core.utils import sanitize_error_message
from gameplay.models import BuildingCategory
from gameplay.selectors.home import get_home_context
from gameplay.services import ensure_manor, refresh_manor_state

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, TemplateView):
    """建筑仪表盘页面"""

    template_name = "gameplay/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        try:
            refresh_manor_state(manor)
        except Exception as exc:
            flash_unexpected_view_error(
                self.request,
                exc,
                log_message="Unexpected dashboard refresh error: manor_id=%s user_id=%s",
                log_args=(
                    getattr(manor, "id", None),
                    getattr(self.request.user, "id", None),
                ),
                logger_instance=logger,
            )

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
            context.update(get_home_context(manor))

        return context


class SettingsView(LoginRequiredMixin, TemplateView):
    """设置页面"""

    template_name = "gameplay/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)

        from gameplay.services import get_rename_card_count

        context["manor"] = manor
        context["rename_card_count"] = get_rename_card_count(manor)

        return context


@login_required
@require_POST
def rename_manor_view(request: HttpRequest) -> HttpResponse:
    """庄园更名"""
    from gameplay.services import rename_manor

    manor = ensure_manor(request.user)
    new_name = request.POST.get("new_name", "").strip()

    if not new_name:
        messages.error(request, "请输入新名称")
        return redirect("gameplay:settings")

    try:
        rename_manor(manor, new_name)
        messages.success(request, f"庄园已成功更名为「{new_name}」")
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        flash_unexpected_view_error(
            request,
            exc,
            log_message="Unexpected manor rename error: manor_id=%s user_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
            ),
            logger_instance=logger,
        )

    return redirect("gameplay:settings")


class RankingView(LoginRequiredMixin, TemplateView):
    """声望排行榜页面"""

    template_name = "gameplay/ranking.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)

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
