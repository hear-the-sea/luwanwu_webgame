from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.decorators import flash_unexpected_view_error
from core.utils import safe_positive_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect
from gameplay.selectors import (
    get_arena_event_detail_context,
    get_arena_events_context,
    get_arena_exchange_context,
    get_arena_registration_context,
)
from gameplay.services.arena.core import (
    ARENA_REGISTRATION_SILVER_COST,
    cancel_arena_entry,
    exchange_arena_reward,
    register_arena_entry,
)
from gameplay.services.manor.core import get_manor
from gameplay.utils.template_loader import get_item_template_names_by_keys

logger = logging.getLogger(__name__)

ARENA_TAB_REGISTRATION = "registration"
ARENA_TAB_EVENTS = "events"
ARENA_TAB_EXCHANGE = "exchange"


def _handle_known_arena_error(request: HttpRequest, exc: ValueError) -> None:
    messages.error(request, sanitize_error_message(exc))


def _handle_unexpected_arena_error(
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


def _resolve_safe_next_url(request: HttpRequest, *, default_view_name: str) -> str:
    candidate = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse(default_view_name)


class BaseArenaView(LoginRequiredMixin, TemplateView):
    active_tab = ARENA_TAB_REGISTRATION
    template_name = "gameplay/arena/registration.html"
    show_arena_hero_card = True

    def _build_page_context(self, manor):
        raise NotImplementedError

    def _build_tabs(self):
        return [
            {
                "key": ARENA_TAB_REGISTRATION,
                "label": "赛事报名",
                "url": reverse("gameplay:arena"),
                "active": self.active_tab == ARENA_TAB_REGISTRATION,
            },
            {
                "key": ARENA_TAB_EVENTS,
                "label": "赛事查看",
                "url": reverse("gameplay:arena_events"),
                "active": self.active_tab == ARENA_TAB_EVENTS,
            },
            {
                "key": ARENA_TAB_EXCHANGE,
                "label": "奖励兑换",
                "url": reverse("gameplay:arena_exchange_page"),
                "active": self.active_tab == ARENA_TAB_EXCHANGE,
            },
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = get_manor(self.request.user)
        context.update(self._build_page_context(manor))
        context["arena_tabs"] = self._build_tabs()
        context["arena_active_tab"] = self.active_tab
        context["show_arena_hero_card"] = self.show_arena_hero_card
        return context


class ArenaView(BaseArenaView):
    active_tab = ARENA_TAB_REGISTRATION
    template_name = "gameplay/arena/registration.html"

    def _build_page_context(self, manor):
        return get_arena_registration_context(manor)


class ArenaEventsView(BaseArenaView):
    active_tab = ARENA_TAB_EVENTS
    template_name = "gameplay/arena/events.html"
    show_arena_hero_card = False

    def _build_page_context(self, manor):
        return get_arena_events_context(manor)


class ArenaExchangePageView(BaseArenaView):
    active_tab = ARENA_TAB_EXCHANGE
    template_name = "gameplay/arena/exchange.html"
    show_arena_hero_card = False

    def _build_page_context(self, manor):
        return get_arena_exchange_context(manor)


class ArenaEventDetailView(BaseArenaView):
    active_tab = ARENA_TAB_EVENTS
    template_name = "gameplay/arena/event_detail.html"
    show_arena_hero_card = False

    def _build_page_context(self, manor):
        tournament_id = safe_positive_int(self.kwargs.get("tournament_id"), default=None)
        if tournament_id is None:
            raise Http404("赛事不存在")
        selected_round = safe_positive_int(self.request.GET.get("round"), default=None)
        context = get_arena_event_detail_context(manor, tournament_id=tournament_id, selected_round=selected_round)
        if context is None:
            raise Http404("赛事不存在或已不可查看")
        return context


@login_required
@require_POST
@rate_limit_redirect("arena_register", limit=20, window_seconds=60)
def arena_register_view(request: HttpRequest) -> HttpResponse:
    manor = get_manor(request.user)
    redirect_target = _resolve_safe_next_url(request, default_view_name="gameplay:arena")
    try:
        guest_ids = _parse_guest_ids(request.POST.getlist("guest_ids"))
        result = register_arena_entry(manor, guest_ids)
        if result.auto_started:
            messages.success(
                request,
                f"报名成功！消耗银两 {ARENA_REGISTRATION_SILVER_COST}。本场已满 {result.entry_count} 人，竞技场已自动开赛。",
            )
        else:
            messages.success(
                request,
                f"报名成功！消耗银两 {ARENA_REGISTRATION_SILVER_COST}。当前已报名 {result.entry_count}/{result.tournament.player_limit} 人。",
            )
    except ValueError as exc:
        _handle_known_arena_error(request, exc)
    except DatabaseError as exc:
        _handle_unexpected_arena_error(
            request,
            exc,
            log_message="arena register failed: user_id=%s manor_id=%s",
            log_args=(
                getattr(request.user, "id", None),
                getattr(manor, "id", None),
            ),
        )

    return redirect(redirect_target)


@login_required
@require_POST
@rate_limit_redirect("arena_cancel", limit=20, window_seconds=60)
def arena_cancel_view(request: HttpRequest) -> HttpResponse:
    manor = get_manor(request.user)
    redirect_target = _resolve_safe_next_url(request, default_view_name="gameplay:arena")
    try:
        canceled_count = cancel_arena_entry(manor)
        messages.success(
            request,
            f"已撤销报名（{canceled_count} 条），可重新报名（报名费 {ARENA_REGISTRATION_SILVER_COST} 银两不返还）。",
        )
    except ValueError as exc:
        _handle_known_arena_error(request, exc)
    except DatabaseError as exc:
        _handle_unexpected_arena_error(
            request,
            exc,
            log_message="arena cancel failed: user_id=%s manor_id=%s",
            log_args=(
                getattr(request.user, "id", None),
                getattr(manor, "id", None),
            ),
        )

    return redirect(redirect_target)


@login_required
@require_POST
@rate_limit_redirect("arena_exchange", limit=30, window_seconds=60)
def arena_exchange_view(request: HttpRequest) -> HttpResponse:
    manor = get_manor(request.user)
    redirect_target = _resolve_safe_next_url(request, default_view_name="gameplay:arena")
    reward_key = (request.POST.get("reward_key") or "").strip()
    quantity = safe_positive_int(request.POST.get("quantity"), default=1)

    if not reward_key:
        messages.error(request, "兑换项不能为空")
        return redirect(redirect_target)

    try:
        result = exchange_arena_reward(manor, reward_key, quantity=quantity)
        random_draw_summary = ""
        if result.random_granted_items:
            item_names = get_item_template_names_by_keys(result.random_granted_items.keys())
            parts: list[str] = []
            for item_key in sorted(result.random_granted_items.keys()):
                item_name = item_names.get(item_key, item_key)
                item_amount = result.random_granted_items[item_key]
                parts.append(f"{item_name}x{item_amount}")
            random_draw_summary = f" 本次抽到：{'、'.join(parts)}。"
        messages.success(
            request,
            f"兑换成功：{result.reward.name} x{result.quantity}，消耗角斗币 {result.total_cost}。{random_draw_summary}",
        )
    except ValueError as exc:
        _handle_known_arena_error(request, exc)
    except DatabaseError as exc:
        _handle_unexpected_arena_error(
            request,
            exc,
            log_message="arena exchange failed: user_id=%s manor_id=%s reward=%s quantity=%s",
            log_args=(
                getattr(request.user, "id", None),
                getattr(manor, "id", None),
                reward_key,
                quantity,
            ),
        )

    return redirect(redirect_target)
