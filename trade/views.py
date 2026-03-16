"""交易视图。"""

import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.utils import safe_int
from core.utils.rate_limit import rate_limit_redirect
from gameplay.models import Manor
from gameplay.services.manor import get_manor
from trade.selectors import get_trade_context
from trade.services.auction_service import place_bid
from trade.services.bank_service import exchange_gold_bar
from trade.services.market_service import LISTING_FEES, cancel_listing, create_listing, purchase_listing
from trade.services.shop_service import buy_item, sell_item
from trade.view_helpers import execute_manor_trade_action_and_redirect as _execute_manor_trade_action_and_redirect
from trade.view_helpers import handle_troop_bank_transfer as _handle_troop_bank_transfer
from trade.view_helpers import parse_market_listing_form as _parse_market_listing_form
from trade.view_helpers import parse_positive_post_int_or_redirect as _parse_positive_post_int_or_redirect
from trade.view_helpers import parse_required_post_text as _parse_required_post_text
from trade.view_helpers import parse_trade_item_quantity_form as _parse_trade_item_quantity_form

logger = logging.getLogger(__name__)
ALLOWED_MARKET_DURATIONS = frozenset(LISTING_FEES.keys())


def _get_positive_int_setting(name: str, default: int) -> int:
    value = safe_int(getattr(settings, name, default), default=default)
    if value is None or value <= 0:
        return default
    return value


def _warn_if_threshold_exceeded(
    *,
    setting_name: str,
    default: int,
    value: int,
    log_message: str,
    log_args: tuple[object, ...],
):
    threshold = _get_positive_int_setting(setting_name, default)
    if value >= threshold:
        logger.warning(log_message, *log_args)


class TradeView(LoginRequiredMixin, TemplateView):
    """交易主页面"""

    template_name = "trade/trade.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = get_manor(self.request.user)
        context.update(get_trade_context(self.request, manor))

        return context


@login_required
@require_POST
@rate_limit_redirect("shop_buy", limit=10, window_seconds=60)
def shop_buy_view(request):
    """购买商品"""
    parsed = _parse_trade_item_quantity_form(request, tab="shop", view="buy")
    if isinstance(parsed, HttpResponseRedirect):
        return parsed

    return _execute_manor_trade_action_and_redirect(
        request,
        op="shop_buy",
        action_factory=lambda manor: buy_item(manor, parsed.item_key, parsed.quantity),
        success_message=lambda result: f"成功购买 {result['item_name']} x{result['quantity']}，花费 {result['total_cost']} 银两",
        tab="shop",
        view="buy",
    )


@login_required
@require_POST
@rate_limit_redirect("shop_sell", limit=10, window_seconds=60)
def shop_sell_view(request):
    """出售物品"""
    parsed = _parse_trade_item_quantity_form(request, tab="shop", view="sell")
    if isinstance(parsed, HttpResponseRedirect):
        return parsed

    return _execute_manor_trade_action_and_redirect(
        request,
        op="shop_sell",
        action_factory=lambda manor: sell_item(manor, parsed.item_key, parsed.quantity),
        success_message=lambda result: f"成功出售 {result['item_name']} x{result['quantity']}，获得 {result['total_income']} 银两",
        tab="shop",
        view="sell",
    )


@login_required
@require_POST
@rate_limit_redirect("bank_exchange", limit=5, window_seconds=60)
def exchange_gold_bar_view(request):
    """兑换金条"""
    troop_category = _parse_required_post_text(request, "troop_category") or ""
    quantity = _parse_positive_post_int_or_redirect(
        request,
        "quantity",
        "数量参数无效",
        tab="bank",
        troop_category=troop_category,
    )
    if isinstance(quantity, HttpResponseRedirect):
        return quantity

    return _execute_manor_trade_action_and_redirect(
        request,
        op="bank_exchange",
        action_factory=lambda manor: exchange_gold_bar(manor, quantity),
        success_message=lambda result: (
            f"成功兑换 {result['quantity']} 根金条，花费 {result['total_cost']:,} 银两"
            f"（含手续费 {result['fee']:,} 银两）。下一根汇率：{result['next_rate']:,} 银两。"
        ),
        tab="bank",
        troop_category=troop_category,
    )


@login_required
@require_POST
@rate_limit_redirect("bank_troop_deposit", limit=30, window_seconds=60)
def deposit_troop_to_bank_view(request):
    """钱庄存入护院"""

    def _deposit(manor, troop_key: str, quantity: int):
        from gameplay.services.manor.troop_bank import deposit_troops_to_bank

        return deposit_troops_to_bank(manor, troop_key, quantity)

    return _handle_troop_bank_transfer(
        request,
        op="bank_troop_deposit",
        transfer_action=_deposit,
        success_message=lambda result: f"已存入 {result['quantity']} 名{result['troop_name']}到钱庄",
    )


@login_required
@require_POST
@rate_limit_redirect("bank_troop_withdraw", limit=30, window_seconds=60)
def withdraw_troop_from_bank_view(request):
    """钱庄取出护院"""

    def _withdraw(manor, troop_key: str, quantity: int):
        from gameplay.services.manor.troop_bank import withdraw_troops_from_bank

        return withdraw_troops_from_bank(manor, troop_key, quantity)

    return _handle_troop_bank_transfer(
        request,
        op="bank_troop_withdraw",
        transfer_action=_withdraw,
        success_message=lambda result: f"已从钱庄取出 {result['quantity']} 名{result['troop_name']}",
    )


@login_required
@require_POST
@rate_limit_redirect("market_create", limit=10, window_seconds=60)
def market_create_listing_view(request):
    """创建交易行挂单"""
    parsed = _parse_market_listing_form(request, allowed_durations=ALLOWED_MARKET_DURATIONS)
    if isinstance(parsed, HttpResponseRedirect):
        return parsed

    return _execute_manor_trade_action_and_redirect(
        request,
        op="market_create_listing",
        action_factory=lambda manor: create_listing(
            manor, parsed.item_key, parsed.quantity, parsed.unit_price, parsed.duration
        ),
        success_message=lambda listing: (
            f"成功上架 {listing.item_template.name} x{parsed.quantity}，单价 {parsed.unit_price} 银两，"
            f"总价 {listing.total_price:,} 银两。上架时长 {listing.get_duration_display()}。"
        ),
        tab="market",
        view="sell",
    )


@login_required
@require_POST
@rate_limit_redirect("market_purchase", limit=10, window_seconds=60)
def market_purchase_view(request, listing_id: int):
    """购买交易行物品"""

    def _purchase(manor: Manor):
        transaction = purchase_listing(manor, listing_id)
        _warn_if_threshold_exceeded(
            setting_name="TRADE_HIGH_VALUE_SILVER_THRESHOLD",
            default=1_000_000,
            value=transaction.total_price,
            log_message="High-value market purchase: user_id=%s listing_id=%s total_price=%s",
            log_args=(request.user.id, listing_id, transaction.total_price),
        )
        return transaction

    return _execute_manor_trade_action_and_redirect(
        request,
        op="market_purchase",
        action_factory=_purchase,
        success_message=lambda transaction: (
            f"成功购买 {transaction.listing.item_template.name} x{transaction.listing.quantity}，"
            f"花费 {transaction.total_price:,} 银两。物品已直接存入仓库，请查收！"
        ),
        tab="market",
        view="buy",
    )


@login_required
@require_POST
@rate_limit_redirect("market_cancel", limit=20, window_seconds=60)
def market_cancel_view(request, listing_id: int):
    """取消交易行挂单"""
    return _execute_manor_trade_action_and_redirect(
        request,
        op="market_cancel",
        action_factory=lambda manor: cancel_listing(manor, listing_id),
        success_message=lambda result: f"已取消挂单，{result['item_name']} x{result['quantity']} 已退回仓库。",
        tab="market",
        view="my_listings",
    )


@login_required
@require_POST
@rate_limit_redirect("auction_bid", limit=15, window_seconds=60)
def auction_bid_view(request, slot_id: int):
    """拍卖行出价"""
    amount = _parse_positive_post_int_or_redirect(request, "amount", "出价参数无效", tab="auction")
    if isinstance(amount, HttpResponseRedirect):
        return amount

    def _place_bid(manor: Manor):
        _bid, is_first_bid = place_bid(manor, slot_id, amount)
        _warn_if_threshold_exceeded(
            setting_name="AUCTION_HIGH_BID_THRESHOLD",
            default=200,
            value=amount,
            log_message="High-value auction bid: user_id=%s slot_id=%s amount=%s",
            log_args=(request.user.id, slot_id, amount),
        )
        return is_first_bid

    return _execute_manor_trade_action_and_redirect(
        request,
        op="auction_bid",
        action_factory=_place_bid,
        success_message=lambda is_first_bid: (
            f"成功出价 {amount} 金条！您目前是最高出价者。"
            if is_first_bid
            else f"成功加价至 {amount} 金条！您目前是最高出价者。"
        ),
        tab="auction",
    )
