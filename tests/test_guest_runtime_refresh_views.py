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
def test_roster_view_refreshes_guest_training_state(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="roster_auto_train", password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor, prefix="roster_auto_train")

    client = Client()
    client.force_login(user)

    response = client.get(reverse("guests:roster"))

    assert response.status_code == 200
    guest.refresh_from_db()
    assert guest.training_complete_at is not None
    assert guest.training_target_level == 2


@pytest.mark.django_db
def test_guest_detail_view_finalizes_overdue_training(game_data, django_user_model):
    user = django_user_model.objects.create_user(username="detail_auto_train", password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor, prefix="detail_auto_train")
    guest.training_target_level = 2
    guest.training_complete_at = timezone.now() - timedelta(seconds=1)
    guest.save(update_fields=["training_target_level", "training_complete_at"])

    client = Client()
    client.force_login(user)

    response = client.get(reverse("guests:detail", args=[guest.pk]))

    assert response.status_code == 200
    guest.refresh_from_db()
    assert guest.level == 2
    assert guest.training_target_level >= 2
    assert guest.training_complete_at is not None
