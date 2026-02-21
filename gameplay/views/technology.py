"""
科技研究视图
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import sanitize_error_message
from gameplay.services import (
    ensure_manor,
    get_categories,
    get_martial_technologies_grouped,
    get_technology_display_data,
    refresh_manor_state,
    refresh_technology_upgrades,
    upgrade_technology,
)


class TechnologyView(LoginRequiredMixin, TemplateView):
    """技术研究页面"""

    template_name = "gameplay/technology.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        refresh_manor_state(manor)

        # 刷新技术升级状态
        refresh_technology_upgrades(manor)

        # 获取当前选中的分类，默认为 basic
        current_tab = self.request.GET.get("tab", "basic")
        valid_tabs = ["basic", "martial", "production"]
        if current_tab not in valid_tabs:
            current_tab = "basic"

        context["manor"] = manor
        context["categories"] = get_categories()
        context["current_tab"] = current_tab

        # 武艺技术按兵种分组，支持子分类筛选
        if current_tab == "martial":
            all_groups = get_martial_technologies_grouped(manor)
            # 兵种子分类
            troop_classes = [
                {"key": "dao", "name": "刀类"},
                {"key": "qiang", "name": "枪类"},
                {"key": "jian", "name": "剑类"},
                {"key": "quan", "name": "拳类"},
                {"key": "gong", "name": "弓箭类"},
            ]
            context["troop_classes"] = troop_classes

            # 获取当前选中的兵种子分类
            current_troop_class = self.request.GET.get("troop", "dao")
            valid_troop_classes = [tc["key"] for tc in troop_classes]
            if current_troop_class not in valid_troop_classes:
                current_troop_class = "dao"
            context["current_troop_class"] = current_troop_class

            # 只显示当前选中兵种的技术
            context["martial_groups"] = [g for g in all_groups if g["class_key"] == current_troop_class]
            context["technologies"] = []
        else:
            context["martial_groups"] = []
            context["troop_classes"] = []
            context["current_troop_class"] = ""
            context["technologies"] = get_technology_display_data(manor, current_tab)

        return context


@login_required
@require_POST
def upgrade_technology_view(request: HttpRequest, tech_key: str) -> HttpResponse:
    """升级技术"""
    manor = ensure_manor(request.user)
    tab = request.POST.get("tab", "basic")
    troop = request.POST.get("troop", "")

    try:
        result = upgrade_technology(manor, tech_key)
        messages.success(request, result["message"])
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))

    # 构建重定向URL，保留子分类参数
    redirect_url = f"{reverse('gameplay:technology')}?tab={tab}"
    if tab == "martial" and troop:
        redirect_url += f"&troop={troop}"
    return redirect(redirect_url)
