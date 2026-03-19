from __future__ import annotations

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.test import Client
from django.urls import reverse

from battle.models import TroopTemplate
from gameplay.models import PlayerTroop, TroopBankStorage
from gameplay.services.manor.core import ensure_manor


@pytest.fixture
def troop_bank_client(django_user_model):
    user = django_user_model.objects.create_user(username="troop_bank_view", password="pass12345")
    manor = ensure_manor(user)
    client = Client()
    client.login(username="troop_bank_view", password="pass12345")
    return manor, client


def _create_troop_template(key: str, name: str) -> TroopTemplate:
    template, _ = TroopTemplate.objects.get_or_create(
        key=key,
        defaults={
            "name": name,
            "description": "",
            "base_attack": 10,
            "base_defense": 10,
            "base_hp": 10,
            "speed_bonus": 0,
            "priority": 0,
            "default_count": 0,
        },
    )
    return template


@pytest.mark.django_db
def test_deposit_troop_to_bank_view_success(troop_bank_client):
    manor, client = troop_bank_client
    template = _create_troop_template("view_bank_spear", "视图枪兵")
    PlayerTroop.objects.create(manor=manor, troop_template=template, count=80)

    response = client.post(
        reverse("gameplay:deposit_troop_to_bank"),
        {"troop_key": template.key, "quantity": "30"},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:troop_recruitment")

    troop = PlayerTroop.objects.get(manor=manor, troop_template=template)
    bank = TroopBankStorage.objects.get(manor=manor, troop_template=template)
    assert troop.count == 50
    assert bank.count == 30


@pytest.mark.django_db
def test_withdraw_troop_from_bank_view_database_error_does_not_500(troop_bank_client, monkeypatch):
    manor, client = troop_bank_client
    template = _create_troop_template("view_bank_blade_db", "视图刀手数据库异常")
    TroopBankStorage.objects.create(manor=manor, troop_template=template, count=30)

    monkeypatch.setattr(
        "gameplay.services.manor.troop_bank.withdraw_troops_from_bank",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("gameplay:withdraw_troop_from_bank"),
        {"troop_key": template.key, "quantity": "10"},
    )
    assert response.status_code == 302
    assert response.url == reverse("gameplay:troop_recruitment")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in messages)


@pytest.mark.django_db
def test_withdraw_troop_from_bank_view_programming_error_bubbles_up(troop_bank_client, monkeypatch):
    manor, client = troop_bank_client
    template = _create_troop_template("view_bank_blade", "视图刀手")
    TroopBankStorage.objects.create(manor=manor, troop_template=template, count=30)

    monkeypatch.setattr(
        "gameplay.services.manor.troop_bank.withdraw_troops_from_bank",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(
            reverse("gameplay:withdraw_troop_from_bank"),
            {"troop_key": template.key, "quantity": "10"},
        )


@pytest.mark.django_db
def test_deposit_troop_to_bank_view_database_error_does_not_500(troop_bank_client, monkeypatch):
    manor, client = troop_bank_client
    template = _create_troop_template("view_bank_archer_db", "视图弓手数据库异常")
    PlayerTroop.objects.create(manor=manor, troop_template=template, count=30)

    monkeypatch.setattr(
        "gameplay.services.manor.troop_bank.deposit_troops_to_bank",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("gameplay:deposit_troop_to_bank"),
        {"troop_key": template.key, "quantity": "10"},
    )
    assert response.status_code == 302
    assert response.url == reverse("gameplay:troop_recruitment")
    messages = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("操作失败，请稍后重试" in m for m in messages)


@pytest.mark.django_db
def test_deposit_troop_to_bank_view_programming_error_bubbles_up(troop_bank_client, monkeypatch):
    manor, client = troop_bank_client
    template = _create_troop_template("view_bank_archer", "视图弓手")
    PlayerTroop.objects.create(manor=manor, troop_template=template, count=30)

    monkeypatch.setattr(
        "gameplay.services.manor.troop_bank.deposit_troops_to_bank",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        client.post(
            reverse("gameplay:deposit_troop_to_bank"),
            {"troop_key": template.key, "quantity": "10"},
        )
