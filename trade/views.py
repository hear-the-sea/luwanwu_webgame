"""
交易视图
"""

import logging
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

from .selectors import get_trade_context
from .services.auction_service import place_bid
from .services.bank_service import exchange_gold_bar
from .services.market_service import cancel_listing, create_listing, purchase_listing
from .services.shop_service import buy_item, sell_item

logger = logging.getLogger(__name__)


def _trade_redirect(tab: str | None = None, view: str | None = None):
    base_url = reverse("trade:trade")
    params = {}
    if tab:
        params["tab"] = tab
    if view:
        params["view"] = view
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


def _get_positive_int_setting(name: str, default: int) -> int:
    value = safe_int(getattr(settings, name, default), default=default)
    if value is None or value <= 0:
        return default
    return value


class TradeView(LoginRequiredMixin, TemplateView):
    """交易主页面"""

    template_name = "trade/trade.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = self.request.user.manor
        context.update(get_trade_context(self.request, manor))

        return context


@login_required
@require_POST
@rate_limit_redirect("shop_buy", limit=10, window_seconds=60)
def shop_buy_view(request):
    """购买商品"""
    manor = request.user.manor
    item_key = request.POST.get("item_key", "")
    quantity = safe_int(request.POST.get("quantity", 1), default=1, min_val=1)

    try:
        result = buy_item(manor, item_key, quantity)
        messages.success(
            request, f"成功购买 {result['item_name']} x{result['quantity']}，花费 {result['total_cost']} 银两"
        )
    except (GameError, ValueError) as exc:
        _handle_trade_error(request, exc)
    except Exception as exc:
        _handle_unexpected_trade_error(request, exc, op="shop_buy")

    return _trade_redirect()


@login_required
@require_POST
@rate_limit_redirect("shop_sell", limit=10, window_seconds=60)
def shop_sell_view(request):
    """出售物品"""
    manor = request.user.manor
    item_key = request.POST.get("item_key", "")
    quantity = safe_int(request.POST.get("quantity", 1), default=1, min_val=1)

    try:
        result = sell_item(manor, item_key, quantity)
        messages.success(
            request, f"成功出售 {result['item_name']} x{result['quantity']}，获得 {result['total_income']} 银两"
        )
    except (GameError, ValueError) as exc:
        _handle_trade_error(request, exc)
    except Exception as exc:
        _handle_unexpected_trade_error(request, exc, op="shop_sell")

    return _trade_redirect()


@login_required
@require_POST
@rate_limit_redirect("bank_exchange", limit=5, window_seconds=60)
def exchange_gold_bar_view(request):
    """兑换金条"""
    manor = request.user.manor
    quantity = safe_int(request.POST.get("quantity", 1), default=1, min_val=1)

    try:
        result = exchange_gold_bar(manor, quantity)
        messages.success(
            request,
            f"成功兑换 {result['quantity']} 根金条，花费 {result['total_cost']:,} 银两"
            f"（含手续费 {result['fee']:,} 银两）。下一根汇率：{result['next_rate']:,} 银两。",
        )
    except (GameError, ValueError) as exc:
        _handle_trade_error(request, exc)
    except Exception as exc:
        _handle_unexpected_trade_error(request, exc, op="bank_exchange")

    return _trade_redirect(tab="bank")


@login_required
@require_POST
@rate_limit_redirect("market_create", limit=10, window_seconds=60)
def market_create_listing_view(request):
    """创建交易行挂单"""
    manor = request.user.manor
    item_key = request.POST.get("item_key", "")
    quantity = safe_int(request.POST.get("quantity", 1), default=1, min_val=1)
    unit_price = safe_int(request.POST.get("unit_price", 0), default=0, min_val=0)
    duration = safe_int(request.POST.get("duration", 7200), default=7200, min_val=7200, max_val=86400)

    try:
        listing = create_listing(manor, item_key, quantity, unit_price, duration)
        messages.success(
            request,
            f"成功上架 {listing.item_template.name} x{quantity}，单价 {unit_price} 银两，"
            f"总价 {listing.total_price:,} 银两。上架时长 {listing.get_duration_display()}。",
        )
    except (GameError, ValueError) as exc:
        _handle_trade_error(request, exc)
    except Exception as exc:
        _handle_unexpected_trade_error(request, exc, op="market_create_listing")

    return _trade_redirect(tab="market", view="sell")


@login_required
@require_POST
@rate_limit_redirect("market_purchase", limit=10, window_seconds=60)
def market_purchase_view(request, listing_id: int):
    """购买交易行物品"""
    manor = request.user.manor

    try:
        transaction = purchase_listing(manor, listing_id)
        high_value_threshold = _get_positive_int_setting("TRADE_HIGH_VALUE_SILVER_THRESHOLD", 1_000_000)
        if transaction.total_price >= high_value_threshold:
            logger.warning(
                "High-value market purchase: user_id=%s listing_id=%s total_price=%s",
                request.user.id,
                listing_id,
                transaction.total_price,
            )
        messages.success(
            request,
            f"成功购买 {transaction.listing.item_template.name} x{transaction.listing.quantity}，"
            f"花费 {transaction.total_price:,} 银两。物品已直接存入仓库，请查收！",
        )
    except (GameError, ValueError) as exc:
        _handle_trade_error(request, exc)
    except Exception as exc:
        _handle_unexpected_trade_error(request, exc, op="market_purchase")

    return _trade_redirect(tab="market", view="buy")


@login_required
@require_POST
@rate_limit_redirect("market_cancel", limit=20, window_seconds=60)
def market_cancel_view(request, listing_id: int):
    """取消交易行挂单"""
    manor = request.user.manor

    try:
        result = cancel_listing(manor, listing_id)
        messages.success(
            request,
            f"已取消挂单，{result['item_name']} x{result['quantity']} 已退回仓库。",
        )
    except (GameError, ValueError) as exc:
        _handle_trade_error(request, exc)
    except Exception as exc:
        _handle_unexpected_trade_error(request, exc, op="market_cancel")

    return _trade_redirect(tab="market", view="my_listings")


@login_required
@require_POST
@rate_limit_redirect("auction_bid", limit=15, window_seconds=60)
def auction_bid_view(request, slot_id: int):
    """拍卖行出价"""
    manor = request.user.manor
    amount = safe_int(request.POST.get("amount", 0), default=0, min_val=1)

    try:
        _bid, is_first_bid = place_bid(manor, slot_id, amount)
        high_bid_threshold = _get_positive_int_setting("AUCTION_HIGH_BID_THRESHOLD", 200)
        if amount >= high_bid_threshold:
            logger.warning(
                "High-value auction bid: user_id=%s slot_id=%s amount=%s",
                request.user.id,
                slot_id,
                amount,
            )
        if is_first_bid:
            messages.success(
                request,
                f"成功出价 {amount} 金条！您目前是最高出价者。",
            )
        else:
            messages.success(
                request,
                f"成功加价至 {amount} 金条！您目前是最高出价者。",
            )
    except (GameError, ValueError) as exc:
        _handle_trade_error(request, exc)
    except Exception as exc:
        _handle_unexpected_trade_error(request, exc, op="auction_bid")

    return _trade_redirect(tab="auction")
