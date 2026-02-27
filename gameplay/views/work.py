"""
打工系统视图
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import safe_positive_int, sanitize_error_message
from gameplay.models import WorkAssignment, WorkTemplate
from gameplay.services import (
    assign_guest_to_work,
    claim_work_reward,
    ensure_manor,
    recall_guest_from_work,
    refresh_work_assignments,
)
from guests.models import Guest, GuestStatus

logger = logging.getLogger(__name__)


def _unexpected_work_error(
    request: HttpRequest,
    *,
    log_message: str,
    log_args: tuple[object, ...],
) -> None:
    logger.exception(log_message, *log_args)
    messages.error(request, "操作失败，请稍后重试")


class WorkView(LoginRequiredMixin, TemplateView):
    """打工页面"""

    template_name = "gameplay/work.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)

        # 刷新打工状态
        refresh_work_assignments(manor)

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

        # 获取当前工作区的工作列表
        works = list(WorkTemplate.objects.filter(tier=current_tier_config["tier"]).order_by("display_order"))

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
            }
        )

        return context


@login_required
@require_POST
def assign_work_view(request: HttpRequest) -> HttpResponse:
    """派遣门客打工"""
    manor = ensure_manor(request.user)
    guest_id = safe_positive_int(request.POST.get("guest_id"), default=None)
    work_key = (request.POST.get("work_key") or "").strip()

    if guest_id is None or not work_key:
        messages.error(request, "参数错误")
        return redirect("gameplay:work")

    guest = get_object_or_404(Guest, id=guest_id, manor=manor)
    work_template = get_object_or_404(WorkTemplate, key=work_key)

    try:
        assign_guest_to_work(guest, work_template)
        # 计算完成时间（小时）
        hours = work_template.work_duration / 3600
        messages.success(request, f"{guest.display_name} 已前往 {work_template.name} 打工，预计 {hours:.1f} 小时后完成")
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception:
        _unexpected_work_error(
            request,
            log_message="Unexpected work assign error: manor_id=%s user_id=%s guest_id=%s work_key=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                guest_id,
                work_key,
            ),
        )

    return redirect("gameplay:work")


@login_required
@require_POST
def recall_work_view(request: HttpRequest, pk: int) -> HttpResponse:
    """召回打工中的门客"""
    manor = ensure_manor(request.user)
    assignment = get_object_or_404(WorkAssignment, id=pk, manor=manor, status=WorkAssignment.Status.WORKING)

    try:
        recall_guest_from_work(assignment)
        messages.success(
            request, f"{assignment.guest.display_name} 已从 {assignment.work_template.name} 召回（无报酬）"
        )
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception:
        _unexpected_work_error(
            request,
            log_message="Unexpected work recall error: manor_id=%s user_id=%s assignment_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                pk,
            ),
        )

    return redirect("gameplay:work")


@login_required
@require_POST
def claim_work_reward_view(request: HttpRequest, pk: int) -> HttpResponse:
    """领取打工报酬"""
    manor = ensure_manor(request.user)
    assignment = get_object_or_404(WorkAssignment, id=pk, manor=manor)

    try:
        reward = claim_work_reward(assignment)
        messages.success(request, f"{assignment.guest.display_name} 完成打工，获得银两 {reward['silver']}")
    except (GameError, ValueError) as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception:
        _unexpected_work_error(
            request,
            log_message="Unexpected work reward claim error: manor_id=%s user_id=%s assignment_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                pk,
            ),
        )

    return redirect("gameplay:work")
