"""交易视图。"""

import logging
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.exceptions import GameError
from core.utils import safe_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect
from gameplay.services import ensure_manor

from .selectors import get_trade_context
from .services.auction_service import place_bid
from .services.bank_service import exchange_gold_bar
from .services.market_service import cancel_listing, create_listing, purchase_listing
from .services.shop_service import buy_item, sell_item

logger = logging.getLogger(__name__)
ALLOWED_MARKET_DURATIONS = frozenset({7200, 28800, 86400})
TradeResult = TypeVar("TradeResult")


def _trade_redirect(tab: str | None = None, view: str | None = None, troop_category: str | None = None):
    base_url = reverse("trade:trade")
    params = {}
    if tab:
        params["tab"] = tab
    if view:
        params["view"] = view
    normalized_troop_category = (troop_category or "").strip()
    if normalized_troop_category and normalized_troop_category != "all":
        params["troop_category"] = normalized_troop_category
    if not params:
        return redirect(base_url)
    return redirect(f"{base_url}?{urlencode(params)}")


def _handle_trade_error(request, exc: Exception) -> None:
    messages.error(request, sanitize_error_message(exc))


def _handle_unexpected_trade_error(request, exc: Exception, *, op: str) -> None:
    logger.exception(
        "trade view unexpected error: op=%s user_id=%s error=%s", op, getattr(request.user, "id", None), exc
    )
    _handle_trade_error(request, exc)


def _execute_trade_action(
    request,
    *,
    op: str,
    action: Callable[[], TradeResult],
    success_message: Callable[[TradeResult], str],
) -> None:
    try:
        result = action()
        messages.success(request, success_message(result))
    except (GameError, ValueError) as exc:
        _handle_trade_error(request, exc)
    except Exception as exc:
        _handle_unexpected_trade_error(request, exc, op=op)


def _get_positive_int_setting(name: str, default: int) -> int:
    value = safe_int(getattr(settings, name, default), default=default)
    if value is None or value <= 0:
        return default
    return value


def _parse_positive_post_int(request, field: str) -> int | None:
    value = safe_int(request.POST.get(field), default=None)
    if value is None or value <= 0:
        return None
    return value


def _parse_non_negative_post_int(request, field: str) -> int | None:
    value = safe_int(request.POST.get(field), default=None)
    if value is None or value < 0:
        return None
    return value


def _parse_market_duration(request) -> int | None:
    duration = safe_int(request.POST.get("duration"), default=None)
    if duration is None:
        return None
    if duration not in ALLOWED_MARKET_DURATIONS:
        return None
    return duration


class TradeView(LoginRequiredMixin, TemplateView):
    """交易主页面"""

    template_name = "trade/trade.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)
        context.update(get_trade_context(self.request, manor))

        return context


@login_required
@require_POST
@rate_limit_redirect("shop_buy", limit=10, window_seconds=60)
def shop_buy_view(request):
    """购买商品"""
    manor = ensure_manor(request.user)
    item_key = (request.POST.get("item_key") or "").strip()
    if not item_key:
        messages.error(request, "请选择商品")
        return _trade_redirect()
    quantity = _parse_positive_post_int(request, "quantity")
    if quantity is None:
        messages.error(request, "数量参数无效")
        return _trade_redirect()

    _execute_trade_action(
        request,
        op="shop_buy",
        action=lambda: buy_item(manor, item_key, quantity),
        success_message=lambda result: f"成功购买 {result['item_name']} x{result['quantity']}，花费 {result['total_cost']} 银两",
    )

    return _trade_redirect()


@login_required
@require_POST
@rate_limit_redirect("shop_sell", limit=10, window_seconds=60)
def shop_sell_view(request):
    """出售物品"""
    manor = ensure_manor(request.user)
    item_key = (request.POST.get("item_key") or "").strip()
    if not item_key:
        messages.error(request, "请选择商品")
        return _trade_redirect()
    quantity = _parse_positive_post_int(request, "quantity")
    if quantity is None:
        messages.error(request, "数量参数无效")
        return _trade_redirect()

    _execute_trade_action(
        request,
        op="shop_sell",
        action=lambda: sell_item(manor, item_key, quantity),
        success_message=lambda result: f"成功出售 {result['item_name']} x{result['quantity']}，获得 {result['total_income']} 银两",
    )

    return _trade_redirect()


@login_required
@require_POST
@rate_limit_redirect("bank_exchange", limit=5, window_seconds=60)
def exchange_gold_bar_view(request):
    """兑换金条"""
    manor = ensure_manor(request.user)
    troop_category = (request.POST.get("troop_category") or "").strip()
    quantity = _parse_positive_post_int(request, "quantity")
    if quantity is None:
        messages.error(request, "数量参数无效")
        return _trade_redirect(tab="bank", troop_category=troop_category)

    _execute_trade_action(
        request,
        op="bank_exchange",
        action=lambda: exchange_gold_bar(manor, quantity),
        success_message=lambda result: (
            f"成功兑换 {result['quantity']} 根金条，花费 {result['total_cost']:,} 银两"
            f"（含手续费 {result['fee']:,} 银两）。下一根汇率：{result['next_rate']:,} 银两。"
        ),
    )

    return _trade_redirect(tab="bank", troop_category=troop_category)


@login_required
@require_POST
@rate_limit_redirect("bank_troop_deposit", limit=30, window_seconds=60)
def deposit_troop_to_bank_view(request):
    """钱庄存入护院"""
    manor = ensure_manor(request.user)
    troop_category = (request.POST.get("troop_category") or "").strip()
    troop_key = (request.POST.get("troop_key") or "").strip()
    quantity = _parse_positive_post_int(request, "quantity")

    if not troop_key:
        messages.error(request, "请选择护院类型")
        return _trade_redirect(tab="bank", troop_category=troop_category)
    if quantity is None:
        messages.error(request, "数量参数无效")
        return _trade_redirect(tab="bank", troop_category=troop_category)

    def _deposit():
        from gameplay.services.manor.troop_bank import deposit_troops_to_bank

        return deposit_troops_to_bank(manor, troop_key, quantity)

    _execute_trade_action(
        request,
        op="bank_troop_deposit",
        action=_deposit,
        success_message=lambda result: f"已存入 {result['quantity']} 名{result['troop_name']}到钱庄",
    )

    return _trade_redirect(tab="bank", troop_category=troop_category)


@login_required
@require_POST
@rate_limit_redirect("bank_troop_withdraw", limit=30, window_seconds=60)
def withdraw_troop_from_bank_view(request):
    """钱庄取出护院"""
    manor = ensure_manor(request.user)
    troop_category = (request.POST.get("troop_category") or "").strip()
    troop_key = (request.POST.get("troop_key") or "").strip()
    quantity = _parse_positive_post_int(request, "quantity")

    if not troop_key:
        messages.error(request, "请选择护院类型")
        return _trade_redirect(tab="bank", troop_category=troop_category)
    if quantity is None:
        messages.error(request, "数量参数无效")
        return _trade_redirect(tab="bank", troop_category=troop_category)

    def _withdraw():
        from gameplay.services.manor.troop_bank import withdraw_troops_from_bank

        return withdraw_troops_from_bank(manor, troop_key, quantity)

    _execute_trade_action(
        request,
        op="bank_troop_withdraw",
        action=_withdraw,
        success_message=lambda result: f"已从钱庄取出 {result['quantity']} 名{result['troop_name']}",
    )

    return _trade_redirect(tab="bank", troop_category=troop_category)


@login_required
@require_POST
@rate_limit_redirect("market_create", limit=10, window_seconds=60)
def market_create_listing_view(request):
    """创建交易行挂单"""
    manor = ensure_manor(request.user)
    item_key = (request.POST.get("item_key") or "").strip()
    if not item_key:
        messages.error(request, "请选择商品")
        return _trade_redirect(tab="market", view="sell")
    quantity = _parse_positive_post_int(request, "quantity")
    unit_price = _parse_non_negative_post_int(request, "unit_price")
    duration = _parse_market_duration(request)
    if quantity is None:
        messages.error(request, "数量参数无效")
        return _trade_redirect(tab="market", view="sell")
    if unit_price is None:
        messages.error(request, "单价参数无效")
        return _trade_redirect(tab="market", view="sell")
    if duration is None:
        messages.error(request, "时长参数无效")
        return _trade_redirect(tab="market", view="sell")

    _execute_trade_action(
        request,
        op="market_create_listing",
        action=lambda: create_listing(manor, item_key, quantity, unit_price, duration),
        success_message=lambda listing: (
            f"成功上架 {listing.item_template.name} x{quantity}，单价 {unit_price} 银两，"
            f"总价 {listing.total_price:,} 银两。上架时长 {listing.get_duration_display()}。"
        ),
    )

    return _trade_redirect(tab="market", view="sell")


@login_required
@require_POST
@rate_limit_redirect("market_purchase", limit=10, window_seconds=60)
def market_purchase_view(request, listing_id: int):
    """购买交易行物品"""
    manor = ensure_manor(request.user)

    def _purchase():
        transaction = purchase_listing(manor, listing_id)
        high_value_threshold = _get_positive_int_setting("TRADE_HIGH_VALUE_SILVER_THRESHOLD", 1_000_000)
        if transaction.total_price >= high_value_threshold:
            logger.warning(
                "High-value market purchase: user_id=%s listing_id=%s total_price=%s",
                request.user.id,
                listing_id,
                transaction.total_price,
            )
        return transaction

    _execute_trade_action(
        request,
        op="market_purchase",
        action=_purchase,
        success_message=lambda transaction: (
            f"成功购买 {transaction.listing.item_template.name} x{transaction.listing.quantity}，"
            f"花费 {transaction.total_price:,} 银两。物品已直接存入仓库，请查收！"
        ),
    )

    return _trade_redirect(tab="market", view="buy")


@login_required
@require_POST
@rate_limit_redirect("market_cancel", limit=20, window_seconds=60)
def market_cancel_view(request, listing_id: int):
    """取消交易行挂单"""
    manor = ensure_manor(request.user)

    _execute_trade_action(
        request,
        op="market_cancel",
        action=lambda: cancel_listing(manor, listing_id),
        success_message=lambda result: f"已取消挂单，{result['item_name']} x{result['quantity']} 已退回仓库。",
    )

    return _trade_redirect(tab="market", view="my_listings")


@login_required
@require_POST
@rate_limit_redirect("auction_bid", limit=15, window_seconds=60)
def auction_bid_view(request, slot_id: int):
    """拍卖行出价"""
    manor = ensure_manor(request.user)
    amount = _parse_positive_post_int(request, "amount")
    if amount is None:
        messages.error(request, "出价参数无效")
        return _trade_redirect(tab="auction")

    def _place_bid():
        _bid, is_first_bid = place_bid(manor, slot_id, amount)
        high_bid_threshold = _get_positive_int_setting("AUCTION_HIGH_BID_THRESHOLD", 200)
        if amount >= high_bid_threshold:
            logger.warning(
                "High-value auction bid: user_id=%s slot_id=%s amount=%s",
                request.user.id,
                slot_id,
                amount,
            )
        return is_first_bid

    _execute_trade_action(
        request,
        op="auction_bid",
        action=_place_bid,
        success_message=lambda is_first_bid: (
            f"成功出价 {amount} 金条！您目前是最高出价者。"
            if is_first_bid
            else f"成功加价至 {amount} 金条！您目前是最高出价者。"
        ),
    )

    return _trade_redirect(tab="auction")
