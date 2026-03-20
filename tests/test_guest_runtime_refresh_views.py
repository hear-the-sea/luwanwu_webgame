from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestTemplate


def _create_guest(manor, *, prefix: str) -> Guest:
    template = GuestTemplate.objects.create(
        key=f"{prefix}_tpl",
        name=f"{prefix}模板",
        archetype="military",
        rarity="green",
    )
    return Guest.objects.create(
        manor=manor,
        template=template,
        custom_name=f"{prefix}门客",
        level=1,
        force=100,
        intellect=80,
        defense_stat=90,
        agility=85,
        current_hp=1,
    )


@pytest.mark.django_db
def test_roster_view_does_not_start_training_from_get(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="roster_auto_train", password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor, prefix="roster_auto_train")
    assert guest.training_complete_at is None

    client = Client()
    client.force_login(user)

    response = client.get(reverse("guests:roster"))

    assert response.status_code == 200
    guest.refresh_from_db()
    assert guest.training_complete_at is None
    assert guest.training_target_level == 0


@pytest.mark.django_db
def test_guest_detail_view_does_not_finalize_overdue_training_on_get(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="detail_auto_train", password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor, prefix="detail_auto_train")
    guest.training_target_level = 2
    overdue_at = timezone.now() - timedelta(seconds=1)
    guest.training_complete_at = overdue_at
    guest.save(update_fields=["training_target_level", "training_complete_at"])

    client = Client()
    client.force_login(user)

    response = client.get(reverse("guests:detail", args=[guest.pk]))

    assert response.status_code == 200
    guest.refresh_from_db()
    assert guest.level == 1
    assert guest.training_target_level == 2
    assert guest.training_complete_at == overdue_at


@pytest.mark.django_db
def test_roster_view_uses_explicit_read_helper(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="roster_read_helper", password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor, prefix="roster_read_helper")

    calls = {"helper": 0}

    def _fake_helper(request, *, logger, source, available_guests_fn):
        calls["helper"] += 1
        assert source == "guest_roster_view"
        return manor, [guest]

    monkeypatch.setattr("guests.views.roster.get_prepared_guest_roster_for_read", _fake_helper)

    client = Client()
    client.force_login(user)
    response = client.get(reverse("guests:roster"))

    assert response.status_code == 200
    assert calls["helper"] == 1


@pytest.mark.django_db
def test_guest_detail_view_uses_explicit_read_helper(game_data, django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="detail_read_helper", password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor, prefix="detail_read_helper")

    calls = {"helper": 0}

    def _fake_helper(request, guest_pk, *, logger, source, load_guest_detail_fn):
        calls["helper"] += 1
        assert guest_pk == guest.pk
        assert source == "guest_detail_view"
        return manor, guest

    monkeypatch.setattr("guests.views.roster.get_prepared_guest_detail_for_read", _fake_helper)

    client = Client()
    client.force_login(user)
    response = client.get(reverse("guests:detail", args=[guest.pk]))

    assert response.status_code == 200
    assert calls["helper"] == 1
