from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from core.exceptions import TradeValidationError
from gameplay.services.manor.core import ensure_manor


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
