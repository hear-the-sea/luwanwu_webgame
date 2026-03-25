from __future__ import annotations

import pytest

from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestArchetype, GuestRarity, GuestTemplate


@pytest.mark.django_db
def test_guest_create_initializes_current_hp_to_max_when_missing(django_user_model):
    user = django_user_model.objects.create_user(username="guest_contract_default_hp", password="pass123")
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key="guest_contract_default_hp_tpl",
        name="门客契约测试",
        archetype=GuestArchetype.MILITARY,
        rarity=GuestRarity.GRAY,
        base_hp=1200,
    )

    guest = Guest.objects.create(manor=manor, template=template, defense_stat=80)

    assert guest.current_hp == guest.max_hp


@pytest.mark.django_db
def test_guest_save_initializes_current_hp_to_max_when_missing(django_user_model):
    user = django_user_model.objects.create_user(username="guest_contract_save_default_hp", password="pass123")
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key="guest_contract_save_default_hp_tpl",
        name="门客契约测试4",
        archetype=GuestArchetype.MILITARY,
        rarity=GuestRarity.GRAY,
        base_hp=1200,
    )

    guest = Guest(manor=manor, template=template, defense_stat=80)
    guest.save()

    assert guest.current_hp == guest.max_hp


@pytest.mark.django_db
def test_guest_create_preserves_explicit_current_hp(django_user_model):
    user = django_user_model.objects.create_user(username="guest_contract_explicit_hp", password="pass123")
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key="guest_contract_explicit_hp_tpl",
        name="门客契约测试2",
        archetype=GuestArchetype.MILITARY,
        rarity=GuestRarity.GRAY,
        base_hp=1200,
    )

    guest = Guest.objects.create(manor=manor, template=template, defense_stat=80, current_hp=5)

    assert guest.current_hp == 5


@pytest.mark.django_db
def test_guest_update_preserves_zero_current_hp_for_existing_record(django_user_model):
    user = django_user_model.objects.create_user(username="guest_contract_zero_hp_update", password="pass123")
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key="guest_contract_zero_hp_update_tpl",
        name="门客契约测试3",
        archetype=GuestArchetype.MILITARY,
        rarity=GuestRarity.GRAY,
        base_hp=1200,
    )

    guest = Guest.objects.create(manor=manor, template=template, defense_stat=80)
    guest.current_hp = 0
    guest.save(update_fields=["current_hp"])
    guest.refresh_from_db()

    assert guest.current_hp == 0
