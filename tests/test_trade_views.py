from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import ShopValidationError, TradeValidationError
from gameplay.models import Manor
from gameplay.services.manor.core import ensure_manor


@pytest.mark.django_db
def test_trade_view_renders(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.views.build_trade_page_context", lambda *_args, **_kwargs: {"current_tab": "shop"})

    user = django_user_model.objects.create_user(username="trade_view", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.get(reverse("trade:trade"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_trade_view_creates_manor_when_missing(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.views.build_trade_page_context", lambda *_args, **_kwargs: {"current_tab": "shop"})

    user = django_user_model.objects.create_user(username="trade_view_create_manor", password="pass12345")
    client.force_login(user)

    resp = client.get(reverse("trade:trade"))
    assert resp.status_code == 200
    assert Manor.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_trade_view_tolerates_resource_sync_error(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.page_context.get_trade_context", lambda *_args, **_kwargs: {"current_tab": "shop"})
    monkeypatch.setattr(
        "trade.page_context.project_resource_production_for_read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("sync failed")),
    )

    user = django_user_model.objects.create_user(username="trade_view_sync_err", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.get(reverse("trade:trade"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_trade_view_renders_bank_degraded_banner_and_disables_exchange(monkeypatch, client, django_user_model):
    user = django_user_model.objects.create_user(username="trade_view_bank_degraded", password="pass12345")
    manor = ensure_manor(user)
    monkeypatch.setattr(
        "trade.views.build_trade_page_context",
        lambda *_args, **_kwargs: {
            "current_tab": "bank",
            "tabs": [{"key": "bank", "name": "钱庄"}],
            "manor": manor,
            "trade_alerts": [{"section": "bank", "message": "钱庄汇率数据暂时不可用，已暂时关闭兑换。"}],
            "bank_info": {
                "current_rate": 0,
                "next_rate": 0,
                "total_cost_per_bar": 0,
                "gold_bar_fee_rate": 0,
                "today_count": 0,
                "manor_silver": manor.silver,
                "effective_supply": 0,
                "supply_factor": 0,
                "progressive_factor": 0,
                "gold_bar_base_price": 0,
                "gold_bar_min_price": 0,
                "gold_bar_max_price": 0,
                "exchange_available": False,
            },
            "troop_bank_capacity": 5000,
            "troop_bank_used": 0,
            "troop_bank_remaining": 5000,
            "troop_bank_rows": [],
            "troop_bank_categories": [{"key": "all", "name": "全部"}],
            "troop_bank_current_category": "all",
        },
    )
    client.force_login(user)

    resp = client.get(reverse("trade:trade"))
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "钱庄汇率数据暂时不可用，已暂时关闭兑换。" in content
    assert "兑换暂不可用" in content


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
    monkeypatch.setattr(
        "trade.views.buy_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ShopValidationError(action="buy", message="bad")),
    )

    user = django_user_model.objects.create_user(username="shop_buy_err", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:shop_buy"), {"item_key": "k", "quantity": "1"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("bad" in m for m in msgs)


@pytest.mark.django_db
def test_shop_buy_view_raw_value_error_bubbles_up(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.views.buy_item", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy")))

    user = django_user_model.objects.create_user(username="shop_buy_legacy_value_error", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    with pytest.raises(ValueError, match="legacy"):
        client.post(reverse("trade:shop_buy"), {"item_key": "k", "quantity": "1"})


@pytest.mark.django_db
def test_shop_sell_view_known_error(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.sell_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ShopValidationError(action="sell", message="sell blocked")),
    )

    user = django_user_model.objects.create_user(username="shop_sell_err", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:shop_sell"), {"item_key": "k", "quantity": "1"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("sell blocked" in m for m in msgs)


@pytest.mark.django_db
def test_exchange_gold_bar_view_handles_trade_validation_error(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.exchange_gold_bar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TradeValidationError("兑换失败")),
    )

    user = django_user_model.objects.create_user(username="bank_trade_validation_error", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:exchange_gold_bar"), {"quantity": "1"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("兑换失败" in m for m in msgs)


@pytest.mark.django_db
def test_shop_buy_view_database_error_degrades_with_flash_message(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.buy_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    user = django_user_model.objects.create_user(username="shop_buy_db_err", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:shop_buy"), {"item_key": "k", "quantity": "1"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in msgs)


@pytest.mark.django_db
def test_shop_buy_view_programming_error_bubbles_up(monkeypatch, client, django_user_model):
    monkeypatch.setattr("trade.views.buy_item", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    user = django_user_model.objects.create_user(username="shop_buy_runtime_err", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    with pytest.raises(RuntimeError, match="boom"):
        client.post(reverse("trade:shop_buy"), {"item_key": "k", "quantity": "1"})


@pytest.mark.django_db
def test_shop_buy_view_rejects_invalid_quantity_without_service_call(monkeypatch, client, django_user_model):
    called = {"count": 0}

    def _unexpected_buy(*_args, **_kwargs):
        called["count"] += 1
        return {"item_name": "测试物品", "quantity": 1, "total_cost": 1}

    monkeypatch.setattr("trade.views.buy_item", _unexpected_buy)

    user = django_user_model.objects.create_user(username="shop_buy_invalid_qty", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:shop_buy"), {"item_key": "k", "quantity": "bad"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("数量参数无效" in m for m in msgs)
    assert called["count"] == 0


@pytest.mark.django_db
def test_shop_buy_view_rejects_missing_item_key_without_service_call(monkeypatch, client, django_user_model):
    called = {"count": 0}

    def _unexpected_buy(*_args, **_kwargs):
        called["count"] += 1
        return {"item_name": "测试物品", "quantity": 1, "total_cost": 1}

    monkeypatch.setattr("trade.views.buy_item", _unexpected_buy)

    user = django_user_model.objects.create_user(username="shop_buy_missing_item_key", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:shop_buy"), {"item_key": "   ", "quantity": "1"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("请选择商品" in m for m in msgs)
    assert called["count"] == 0


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
def test_shop_sell_view_rejects_missing_item_key_without_service_call(monkeypatch, client, django_user_model):
    called = {"count": 0}

    def _unexpected_sell(*_args, **_kwargs):
        called["count"] += 1
        return {"item_name": "测试物品", "quantity": 1, "total_income": 1}

    monkeypatch.setattr("trade.views.sell_item", _unexpected_sell)

    user = django_user_model.objects.create_user(username="shop_sell_missing_item_key", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:shop_sell"), {"item_key": " ", "quantity": "1"})
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("请选择商品" in m for m in msgs)
    assert called["count"] == 0


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
def test_exchange_gold_bar_view_rejects_invalid_quantity_without_service_call(monkeypatch, client, django_user_model):
    called = {"count": 0}

    def _unexpected_exchange(*_args, **_kwargs):
        called["count"] += 1
        return {"quantity": 1, "total_cost": 100, "fee": 10, "next_rate": 123}

    monkeypatch.setattr("trade.views.exchange_gold_bar", _unexpected_exchange)

    user = django_user_model.objects.create_user(username="bank_exchange_invalid_qty", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:exchange_gold_bar"), {"quantity": "bad"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=bank")
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("数量参数无效" in m for m in msgs)
    assert called["count"] == 0


@pytest.mark.django_db
def test_deposit_troop_to_bank_view_redirects_to_bank_tab(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "gameplay.services.manor.troop_bank.deposit_troops_to_bank",
        lambda *_args, **_kwargs: {"quantity": 5, "troop_name": "刀手"},
    )

    user = django_user_model.objects.create_user(username="bank_troop_deposit_view", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:deposit_troop_to_bank"), {"troop_key": "dao_jie", "quantity": "5"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=bank")
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("已存入" in m for m in msgs)


@pytest.mark.django_db
def test_deposit_troop_to_bank_view_rejects_missing_troop_key_without_service_call(
    monkeypatch, client, django_user_model
):
    called = {"count": 0}

    def _unexpected_deposit(*_args, **_kwargs):
        called["count"] += 1
        return {"quantity": 5, "troop_name": "刀手"}

    monkeypatch.setattr("gameplay.services.manor.troop_bank.deposit_troops_to_bank", _unexpected_deposit)

    user = django_user_model.objects.create_user(username="bank_troop_deposit_missing_key", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:deposit_troop_to_bank"), {"troop_key": " ", "quantity": "5"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=bank")
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("请选择护院类型" in m for m in msgs)
    assert called["count"] == 0


@pytest.mark.django_db
def test_deposit_troop_to_bank_view_rejects_invalid_quantity_without_service_call(
    monkeypatch, client, django_user_model
):
    called = {"count": 0}

    def _unexpected_deposit(*_args, **_kwargs):
        called["count"] += 1
        return {"quantity": 5, "troop_name": "刀手"}

    monkeypatch.setattr("gameplay.services.manor.troop_bank.deposit_troops_to_bank", _unexpected_deposit)

    user = django_user_model.objects.create_user(username="bank_troop_deposit_invalid_qty", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:deposit_troop_to_bank"), {"troop_key": "dao_jie", "quantity": "bad"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=bank")
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("数量参数无效" in m for m in msgs)
    assert called["count"] == 0


@pytest.mark.django_db
def test_withdraw_troop_from_bank_view_redirects_to_bank_tab(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "gameplay.services.manor.troop_bank.withdraw_troops_from_bank",
        lambda *_args, **_kwargs: {"quantity": 3, "troop_name": "刀手"},
    )

    user = django_user_model.objects.create_user(username="bank_troop_withdraw_view", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:withdraw_troop_from_bank"), {"troop_key": "dao_jie", "quantity": "3"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=bank")
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("已从钱庄取出" in m for m in msgs)


@pytest.mark.django_db
def test_withdraw_troop_from_bank_view_rejects_missing_troop_key_without_service_call(
    monkeypatch, client, django_user_model
):
    called = {"count": 0}

    def _unexpected_withdraw(*_args, **_kwargs):
        called["count"] += 1
        return {"quantity": 3, "troop_name": "刀手"}

    monkeypatch.setattr("gameplay.services.manor.troop_bank.withdraw_troops_from_bank", _unexpected_withdraw)

    user = django_user_model.objects.create_user(username="bank_troop_withdraw_missing_key", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:withdraw_troop_from_bank"), {"troop_key": " ", "quantity": "3"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=bank")
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("请选择护院类型" in m for m in msgs)
    assert called["count"] == 0


@pytest.mark.django_db
def test_withdraw_troop_from_bank_view_rejects_invalid_quantity_without_service_call(
    monkeypatch, client, django_user_model
):
    called = {"count": 0}

    def _unexpected_withdraw(*_args, **_kwargs):
        called["count"] += 1
        return {"quantity": 3, "troop_name": "刀手"}

    monkeypatch.setattr("gameplay.services.manor.troop_bank.withdraw_troops_from_bank", _unexpected_withdraw)

    user = django_user_model.objects.create_user(username="bank_troop_withdraw_invalid_qty", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:withdraw_troop_from_bank"), {"troop_key": "dao_jie", "quantity": "bad"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=bank")
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("数量参数无效" in m for m in msgs)
    assert called["count"] == 0


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
def test_market_create_listing_view_rejects_invalid_quantity_without_service_call(
    monkeypatch, client, django_user_model
):
    called = {"count": 0}

    class _DummyListing:
        total_price = 100

        class _Template:
            name = "物品"

        item_template = _Template()

        def get_duration_display(self):
            return "2小时"

    def _unexpected_create(*_args, **_kwargs):
        called["count"] += 1
        return _DummyListing()

    monkeypatch.setattr("trade.views.create_listing", _unexpected_create)

    user = django_user_model.objects.create_user(username="market_create_invalid_qty", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(
        reverse("trade:market_create_listing"),
        {"item_key": "k", "quantity": "bad", "unit_price": "10", "duration": "7200"},
    )
    assert resp.status_code == 302
    assert "tab=market" in resp["Location"]
    assert "view=sell" in resp["Location"]
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("数量参数无效" in m for m in msgs)
    assert called["count"] == 0


@pytest.mark.django_db
def test_market_create_listing_view_rejects_missing_item_key_without_service_call(
    monkeypatch, client, django_user_model
):
    called = {"count": 0}

    class _DummyListing:
        total_price = 100

        class _Template:
            name = "物品"

        item_template = _Template()

        def get_duration_display(self):
            return "2小时"

    def _unexpected_create(*_args, **_kwargs):
        called["count"] += 1
        return _DummyListing()

    monkeypatch.setattr("trade.views.create_listing", _unexpected_create)

    user = django_user_model.objects.create_user(username="market_create_missing_item_key", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(
        reverse("trade:market_create_listing"),
        {"item_key": " ", "quantity": "1", "unit_price": "10", "duration": "7200"},
    )
    assert resp.status_code == 302
    assert "tab=market" in resp["Location"]
    assert "view=sell" in resp["Location"]
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("请选择商品" in m for m in msgs)
    assert called["count"] == 0


@pytest.mark.django_db
def test_market_create_listing_view_rejects_invalid_unit_price_without_service_call(
    monkeypatch, client, django_user_model
):
    called = {"count": 0}

    class _DummyListing:
        total_price = 100

        class _Template:
            name = "物品"

        item_template = _Template()

        def get_duration_display(self):
            return "2小时"

    def _unexpected_create(*_args, **_kwargs):
        called["count"] += 1
        return _DummyListing()

    monkeypatch.setattr("trade.views.create_listing", _unexpected_create)

    user = django_user_model.objects.create_user(username="market_create_invalid_price", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(
        reverse("trade:market_create_listing"),
        {"item_key": "k", "quantity": "1", "unit_price": "bad", "duration": "7200"},
    )
    assert resp.status_code == 302
    assert "tab=market" in resp["Location"]
    assert "view=sell" in resp["Location"]
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("单价参数无效" in m for m in msgs)
    assert called["count"] == 0


@pytest.mark.django_db
def test_market_create_listing_view_rejects_invalid_duration_without_service_call(
    monkeypatch, client, django_user_model
):
    called = {"count": 0}

    class _DummyListing:
        total_price = 100

        class _Template:
            name = "物品"

        item_template = _Template()

        def get_duration_display(self):
            return "2小时"

    def _unexpected_create(*_args, **_kwargs):
        called["count"] += 1
        return _DummyListing()

    monkeypatch.setattr("trade.views.create_listing", _unexpected_create)

    user = django_user_model.objects.create_user(username="market_create_invalid_duration", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(
        reverse("trade:market_create_listing"),
        {"item_key": "k", "quantity": "1", "unit_price": "10", "duration": "bad"},
    )
    assert resp.status_code == 302
    assert "tab=market" in resp["Location"]
    assert "view=sell" in resp["Location"]
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("时长参数无效" in m for m in msgs)
    assert called["count"] == 0


@pytest.mark.django_db
def test_market_create_listing_view_rejects_out_of_range_duration_without_service_call(
    monkeypatch, client, django_user_model
):
    called = {"count": 0}

    class _DummyListing:
        total_price = 100

        class _Template:
            name = "物品"

        item_template = _Template()

        def get_duration_display(self):
            return "2小时"

    def _unexpected_create(*_args, **_kwargs):
        called["count"] += 1
        return _DummyListing()

    monkeypatch.setattr("trade.views.create_listing", _unexpected_create)

    user = django_user_model.objects.create_user(username="market_create_out_of_range_duration", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(
        reverse("trade:market_create_listing"),
        {"item_key": "k", "quantity": "1", "unit_price": "10", "duration": "1"},
    )
    assert resp.status_code == 302
    assert "tab=market" in resp["Location"]
    assert "view=sell" in resp["Location"]
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("时长参数无效" in m for m in msgs)
    assert called["count"] == 0


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
def test_market_purchase_view_database_error_uses_generic_message(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.purchase_listing", lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down"))
    )

    user = django_user_model.objects.create_user(username="market_buy_unexpected", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:market_purchase", args=[1]))
    assert resp.status_code == 302
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in msgs)


@pytest.mark.django_db
def test_market_purchase_view_programming_error_bubbles_up(monkeypatch, client, django_user_model):
    monkeypatch.setattr(
        "trade.views.purchase_listing", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    user = django_user_model.objects.create_user(username="market_buy_runtime", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    with pytest.raises(RuntimeError, match="boom"):
        client.post(reverse("trade:market_purchase", args=[1]))


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
def test_auction_bid_view_rejects_invalid_amount_without_service_call(monkeypatch, client, django_user_model):
    called = {"count": 0}

    def _unexpected_bid(*_args, **_kwargs):
        called["count"] += 1
        return object(), True

    monkeypatch.setattr("trade.views.place_bid", _unexpected_bid)

    user = django_user_model.objects.create_user(username="auction_bid_invalid_amount", password="pass12345")
    _ = ensure_manor(user)
    client.force_login(user)

    resp = client.post(reverse("trade:auction_bid", args=[1]), {"amount": "bad"})
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=auction")
    msgs = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("出价参数无效" in m for m in msgs)
    assert called["count"] == 0


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
