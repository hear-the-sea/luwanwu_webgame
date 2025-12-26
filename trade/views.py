"""
交易视图
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.utils import safe_int, safe_ordering, sanitize_error_message
from gameplay.services.resources import sync_resource_production

from .services.auction_service import (
    get_active_slots,
    get_auction_stats,
    get_my_bids,
    get_my_leading_bids,
    get_slot_bid_info,
    place_bid,
)
from .services.bank_service import exchange_gold_bar, get_bank_info
from .services.market_service import (
    cancel_listing,
    create_listing,
    expire_user_listings,
    get_active_listings,
    get_my_listings,
    get_tradeable_inventory,
    purchase_listing,
)
from .services.shop_service import (
    EFFECT_TYPE_CATEGORY,
    buy_item,
    get_sellable_inventory,
    get_shop_items_for_display,
    sell_item,
)


class TradeView(LoginRequiredMixin, TemplateView):
    """交易主页面"""

    template_name = "trade/trade.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = self.request.user.manor

        # 同步资源产出
        sync_resource_production(manor)
        tab = self.request.GET.get("tab", "shop")
        context["current_tab"] = tab
        context["tabs"] = [
            {"key": "auction", "name": "拍卖行"},
            {"key": "bank", "name": "钱庄"},
            {"key": "shop", "name": "商店"},
            {"key": "market", "name": "集市"},
        ]
        context["manor"] = manor

        if tab == "auction":
            # 拍卖行逻辑
            auction_stats = get_auction_stats(manor)
            context["auction_stats"] = auction_stats

            auction_view = self.request.GET.get("view", "browse")
            context["auction_view"] = auction_view

            if auction_view == "browse":
                # 浏览拍卖位
                category = self.request.GET.get("category", "all")
                rarity = self.request.GET.get("rarity", "all")
                order_by = safe_ordering(
                    self.request.GET.get("order_by", "-current_price"),
                    "-current_price",
                    {"-current_price", "current_price", "-bid_count", "bid_count"}
                )
                page = safe_int(self.request.GET.get("page", 1), 1)

                slots = get_active_slots(
                    category=category,
                    rarity=rarity,
                    order_by=order_by,
                )

                # 分页处理，每页5个
                paginator = Paginator(slots, 5)
                page_obj = paginator.get_page(page)

                # 为当前页的拍卖位添加维克里拍卖的出价信息
                slots_with_info = []
                for slot in page_obj:
                    bid_info = get_slot_bid_info(slot, manor)
                    slot.bid_info = bid_info  # 动态附加属性
                    slots_with_info.append(slot)

                context["auction_slots"] = slots_with_info
                context["page_obj"] = page_obj
                context["selected_category"] = category
                context["selected_rarity"] = rarity
                context["selected_order"] = order_by

                # 类别选项
                categories = [{"key": "all", "label": "全部"}] + [
                    {"key": c, "label": EFFECT_TYPE_CATEGORY.get(c, c)}
                    for c in sorted(EFFECT_TYPE_CATEGORY.keys())
                ]
                context["categories"] = categories

            elif auction_view == "my_bids":
                # 我的竞拍
                my_bids = get_my_bids(manor)
                my_leading = get_my_leading_bids(manor)

                # 为我的安全拍卖位添加出价信息
                for slot in my_leading:
                    slot.bid_info = get_slot_bid_info(slot, manor)

                context["my_bids"] = my_bids
                context["my_leading_slots"] = my_leading

        elif tab == "shop":
            def normalize_effect_type(effect_type: str) -> str:
                effect_type = effect_type or "other"
                if effect_type in {"magnifying_glass", "peace_shield", "manor_rename"}:
                    return "tool"
                return effect_type

            selected_category = self.request.GET.get("category", "all")
            if selected_category != "all":
                selected_category = normalize_effect_type(selected_category)
            shop_items = get_shop_items_for_display()
            sellable_items = list(get_sellable_inventory(manor))

            categories = {"all"}
            categories.update(normalize_effect_type(item.effect_type or "other") for item in shop_items)
            categories.update(
                normalize_effect_type(itm.inventory_item.template.effect_type or "other")
                for itm in sellable_items
            )
            category_options = [{"key": "all", "label": "全部"}] + [
                {"key": c, "label": EFFECT_TYPE_CATEGORY.get(c, c)}
                for c in sorted(c for c in categories if c and c != "all")
            ]

            if selected_category != "all":
                shop_items = [
                    item
                    for item in shop_items
                    if normalize_effect_type(item.effect_type or "other") == selected_category
                ]
                sellable_items = [
                    item
                    for item in sellable_items
                    if normalize_effect_type(item.inventory_item.template.effect_type or "other") == selected_category
                ]

            context["shop_items"] = shop_items
            context["inventory"] = sellable_items
            context["categories"] = category_options
            context["selected_category"] = selected_category
        elif tab == "bank":
            context["bank_info"] = get_bank_info(manor)
        elif tab == "market":
            # 交易行逻辑
            # 主动检查当前用户的过期挂单
            expire_user_listings(manor)

            market_view = self.request.GET.get("view", "buy")
            context["market_view"] = market_view

            if market_view == "buy":
                # 购买区
                category = self.request.GET.get("category", "all")
                rarity = self.request.GET.get("rarity", "all")
                order_by = safe_ordering(
                    self.request.GET.get("order_by", "-listed_at"),
                    "-listed_at",
                    {"-listed_at", "listed_at", "-price", "price", "-expires_at", "expires_at"}
                )

                listings = get_active_listings(
                    order_by=order_by,
                    category=category,
                    rarity=rarity,
                )

                # 分页，每页5个
                paginator = Paginator(listings, 5)
                page_number = self.request.GET.get("page", 1)
                page_obj = paginator.get_page(page_number)

                context["listings"] = page_obj
                context["page_obj"] = page_obj

                # 筛选选项
                context["selected_category"] = category
                context["selected_rarity"] = rarity
                context["selected_order"] = order_by

                # 类别选项
                categories = [{"key": "all", "label": "全部"}] + [
                    {"key": c, "label": EFFECT_TYPE_CATEGORY.get(c, c)}
                    for c in sorted(EFFECT_TYPE_CATEGORY.keys())
                ]
                context["categories"] = categories

            elif market_view == "sell":
                # 出售区
                category = self.request.GET.get("category", "all")
                page = safe_int(self.request.GET.get("page", 1), 1)

                tradeable_items = get_tradeable_inventory(manor)

                # 分类筛选
                if category != "all":
                    tradeable_items = [
                        item for item in tradeable_items
                        if (item.template.effect_type or "other") == category
                    ]

                # 分页，每页5个
                paginator = Paginator(tradeable_items, 5)
                page_obj = paginator.get_page(page)

                context["tradeable_items"] = page_obj
                context["page_obj"] = page_obj
                context["selected_category"] = category

                # 类别选项
                categories = [{"key": "all", "label": "全部"}] + [
                    {"key": c, "label": EFFECT_TYPE_CATEGORY.get(c, c)}
                    for c in sorted(EFFECT_TYPE_CATEGORY.keys())
                ]
                context["categories"] = categories

            elif market_view == "my_listings":
                # 我的挂单
                status = self.request.GET.get("status", "all")
                my_listings = get_my_listings(manor, status)

                # 分页，每页5个
                paginator = Paginator(my_listings, 5)
                page_number = self.request.GET.get("page", 1)
                page_obj = paginator.get_page(page_number)

                context["my_listings"] = page_obj
                context["page_obj"] = page_obj
                context["selected_status"] = status

        return context


@login_required
@require_POST
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
    except ValueError as e:
        messages.error(request, sanitize_error_message(e))

    return redirect("trade:trade")


@login_required
@require_POST
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
    except ValueError as e:
        messages.error(request, sanitize_error_message(e))

    return redirect("trade:trade")


@login_required
@require_POST
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
    except ValueError as e:
        messages.error(request, sanitize_error_message(e))

    return redirect(reverse("trade:trade") + "?tab=bank")


@login_required
@require_POST
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
    except ValueError as e:
        messages.error(request, sanitize_error_message(e))

    return redirect(reverse("trade:trade") + "?tab=market&view=sell")


@login_required
@require_POST
def market_purchase_view(request, listing_id: int):
    """购买交易行物品"""
    manor = request.user.manor

    try:
        transaction = purchase_listing(manor, listing_id)
        messages.success(
            request,
            f"成功购买 {transaction.listing.item_template.name} x{transaction.listing.quantity}，"
            f"花费 {transaction.total_price:,} 银两。物品已通过邮件发送，请查收！",
        )
    except ValueError as e:
        messages.error(request, sanitize_error_message(e))

    return redirect(reverse("trade:trade") + "?tab=market&view=buy")


@login_required
@require_POST
def market_cancel_view(request, listing_id: int):
    """取消交易行挂单"""
    manor = request.user.manor

    try:
        result = cancel_listing(manor, listing_id)
        messages.success(
            request,
            f"已取消挂单，{result['item_name']} x{result['quantity']} 已退回仓库。",
        )
    except ValueError as e:
        messages.error(request, str(e))

    return redirect(reverse("trade:trade") + "?tab=market&view=my_listings")


@login_required
@require_POST
def auction_bid_view(request, slot_id: int):
    """拍卖行出价"""
    manor = request.user.manor
    amount = safe_int(request.POST.get("amount", 0), default=0, min_val=1)

    try:
        bid, is_first_bid = place_bid(manor, slot_id, amount)
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
    except ValueError as e:
        messages.error(request, sanitize_error_message(e))

    return redirect(reverse("trade:trade") + "?tab=auction")
