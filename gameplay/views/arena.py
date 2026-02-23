from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.utils import safe_positive_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect
from gameplay.selectors import get_arena_context
from gameplay.services import ensure_manor
from gameplay.services.arena.core import exchange_arena_reward, register_arena_entry

logger = logging.getLogger(__name__)


def _parse_guest_ids(raw_values: list[str]) -> list[int]:
    parsed: list[int] = []
    seen: set[int] = set()
    for raw in raw_values:
        guest_id = safe_positive_int(raw, default=None)
        if guest_id is None:
            raise ValueError("门客选择有误")
        if guest_id in seen:
            continue
        seen.add(guest_id)
        parsed.append(guest_id)
    return parsed


class ArenaView(LoginRequiredMixin, TemplateView):
    template_name = "gameplay/arena.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        context.update(get_arena_context(manor))
        return context


@login_required
@require_POST
@rate_limit_redirect("arena_register", limit=20, window_seconds=60)
def arena_register_view(request: HttpRequest) -> HttpResponse:
    manor = ensure_manor(request.user)
    try:
        guest_ids = _parse_guest_ids(request.POST.getlist("guest_ids"))
        result = register_arena_entry(manor, guest_ids)
        if result.auto_started:
            messages.success(
                request,
                f"报名成功！本场已满 {result.entry_count} 人，竞技场已自动开赛。",
            )
        else:
            messages.success(
                request,
                f"报名成功！当前已报名 {result.entry_count}/{result.tournament.player_limit} 人。",
            )
    except ValueError as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "arena register failed: user_id=%s manor_id=%s",
            getattr(request.user, "id", None),
            getattr(manor, "id", None),
        )
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:arena")


@login_required
@require_POST
@rate_limit_redirect("arena_exchange", limit=30, window_seconds=60)
def arena_exchange_view(request: HttpRequest) -> HttpResponse:
    manor = ensure_manor(request.user)
    reward_key = (request.POST.get("reward_key") or "").strip()
    quantity = safe_positive_int(request.POST.get("quantity"), default=1)

    if not reward_key:
        messages.error(request, "兑换项不能为空")
        return redirect("gameplay:arena")

    try:
        result = exchange_arena_reward(manor, reward_key, quantity=quantity)
        messages.success(
            request,
            f"兑换成功：{result.reward.name} x{result.quantity}，消耗角斗币 {result.total_cost}。",
        )
    except ValueError as exc:
        messages.error(request, sanitize_error_message(exc))
    except Exception as exc:
        logger.exception(
            "arena exchange failed: user_id=%s manor_id=%s reward=%s quantity=%s",
            getattr(request.user, "id", None),
            getattr(manor, "id", None),
            reward_key,
            quantity,
        )
        messages.error(request, sanitize_error_message(exc))

    return redirect("gameplay:arena")
