from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from gameplay.services.manor.core import ensure_manor
from guests import tasks as guest_tasks
from guests.models import Guest, GuestRarity, GuestTemplate, SalaryPayment
from guests.services.loyalty import extract_guest_ids, grant_battle_victory_loyalty


def test_extract_guest_ids_deduplicates_and_ignores_invalid_ids():
    guests = [
        SimpleNamespace(pk=1),
        SimpleNamespace(id=1),
        SimpleNamespace(id="2"),
        SimpleNamespace(pk=None, id=0),
        SimpleNamespace(pk="bad"),
    ]

    assert extract_guest_ids(guests) == [1, 2]


@pytest.mark.django_db
def test_grant_battle_victory_loyalty_caps_at_100(django_user_model):
    user = django_user_model.objects.create_user(username="loyalty_cap", password="pass123")
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key="loyalty_cap_tpl",
        name="忠诚测试门客",
        rarity=GuestRarity.GRAY,
        base_attack=10,
        base_defense=10,
    )
    guest = Guest.objects.create(manor=manor, template=template, force=10, intellect=10, loyalty=100)

    updated = grant_battle_victory_loyalty([guest])

    guest.refresh_from_db(fields=["loyalty"])
    assert updated == 1
    assert guest.loyalty == 100


@pytest.mark.django_db
def test_process_daily_loyalty_increases_paid_guests_and_decreases_unpaid_guests(django_user_model):
    user = django_user_model.objects.create_user(username="daily_loyalty", password="pass123")
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key="daily_loyalty_tpl",
        name="日结忠诚门客",
        rarity=GuestRarity.GRAY,
        base_attack=10,
        base_defense=10,
    )
    paid_guest = Guest.objects.create(manor=manor, template=template, force=10, intellect=10, loyalty=50)
    unpaid_guest = Guest.objects.create(manor=manor, template=template, force=10, intellect=10, loyalty=50)

    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    SalaryPayment.objects.create(manor=manor, guest=paid_guest, amount=100, for_date=yesterday)

    result = guest_tasks.process_daily_loyalty.run()

    paid_guest.refresh_from_db(fields=["loyalty", "loyalty_processed_for_date"])
    unpaid_guest.refresh_from_db(fields=["loyalty", "loyalty_processed_for_date"])
    assert paid_guest.loyalty == 51
    assert unpaid_guest.loyalty == 49
    assert paid_guest.loyalty_processed_for_date == today
    assert unpaid_guest.loyalty_processed_for_date == today
    assert "处理了 2 个门客的忠诚度" in result
