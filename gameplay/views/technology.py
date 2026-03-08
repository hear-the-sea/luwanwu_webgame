"""
科技研究视图
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.decorators import flash_unexpected_view_error
from core.exceptions import GameError
from core.utils import safe_redirect_url, sanitize_error_message
from gameplay.services import (
    ensure_manor,
    get_categories,
    get_martial_technologies_grouped,
    get_technology_display_data,
    refresh_manor_state,
    refresh_technology_upgrades,
    upgrade_technology,
)

logger = logging.getLogger(__name__)

TECHNOLOGY_TABS = frozenset({"basic", "martial", "production"})
MARTIAL_TROOP_CLASSES = (
    {"key": "dao", "name": "刀类"},
    {"key": "qiang", "name": "枪类"},
    {"key": "jian", "name": "剑类"},
    {"key": "quan", "name": "拳类"},
    {"key": "gong", "name": "弓箭类"},
)
DEFAULT_TECHNOLOGY_TAB = "basic"
DEFAULT_MARTIAL_TROOP_CLASS = "dao"


def _normalize_technology_tab(raw_tab: str | None) -> str:
    tab = (raw_tab or DEFAULT_TECHNOLOGY_TAB).strip()
    if tab not in TECHNOLOGY_TABS:
        return DEFAULT_TECHNOLOGY_TAB
    return tab


def _normalize_martial_troop_class(raw_troop_class: str | None) -> str:
    troop_class = (raw_troop_class or DEFAULT_MARTIAL_TROOP_CLASS).strip()
    valid_troop_classes = {item["key"] for item in MARTIAL_TROOP_CLASSES}
    if troop_class not in valid_troop_classes:
        return DEFAULT_MARTIAL_TROOP_CLASS
    return troop_class


def _build_technology_redirect_url(tab: str, troop: str = "") -> str:
    redirect_url = f"{reverse('gameplay:technology')}?tab={tab}"
    if tab == "martial" and troop:
        redirect_url += f"&troop={troop}"
    return redirect_url


def _handle_known_technology_error(request: HttpRequest, exc: GameError | ValueError) -> None:
    messages.error(request, sanitize_error_message(exc))


def _handle_unexpected_technology_error(
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
        current_tab = _normalize_technology_tab(self.request.GET.get("tab"))

        context["manor"] = manor
        context["categories"] = get_categories()
        context["current_tab"] = current_tab

        # 武艺技术按兵种分组，支持子分类筛选
        if current_tab == "martial":
            all_groups = get_martial_technologies_grouped(manor)
            # 兵种子分类
            context["troop_classes"] = list(MARTIAL_TROOP_CLASSES)

            # 获取当前选中的兵种子分类
            current_troop_class = _normalize_martial_troop_class(self.request.GET.get("troop"))
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
    tab = _normalize_technology_tab(request.POST.get("tab"))
    troop = _normalize_martial_troop_class(request.POST.get("troop")) if tab == "martial" else ""
    next_url = (request.POST.get("next") or "").strip()

    try:
        result = upgrade_technology(manor, tech_key)
        messages.success(request, result["message"])
    except (GameError, ValueError) as exc:
        _handle_known_technology_error(request, exc)
    except Exception as exc:
        _handle_unexpected_technology_error(
            request,
            exc,
            log_message="Unexpected technology upgrade view error: manor_id=%s user_id=%s tech_key=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                tech_key,
            ),
        )

    # 构建重定向URL，保留子分类参数
    redirect_url = _build_technology_redirect_url(tab, troop)
    redirect_url = safe_redirect_url(request, next_url, redirect_url)
    return redirect(redirect_url)
