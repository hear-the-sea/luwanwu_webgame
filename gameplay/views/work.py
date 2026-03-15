"""
打工系统视图
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.decorators import flash_unexpected_view_error
from core.exceptions import GameError
from core.utils import safe_positive_int, safe_redirect_url, sanitize_error_message
from gameplay.models import WorkAssignment, WorkTemplate
from gameplay.services.manor.core import get_manor
from gameplay.services.resources import sync_resource_production
from gameplay.services.work import assign_guest_to_work, claim_work_reward, recall_guest_from_work
from guests.models import Guest, GuestStatus

logger = logging.getLogger(__name__)


def _handle_unexpected_work_error(
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


def _handle_known_work_error(request: HttpRequest, exc: GameError | ValueError) -> None:
    messages.error(request, sanitize_error_message(exc))


def _resolve_work_redirect_url(request: HttpRequest) -> str:
    return safe_redirect_url(
        request,
        (request.POST.get("next") or request.GET.get("next") or "").strip(),
        reverse("gameplay:work"),
    )


class WorkView(LoginRequiredMixin, TemplateView):
    """打工页面"""

    template_name = "gameplay/work.html"
    WORKS_PER_PAGE = 4

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = get_manor(self.request.user)
        sync_resource_production(manor, persist=False)

        # 获取当前标签页
        current_tier = self.request.GET.get("tier", "junior")

        # 工作区选项
        work_tiers = [
            {
                "key": "junior",
                "name": "初级工作区",
                "tier": WorkTemplate.Tier.JUNIOR,
                "desc": "适合新手门客的基础工作，2小时完成",
            },
            {
                "key": "intermediate",
                "name": "中级工作区",
                "tier": WorkTemplate.Tier.INTERMEDIATE,
                "desc": "需要一定经验的工作，3小时完成",
            },
            {
                "key": "senior",
                "name": "高级工作区",
                "tier": WorkTemplate.Tier.SENIOR,
                "desc": "高难度工作，回报丰厚，4小时完成",
            },
        ]

        # 获取当前工作区的配置
        current_tier_config = next((t for t in work_tiers if t["key"] == current_tier), work_tiers[0])
        current_tier = current_tier_config["key"]

        # 获取当前工作区的工作列表
        paginator = Paginator(
            WorkTemplate.objects.filter(tier=current_tier_config["tier"]).order_by("display_order"),
            self.WORKS_PER_PAGE,
        )
        page_obj = paginator.get_page(self.request.GET.get("page", 1))
        works = list(page_obj.object_list)

        # 获取所有空闲的门客
        idle_guests = list(
            manor.guests.filter(status=GuestStatus.IDLE).select_related("template").order_by("-level", "template__name")
        )

        # 获取未结算记录并映射到对应工作卡片（优先显示打工中，其次显示已完成待领取）
        pending_assignments = list(
            WorkAssignment.objects.filter(
                manor=manor,
                status__in=[WorkAssignment.Status.WORKING, WorkAssignment.Status.COMPLETED],
                reward_claimed=False,
            )
            .select_related("guest", "work_template")
            .order_by("work_template_id", "complete_at", "-started_at", "-id")
        )
        assignment_by_work_template_id: dict[int, WorkAssignment] = {}
        for assignment in sorted(
            pending_assignments,
            key=lambda item: (
                0 if item.status == WorkAssignment.Status.WORKING else 1,
                item.complete_at,
                -item.id,
            ),
        ):
            assignment_by_work_template_id.setdefault(assignment.work_template_id, assignment)

        for work in works:
            work.active_assignment = assignment_by_work_template_id.get(work.id)
            work.eligible_idle_guests = [
                guest
                for guest in idle_guests
                if (
                    guest.level >= work.required_level
                    and guest.force >= work.required_force
                    and guest.intellect >= work.required_intellect
                )
            ]

        context.update(
            {
                "manor": manor,
                "work_tiers": work_tiers,
                "current_tier": current_tier,
                "current_tier_config": current_tier_config,
                "works": works,
                "page_obj": page_obj,
                "is_paginated": page_obj.has_other_pages(),
            }
        )

        return context


@login_required
@require_POST
def assign_work_view(request: HttpRequest) -> HttpResponse:
    """派遣门客打工"""
    redirect_url = _resolve_work_redirect_url(request)
    manor = get_manor(request.user)
    guest_id = safe_positive_int(request.POST.get("guest_id"), default=None)
    work_key = (request.POST.get("work_key") or "").strip()

    if guest_id is None or not work_key:
        messages.error(request, "参数错误")
        return redirect(redirect_url)

    guest = get_object_or_404(Guest, id=guest_id, manor=manor)
    work_template = get_object_or_404(WorkTemplate, key=work_key)

    try:
        assign_guest_to_work(guest, work_template)
        # 计算完成时间（小时）
        hours = work_template.work_duration / 3600
        messages.success(request, f"{guest.display_name} 已前往 {work_template.name} 打工，预计 {hours:.1f} 小时后完成")
    except (GameError, ValueError) as exc:
        _handle_known_work_error(request, exc)
    except DatabaseError as exc:
        _handle_unexpected_work_error(
            request,
            exc,
            log_message="Unexpected work assign error: manor_id=%s user_id=%s guest_id=%s work_key=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                guest_id,
                work_key,
            ),
        )

    return redirect(redirect_url)


@login_required
@require_POST
def recall_work_view(request: HttpRequest, pk: int) -> HttpResponse:
    """召回打工中的门客"""
    redirect_url = _resolve_work_redirect_url(request)
    manor = get_manor(request.user)
    assignment = get_object_or_404(WorkAssignment, id=pk, manor=manor, status=WorkAssignment.Status.WORKING)

    try:
        recall_guest_from_work(assignment)
        messages.success(
            request, f"{assignment.guest.display_name} 已从 {assignment.work_template.name} 召回（无报酬）"
        )
    except (GameError, ValueError) as exc:
        _handle_known_work_error(request, exc)
    except DatabaseError as exc:
        _handle_unexpected_work_error(
            request,
            exc,
            log_message="Unexpected work recall error: manor_id=%s user_id=%s assignment_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                pk,
            ),
        )

    return redirect(redirect_url)


@login_required
@require_POST
def claim_work_reward_view(request: HttpRequest, pk: int) -> HttpResponse:
    """领取打工报酬"""
    redirect_url = _resolve_work_redirect_url(request)
    manor = get_manor(request.user)
    assignment = get_object_or_404(WorkAssignment, id=pk, manor=manor)

    try:
        reward = claim_work_reward(assignment)
        messages.success(request, f"{assignment.guest.display_name} 完成打工，获得银两 {reward['silver']}")
    except (GameError, ValueError) as exc:
        _handle_known_work_error(request, exc)
    except DatabaseError as exc:
        _handle_unexpected_work_error(
            request,
            exc,
            log_message="Unexpected work reward claim error: manor_id=%s user_id=%s assignment_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                pk,
            ),
        )

    return redirect(redirect_url)
