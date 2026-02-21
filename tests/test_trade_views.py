from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from gameplay.services.manor.core import ensure_manor


@pytest.mark.django_db
def test_trade_view_renders(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.views.get_trade_context", lambda *_args, **_kwargs: {"current_tab": "shop"})

    user = django_user_model.objects.create_user(username="trade_view", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.get(reverse("trade:trade"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_shop_buy_view_success(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.buy_item",
        lambda *_args, **_kwargs: {"item_name": "测试物品", "quantity": 2, "total_cost": 10},
    )

    user = django_user_model.objects.create_user(username="shop_buy_view", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:shop_buy"), {"item_key": "k", "quantity": "2"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("成功购买" in m for m in msgs)


@pytest.mark.django_db
def test_shop_buy_view_error(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.views.buy_item", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad")))

    user = django_user_model.objects.create_user(username="shop_buy_err", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:shop_buy"), {"item_key": "k", "quantity": "1"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("bad" in m for m in msgs)


@pytest.mark.django_db
def test_shop_sell_view_success(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.sell_item",
        lambda *_args, **_kwargs: {"item_name": "测试物品", "quantity": 1, "total_income": 7},
    )

    user = django_user_model.objects.create_user(username="shop_sell_view", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:shop_sell"), {"item_key": "k", "quantity": "1"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("成功出售" in m for m in msgs)


@pytest.mark.django_db
def test_exchange_gold_bar_view_redirects_to_bank_tab(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.exchange_gold_bar",
        lambda *_args, **_kwargs: {"quantity": 1, "total_cost": 100, "fee": 10, "next_rate": 123},
    )

    user = django_user_model.objects.create_user(username="bank_view", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:exchange_gold_bar"), {"quantity": "1"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=bank")


@pytest.mark.django_db
def test_market_create_listing_view_success(monkeypatch, client, django_user_model):
    class _DummyListing:
        total_price = 100

        class _Template:
            name = "物品"

        item_template = _Template()

        def get_duration_display(self):
            return "2小时"

    monkeypatch.setattr("trade.views.create_listing", lambda *_args, **_kwargs: _DummyListing())

    user = django_user_model.objects.create_user(username="market_create", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(
        reverse("trade:market_create_listing"),
        {"item_key": "k", "quantity": "1", "unit_price": "10", "duration": "7200"},
    )
    assert resp.status_code == 302
    assert "tab=market" in resp["Location"]
    assert "view=sell" in resp["Location"]


@pytest.mark.django_db
def test_market_purchase_view_success(monkeypatch, client, django_user_model):
    class _DummyListing:
        quantity = 2

        class _Template:
            name = "物品"

        item_template = _Template()

    class _DummyTransaction:
        total_price = 100
        listing = _DummyListing()

    monkeypatch.setattr("trade.views.purchase_listing", lambda *_args, **_kwargs: _DummyTransaction())

    user = django_user_model.objects.create_user(username="market_buy", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:market_purchase", args=[1]))
    assert resp.status_code == 302
    assert "tab=market" in resp["Location"]
    assert "view=buy" in resp["Location"]


@pytest.mark.django_db
def test_market_purchase_view_unexpected_error_uses_generic_message(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.purchase_listing", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    user = django_user_model.objects.create_user(username="market_buy_unexpected", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:market_purchase", args=[1]))
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in msgs)


@pytest.mark.django_db
def test_market_purchase_view_tolerates_missing_threshold_setting(monkeypatch, client, django_user_model):
    class _DummyListing:
        quantity = 2

        class _Template:
            name = "物品"

        item_template = _Template()

    class _DummyTransaction:
        total_price = 100
        listing = _DummyListing()

    monkeypatch.setattr("trade.views.purchase_listing", lambda *_args, **_kwargs: _DummyTransaction())
    monkeypatch.setattr("trade.views.settings.TRADE_HIGH_VALUE_SILVER_THRESHOLD", None, raising=False)

    user = django_user_model.objects.create_user(username="market_buy_missing_threshold", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:market_purchase", args=[1]))
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("成功购买" in m for m in msgs)


@pytest.mark.django_db
def test_market_purchase_view_tolerates_invalid_threshold_setting(monkeypatch, client, django_user_model):
    class _DummyListing:
        quantity = 2

        class _Template:
            name = "物品"

        item_template = _Template()

    class _DummyTransaction:
        total_price = 100
        listing = _DummyListing()

    monkeypatch.setattr("trade.views.purchase_listing", lambda *_args, **_kwargs: _DummyTransaction())
    monkeypatch.setattr("trade.views.settings.TRADE_HIGH_VALUE_SILVER_THRESHOLD", "invalid", raising=False)

    user = django_user_model.objects.create_user(username="market_buy_invalid_threshold", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:market_purchase", args=[1]))
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("成功购买" in m for m in msgs)


@pytest.mark.django_db
def test_market_cancel_view_success(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.cancel_listing",
        lambda *_args, **_kwargs: {"item_name": "物品", "quantity": 1},
    )

    user = django_user_model.objects.create_user(username="market_cancel", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:market_cancel", args=[1]))
    assert resp.status_code == 302
    assert "view=my_listings" in resp["Location"]


@pytest.mark.django_db
def test_auction_bid_view_messages_first_and_raise(monkeypatch, client, django_user_model):
    user = django_user_model.objects.create_user(username="auction_bid", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    monkeypatch.setattr("trade.views.place_bid", lambda *_args, **_kwargs: (object(), True))
    resp = client.post(reverse("trade:auction_bid", args=[1]), {"amount": "5"})
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("成功出价" in m for m in msgs)

    monkeypatch.setattr("trade.views.place_bid", lambda *_args, **_kwargs: (object(), False))
    resp = client.post(reverse("trade:auction_bid", args=[1]), {"amount": "6"})
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("成功加价" in m for m in msgs)


@pytest.mark.django_db
def test_auction_bid_view_tolerates_missing_threshold_setting(monkeypatch, client, django_user_model):
    user = django_user_model.objects.create_user(username="auction_bid_missing_threshold", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    monkeypatch.setattr("trade.views.place_bid", lambda *_args, **_kwargs: (object(), True))
    monkeypatch.setattr("trade.views.settings.AUCTION_HIGH_BID_THRESHOLD", None, raising=False)

    resp = client.post(reverse("trade:auction_bid", args=[1]), {"amount": "5"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("成功出价" in m for m in msgs)


@pytest.mark.django_db
def test_auction_bid_view_tolerates_invalid_threshold_setting(monkeypatch, client, django_user_model):
    user = django_user_model.objects.create_user(username="auction_bid_invalid_threshold", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    monkeypatch.setattr("trade.views.place_bid", lambda *_args, **_kwargs: (object(), True))
    monkeypatch.setattr("trade.views.settings.AUCTION_HIGH_BID_THRESHOLD", "invalid", raising=False)

    resp = client.post(reverse("trade:auction_bid", args=[1]), {"amount": "5"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("成功出价" in m for m in msgs)
