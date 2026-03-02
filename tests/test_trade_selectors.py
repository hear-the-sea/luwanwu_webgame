from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.test import RequestFactory

from gameplay.services.manor.core import ensure_manor
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

    captured = {"category": "unset"}

    def _sellable_inventory(_manor, category=None):
        captured["category"] = category
        return [_DummySellable(inventory_item=object(), sell_price=1)]

    monkeypatch.setattr("trade.selectors.get_shop_items_for_display", lambda: list(shop_items))
    monkeypatch.setattr("trade.selectors.get_sellable_inventory", _sellable_inventory)

    request = RequestFactory().get("/trade", {"tab": "shop", "category": "magnifying_glass"})
    context = get_trade_context(request, manor)

    assert context["current_tab"] == "shop"
    assert context["selected_category"] == "tool"
    assert [item.key for item in context["shop_items"]] == ["tool_item"]
    assert captured["category"] is None

    category_keys = [c["key"] for c in context["categories"]]
    assert "all" in category_keys
    assert "tool" in category_keys
    assert "medicine" in category_keys
    assert len(context["inventory"]) == 1


@pytest.mark.django_db
def test_get_trade_context_bank_includes_bank_info(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.get_bank_info", lambda *_args, **_kwargs: {"current_rate": 123})
    monkeypatch.setattr("trade.selectors.get_troop_bank_capacity", lambda *_args, **_kwargs: 5000)
    monkeypatch.setattr("trade.selectors.get_troop_bank_used_space", lambda *_args, **_kwargs: 100)
    monkeypatch.setattr("trade.selectors.get_troop_bank_remaining_space", lambda *_args, **_kwargs: 4900)
    monkeypatch.setattr(
        "trade.selectors.get_troop_bank_rows",
        lambda *_args, **_kwargs: [{"key": "dao_jie", "name": "刀手", "player_count": 10, "bank_count": 5}],
    )

    user = django_user_model.objects.create_user(username="trade_ctx_bank", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "bank"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "bank"
    assert context["bank_info"] == {"current_rate": 123}
    assert context["troop_bank_capacity"] == 5000
    assert context["troop_bank_used"] == 100
    assert context["troop_bank_remaining"] == 4900
    assert len(context["troop_bank_rows"]) == 1


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


@pytest.mark.django_db
def test_get_trade_context_market_buy_negative_page_clamped(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.expire_user_listings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.get_active_listings", lambda **_kwargs: list(range(1, 21)))

    user = django_user_model.objects.create_user(username="trade_ctx_market_page_clamp", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "market", "view": "buy", "page": "-9"})

    context = get_trade_context(request, manor)
    assert context["page_obj"].number == 1
    assert list(context["listings"].object_list) == [1, 2, 3, 4, 5]


@pytest.mark.django_db
def test_get_trade_context_market_buy_tolerates_expire_user_listings_error(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "trade.selectors.expire_user_listings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("expire failed")),
    )
    monkeypatch.setattr("trade.selectors.get_active_listings", lambda **_kwargs: ["l1"])

    user = django_user_model.objects.create_user(username="trade_ctx_market_expire_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "market", "view": "buy"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "market"
    assert context["market_view"] == "buy"
    assert list(context["listings"].object_list) == ["l1"]


@pytest.mark.django_db
def test_get_trade_context_bank_tolerates_sync_resource_error(monkeypatch, django_user_model):
    monkeypatch.setattr(
        "trade.selectors.sync_resource_production",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sync failed")),
    )
    monkeypatch.setattr("trade.selectors.get_bank_info", lambda *_args, **_kwargs: {"current_rate": 123})

    user = django_user_model.objects.create_user(username="trade_ctx_bank_sync_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "bank"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "bank"
    assert context["bank_info"] == {"current_rate": 123}


@pytest.mark.django_db
def test_get_trade_context_auction_browse_tolerates_bid_info_batch_error(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.get_auction_stats", lambda *_args, **_kwargs: {"round": 1})

    class Slot:
        def __init__(self, slot_id: int):
            self.id = slot_id

    slots = [Slot(1), Slot(2)]
    monkeypatch.setattr("trade.selectors.get_active_slots", lambda **_kwargs: list(slots))
    monkeypatch.setattr(
        "trade.services.auction_service.get_slots_bid_info_batch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("batch failed")),
    )

    user = django_user_model.objects.create_user(username="trade_ctx_auction_bidinfo_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "auction", "view": "browse"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "auction"
    assert context["auction_view"] == "browse"
    assert [slot.bid_info for slot in context["auction_slots"]] == [{}, {}]


@pytest.mark.django_db
def test_get_trade_context_market_my_listings_negative_page_clamped(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.expire_user_listings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.get_my_listings", lambda *_args, **_kwargs: list(range(1, 21)))

    user = django_user_model.objects.create_user(username="trade_ctx_market_my_page_clamp", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "market", "view": "my_listings", "page": "-3"})

    context = get_trade_context(request, manor)
    assert context["page_obj"].number == 1
    assert list(context["my_listings"].object_list) == [1, 2, 3, 4, 5]


@pytest.mark.django_db
def test_get_trade_context_bank_tolerates_bank_info_error(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "trade.selectors.get_bank_info",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bank failed")),
    )

    user = django_user_model.objects.create_user(username="trade_ctx_bank_info_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "bank"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "bank"
    assert context["bank_info"] == {}


@pytest.mark.django_db
def test_get_trade_context_shop_tolerates_data_loading_errors(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "trade.selectors.get_shop_items_for_display",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("shop items failed")),
    )
    monkeypatch.setattr(
        "trade.selectors.get_sellable_inventory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("sellable failed")),
    )

    user = django_user_model.objects.create_user(username="trade_ctx_shop_load_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "shop"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "shop"
    assert context["shop_items"] == []
    assert context["inventory"] == []
    assert context["categories"][0]["key"] == "all"


@pytest.mark.django_db
def test_get_trade_context_auction_browse_tolerates_stats_and_slot_errors(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "trade.selectors.get_auction_stats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("stats failed")),
    )
    monkeypatch.setattr(
        "trade.selectors.get_active_slots",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("slots failed")),
    )

    user = django_user_model.objects.create_user(username="trade_ctx_auction_load_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "auction", "view": "browse"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "auction"
    assert context["auction_view"] == "browse"
    assert context["auction_stats"] == {}
    assert context["auction_slots"] == []
    assert context["page_obj"].number == 1


@pytest.mark.django_db
def test_get_trade_context_auction_my_bids_tolerates_loading_errors(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.get_auction_stats", lambda *_args, **_kwargs: {"round": 1})
    monkeypatch.setattr(
        "trade.selectors.get_my_bids",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("my bids failed")),
    )
    monkeypatch.setattr(
        "trade.selectors.get_my_leading_bids",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("leading bids failed")),
    )

    user = django_user_model.objects.create_user(username="trade_ctx_auction_my_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "auction", "view": "my_bids"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "auction"
    assert context["auction_view"] == "my_bids"
    assert context["my_bids"] == []
    assert context["my_leading_slots"] == []


@pytest.mark.django_db
def test_get_trade_context_market_buy_tolerates_active_listings_error(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.expire_user_listings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "trade.selectors.get_active_listings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("listings failed")),
    )

    user = django_user_model.objects.create_user(username="trade_ctx_market_buy_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "market", "view": "buy"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "market"
    assert context["market_view"] == "buy"
    assert list(context["listings"].object_list) == []


@pytest.mark.django_db
def test_get_trade_context_market_sell_negative_page_clamped_and_tolerates_inventory_error(
    monkeypatch, django_user_model
):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.expire_user_listings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "trade.selectors.get_tradeable_inventory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("tradeable failed")),
    )

    user = django_user_model.objects.create_user(username="trade_ctx_market_sell_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "market", "view": "sell", "page": "-10"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "market"
    assert context["market_view"] == "sell"
    assert context["page_obj"].number == 1
    assert list(context["tradeable_items"].object_list) == []


@pytest.mark.django_db
def test_get_trade_context_market_my_listings_tolerates_loading_error(monkeypatch, django_user_model):
    monkeypatch.setattr("trade.selectors.sync_resource_production", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("trade.selectors.expire_user_listings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "trade.selectors.get_my_listings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("my listings failed")),
    )

    user = django_user_model.objects.create_user(username="trade_ctx_market_my_err", password="pass12345")
    manor = ensure_manor(user)
    request = RequestFactory().get("/trade", {"tab": "market", "view": "my_listings"})

    context = get_trade_context(request, manor)
    assert context["current_tab"] == "market"
    assert context["market_view"] == "my_listings"
    assert list(context["my_listings"].object_list) == []
