from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.test import RequestFactory

from gameplay.services.manor import ensure_manor
from trade.selectors import get_trade_context
from trade.services.shop_service import ShopItemDisplay


@dataclass
class _DummySellable:
    inventory_item: object
    sell_price: int


@pytest.mark.django_db
def test_get_trade_context_shop_builds_categories_and_filters(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)

    user = django_user_model.objects.create_user(username="trade_ctx_shop", password="pass12345")
    manor = ensure_manor(user)

    shop_items = [
        ShopItemDisplay(
            key="tool_item",
            name="工具",
            description="",
            price=1,
            stock=-1,
            stock_display="无限",
            available=True,
            icon="",
            image_url="",
            effect_type="tool",
            category="道具",
            rarity="black",
            effect_payload={},
        ),
        ShopItemDisplay(
            key="med_item",
            name="药品",
            description="",
            price=1,
            stock=-1,
            stock_display="无限",
            available=True,
            icon="",
            image_url="",
            effect_type="medicine",
            category="药品",
            rarity="black",
            effect_payload={},
        ),
    ]

    def _sellable_inventory(_manor, category=None):
        assert category == "tool"
        return [_DummySellable(inventory_item=object(), sell_price=1)]

    monkeypatch.setattr("trade.selectors.get_shop_items_for_display", lambda: list(shop_items))
    monkeypatch.setattr("trade.selectors.get_sellable_inventory", _sellable_inventory)
    monkeypatch.setattr("trade.selectors.get_sellable_effect_types", lambda *_args, **_kwargs: {"tool"})

    request = RequestFactory().get("/trade", {"tab": "shop", "category": "magnifying_glass"})
    context = get_trade_context(request, manor)

    assert context["current_tab"] == "shop"
    assert context["selected_category"] == "tool"
    assert [item.key for item in context["shop_items"]] == ["tool_item"]

    category_keys = [c["key"] for c in context["categories"]]
    assert "all" in category_keys
    assert "tool" in category_keys
    assert "medicine" in category_keys
    assert len(context["inventory"]) == 1


@pytest.mark.django_db
def test_get_trade_context_bank_includes_bank_info(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.get_bank_info", lambda *_args, **_kwargs: {"current_rate": 123})

    user = django_user_model.objects.create_user(username="trade_ctx_bank", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "bank"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "bank"
    assert context["bank_info"] == {"current_rate": 123}


@pytest.mark.django_db
def test_get_trade_context_auction_browse_sets_bid_info(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.get_auction_stats", lambda *_args, **_kwargs: {"round": 1})

    class Slot:
        def __init__(self, slot_id: int):
            self.id = slot_id

    slots = [Slot(1), Slot(2)]
    monkeypatch.setattr("trade.selectors.get_active_slots", lambda **_kwargs: list(slots))
    monkeypatch.setattr(
        "trade.services.auction_service.get_slots_bid_info_batch",
        lambda slots_list, _manor: {slot.id: {"bid": slot.id} for slot in slots_list},
    )

    user = django_user_model.objects.create_user(username="trade_ctx_auction", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "auction", "view": "browse"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "auction"
    assert context["auction_view"] == "browse"
    assert context["auction_stats"] == {"round": 1}
    assert [slot.bid_info for slot in context["auction_slots"]] == [{"bid": 1}, {"bid": 2}]


@pytest.mark.django_db
def test_get_trade_context_market_buy_lists_page(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.expire_user_listings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.get_active_listings", lambda **_kwargs: ["l1", "l2", "l3"])

    user = django_user_model.objects.create_user(username="trade_ctx_market", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "market", "view": "buy"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "market"
    assert context["market_view"] == "buy"
    assert list(context["listings"].object_list) == ["l1", "l2", "l3"]
