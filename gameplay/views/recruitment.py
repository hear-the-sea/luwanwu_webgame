"""
护院募兵视图
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import sanitize_error_message
from gameplay.constants import BuildingKeys
from gameplay.services import (
    ensure_manor,
    refresh_manor_state,
)


class TroopRecruitmentView(LoginRequiredMixin, TemplateView):
    """护院募兵页面"""

    template_name = "gameplay/troop_recruitment.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)

        from gameplay.services.recruitment import (
            get_recruitment_options,
            get_active_recruitments,
            refresh_troop_recruitments,
            has_active_recruitment,
            get_player_troops,
        )

        # 刷新募兵状态
        refresh_troop_recruitments(manor)

        training_level = manor.get_building_level(BuildingKeys.LIANGGONG_CHANG)
        citang_level = manor.get_building_level(BuildingKeys.CITANG)
        is_recruiting = has_active_recruitment(manor)

        # 计算综合速度加成（用于显示）
        training_multiplier = manor.guard_training_speed_multiplier
        citang_multiplier = manor.citang_recruitment_speed_multiplier
        total_multiplier = training_multiplier * citang_multiplier
        # 速度加成百分比 = (倍率 - 1) * 100，如 1.3 * 2.2 = 2.86 -> 186%
        speed_bonus_percent = int((total_multiplier - 1) * 100)

        context["manor"] = manor
        context["training_level"] = training_level
        context["citang_level"] = citang_level
        context["can_recruit"] = training_level >= 1
        context["recruitment_options"] = get_recruitment_options(manor)
        context["active_recruitments"] = get_active_recruitments(manor)
        context["player_troops"] = get_player_troops(manor)
        context["speed_bonus_percent"] = speed_bonus_percent
        context["training_multiplier"] = training_multiplier
        context["citang_multiplier"] = citang_multiplier
        context["is_recruiting"] = is_recruiting

        return context


@login_required
@require_POST
def start_troop_recruitment_view(request: HttpRequest) -> HttpResponse:
    """开始募兵"""
    manor = ensure_manor(request.user)
    troop_key = request.POST.get("troop_key")
    quantity_str = request.POST.get("quantity", "1")

    if not troop_key:
        messages.error(request, "请选择兵种")
        return redirect("gameplay:troop_recruitment")

    try:
        quantity = int(quantity_str)
    except ValueError:
        messages.error(request, "无效的数量")
        return redirect("gameplay:troop_recruitment")

    try:
        from gameplay.services.recruitment import start_troop_recruitment
        recruitment = start_troop_recruitment(manor, troop_key, quantity)
        quantity_text = f"x{recruitment.quantity}" if recruitment.quantity > 1 else ""
        messages.success(request, f"{recruitment.troop_name}{quantity_text} 开始募兵，预计 {recruitment.actual_duration} 秒后完成")
    except (GameError, ValueError) as e:
        messages.error(request, sanitize_error_message(e))

    return redirect("gameplay:troop_recruitment")
