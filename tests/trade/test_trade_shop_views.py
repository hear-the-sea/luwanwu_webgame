from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.urls import reverse

from core.exceptions import ShopValidationError
from gameplay.services.manor.core import ensure_manor


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
