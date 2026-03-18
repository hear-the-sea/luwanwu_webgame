"""
护院募兵视图
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.decorators import flash_unexpected_view_error
from core.exceptions import GameError
from core.utils import safe_positive_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect
from gameplay.constants import BuildingKeys
from gameplay.services.manor.core import get_manor
from gameplay.services.resources import project_resource_production_for_read

logger = logging.getLogger(__name__)

RECRUITMENT_CATEGORY_LABELS: dict[str, str] = {
    "dao": "刀系",
    "qiang": "枪系",
    "jian": "剑系",
    "quan": "拳系",
    "gong": "弓系",
    "scout": "探子",
    "other": "其他",
}


def _build_recruitment_categories(available_classes: set[str]) -> list[dict[str, str]]:
    categories: list[dict[str, str]] = [{"key": "all", "name": "全部"}]
    ordered = ["dao", "qiang", "jian", "quan", "gong", "scout", "other"]
    used = {"all"}

    for class_key in ordered:
        if class_key in available_classes:
            categories.append({"key": class_key, "name": RECRUITMENT_CATEGORY_LABELS.get(class_key, class_key)})
            used.add(class_key)

    for class_key in sorted(available_classes):
        if class_key not in used:
            categories.append({"key": class_key, "name": RECRUITMENT_CATEGORY_LABELS.get(class_key, class_key)})
    return categories


def _recruitment_redirect(category: str | None = None) -> HttpResponse:
    base_url = reverse("gameplay:troop_recruitment")
    normalized_category = (category or "all").strip()
    if normalized_category and normalized_category != "all":
        return redirect(f"{base_url}?{urlencode({'category': normalized_category})}")
    return redirect(base_url)


def _handle_unexpected_recruitment_error(
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


def _handle_known_recruitment_error(request: HttpRequest, exc: GameError | ValueError) -> None:
    messages.error(request, sanitize_error_message(exc))


class TroopRecruitmentView(LoginRequiredMixin, TemplateView):
    """护院募兵页面"""

    template_name = "gameplay/troop_recruitment.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        manor = get_manor(self.request.user)
        project_resource_production_for_read(manor)

        from gameplay.services.recruitment.recruitment import (
            get_active_recruitments,
            get_player_troops,
            get_recruitment_options,
            has_active_recruitment,
        )

        training_level = manor.get_building_level(BuildingKeys.LIANGGONG_CHANG)
        citang_level = manor.get_building_level(BuildingKeys.CITANG)
        is_recruiting = has_active_recruitment(manor)

        # 计算综合速度加成（用于显示）
        training_multiplier = manor.guard_training_speed_multiplier
        citang_multiplier = manor.citang_recruitment_speed_multiplier
        total_multiplier = training_multiplier * citang_multiplier
        # 速度加成百分比 = (倍率 - 1) * 100，如 1.3 * 2.2 = 2.86 -> 186%
        speed_bonus_percent = int((total_multiplier - 1) * 100)
        selected_category = (self.request.GET.get("category") or "all").strip() or "all"
        recruitment_options = get_recruitment_options(manor)

        from gameplay.services.technology import get_troop_class_for_key

        available_classes: set[str] = set()
        for troop in recruitment_options:
            troop_class = get_troop_class_for_key(str(troop.get("key", ""))) or "other"
            troop["troop_class"] = troop_class
            available_classes.add(troop_class)

        recruitment_categories = _build_recruitment_categories(available_classes)
        valid_category_keys = {item["key"] for item in recruitment_categories}
        if selected_category not in valid_category_keys:
            selected_category = "all"
        if selected_category != "all":
            recruitment_options = [
                troop for troop in recruitment_options if troop.get("troop_class") == selected_category
            ]

        context["manor"] = manor
        context["training_level"] = training_level
        context["citang_level"] = citang_level
        context["can_recruit"] = training_level >= 1
        context["recruitment_options"] = recruitment_options
        context["recruitment_categories"] = recruitment_categories
        context["current_category"] = selected_category
        context["active_recruitments"] = get_active_recruitments(manor)
        context["player_troops"] = get_player_troops(manor)
        context["speed_bonus_percent"] = speed_bonus_percent
        context["training_multiplier"] = training_multiplier
        context["citang_multiplier"] = citang_multiplier
        context["is_recruiting"] = is_recruiting

        return context


def _troop_bank_post_input(request: HttpRequest) -> tuple[str | None, int | None]:
    troop_key = (request.POST.get("troop_key") or "").strip()
    quantity = safe_positive_int(request.POST.get("quantity"), default=None)
    if not troop_key:
        return None, None
    return troop_key, quantity


def _execute_troop_bank_transfer(
    request: HttpRequest,
    *,
    transfer_action: Callable[[Any, str, int], Any],
    success_message_template: str,
    log_message: str,
) -> HttpResponse:
    manor = get_manor(request.user)
    troop_key, quantity = _troop_bank_post_input(request)

    if not troop_key:
        messages.error(request, "请选择护院类型")
        return redirect("gameplay:troop_recruitment")
    if quantity is None:
        messages.error(request, "数量参数无效")
        return redirect("gameplay:troop_recruitment")

    try:
        result = transfer_action(manor, troop_key, quantity)
        messages.success(request, success_message_template.format(**result))
    except (GameError, ValueError) as exc:
        _handle_known_recruitment_error(request, exc)
    except DatabaseError as exc:
        _handle_unexpected_recruitment_error(
            request,
            exc,
            log_message=log_message,
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                troop_key,
                quantity,
            ),
        )
    except Exception as exc:
        _handle_unexpected_recruitment_error(
            request,
            exc,
            log_message=log_message,
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                troop_key,
                quantity,
            ),
        )

    return redirect("gameplay:troop_recruitment")


@login_required
@require_POST
def start_troop_recruitment_view(request: HttpRequest) -> HttpResponse:
    """开始募兵"""
    manor = get_manor(request.user)
    selected_category = (request.POST.get("category") or "all").strip()
    troop_key = (request.POST.get("troop_key") or "").strip()
    quantity = safe_positive_int(request.POST.get("quantity"), default=None)

    if not troop_key:
        messages.error(request, "请选择兵种")
        return _recruitment_redirect(selected_category)
    if quantity is None:
        messages.error(request, "无效的数量")
        return _recruitment_redirect(selected_category)

    try:
        from gameplay.services.recruitment.recruitment import start_troop_recruitment

        recruitment = start_troop_recruitment(manor, troop_key, quantity)
        quantity_text = f"x{recruitment.quantity}" if recruitment.quantity > 1 else ""
        messages.success(
            request, f"{recruitment.troop_name}{quantity_text} 开始募兵，预计 {recruitment.actual_duration} 秒后完成"
        )
    except (GameError, ValueError) as exc:
        _handle_known_recruitment_error(request, exc)
    except DatabaseError as exc:
        _handle_unexpected_recruitment_error(
            request,
            exc,
            log_message="Unexpected troop recruitment start error: manor_id=%s user_id=%s troop_key=%s quantity=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                troop_key,
                request.POST.get("quantity"),
            ),
        )
    except Exception as exc:
        _handle_unexpected_recruitment_error(
            request,
            exc,
            log_message="Unexpected troop recruitment start error: manor_id=%s user_id=%s troop_key=%s quantity=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                troop_key,
                request.POST.get("quantity"),
            ),
        )

    return _recruitment_redirect(selected_category)


@login_required
@require_POST
@rate_limit_redirect("deposit_troop_to_bank", limit=30, window_seconds=60)
def deposit_troop_to_bank_view(request: HttpRequest) -> HttpResponse:
    from gameplay.services.manor.troop_bank import deposit_troops_to_bank

    return _execute_troop_bank_transfer(
        request,
        transfer_action=deposit_troops_to_bank,
        success_message_template="已存入 {quantity} 名{troop_name}到钱庄",
        log_message="Unexpected troop bank deposit error: manor_id=%s user_id=%s troop_key=%s quantity=%s",
    )


@login_required
@require_POST
@rate_limit_redirect("withdraw_troop_from_bank", limit=30, window_seconds=60)
def withdraw_troop_from_bank_view(request: HttpRequest) -> HttpResponse:
    from gameplay.services.manor.troop_bank import withdraw_troops_from_bank

    return _execute_troop_bank_transfer(
        request,
        transfer_action=withdraw_troops_from_bank,
        success_message_template="已从钱庄取出 {quantity} 名{troop_name}",
        log_message="Unexpected troop bank withdraw error: manor_id=%s user_id=%s troop_key=%s quantity=%s",
    )
