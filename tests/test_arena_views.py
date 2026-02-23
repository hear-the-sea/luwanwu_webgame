from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from gameplay.models import ArenaEntry, ArenaEntryGuest
from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestTemplate


def _build_guest_template(key: str) -> GuestTemplate:
    return GuestTemplate.objects.create(
        key=key,
        name=f"竞技场模板-{key}",
        archetype="military",
        rarity="green",
    )


def _build_guest(manor, template, suffix: str) -> Guest:
    guest = Guest.objects.create(
        manor=manor,
        template=template,
        custom_name=f"竞技{suffix}",
        level=20,
        force=160,
        intellect=110,
        defense_stat=120,
        agility=120,
        current_hp=1,
    )
    guest.current_hp = guest.max_hp
    guest.save(update_fields=["current_hp"])
    return guest


@pytest.fixture
def arena_client(django_user_model):
    user = django_user_model.objects.create_user(
        username="arena_view_user",
        password="testpass123",
        email="arena_view_user@test.local",
    )
    client = Client()
    client.login(username="arena_view_user", password="testpass123")
    manor = ensure_manor(user)
    return client, manor


@pytest.mark.django_db
def test_arena_view_renders(arena_client):
    client, _manor = arena_client
    response = client.get(reverse("gameplay:arena"))

    assert response.status_code == 200
    assert "竞技场" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_arena_register_view_creates_entry(arena_client):
    client, manor = arena_client
    template = _build_guest_template("arena_view_register_tpl")
    guest1 = _build_guest(manor, template, "A")
    guest2 = _build_guest(manor, template, "B")

    response = client.post(
        reverse("gameplay:arena_register"),
        {"guest_ids": [str(guest1.id), str(guest2.id)]},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:arena")

    entry = ArenaEntry.objects.filter(manor=manor).first()
    assert entry is not None
    assert ArenaEntryGuest.objects.filter(entry=entry).count() == 2


@pytest.mark.django_db
def test_arena_exchange_view_deducts_coins(arena_client):
    client, manor = arena_client
    manor.arena_coins = 300
    manor.save(update_fields=["arena_coins"])

    response = client.post(
        reverse("gameplay:arena_exchange"),
        {"reward_key": "grain_pack_small", "quantity": "1"},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:arena")
    manor.refresh_from_db(fields=["arena_coins"])
    assert manor.arena_coins == 220
