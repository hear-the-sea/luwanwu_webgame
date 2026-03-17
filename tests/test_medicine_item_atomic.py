from __future__ import annotations

import uuid

import pytest

from core.exceptions import GuestNotIdleError
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from guests.models import GuestStatus, RecruitmentPool
from guests.services.health import use_medicine_item_for_guest
from guests.services.recruitment import recruit_guest
from guests.services.recruitment_guests import finalize_candidate


def _bootstrap_injured_guest(game_data, django_user_model, *, username: str):
    user = django_user_model.objects.create_user(username=username, password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=1)[0]
    guest = finalize_candidate(candidate)

    injured_hp = max(1, int(guest.max_hp * 0.1))
    guest.current_hp = injured_hp
    guest.status = GuestStatus.INJURED
    guest.save(update_fields=["current_hp", "status"])
    return manor, guest


def _create_medicine_item(manor, *, heal_amount: int = 120) -> InventoryItem:
    suffix = uuid.uuid4().hex[:10]
    template = ItemTemplate.objects.create(
        key=f"test_medicine_item_{suffix}",
        name="疗伤药",
        effect_type=ItemTemplate.EffectType.MEDICINE,
        is_usable=True,
        tradeable=False,
        effect_payload={"hp": heal_amount},
    )
    return InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )


@pytest.mark.django_db
def test_use_medicine_item_for_guest_is_atomic_success(game_data, django_user_model):
    manor, guest = _bootstrap_injured_guest(game_data, django_user_model, username="medicine_item_atomic_ok")
    heal_amount = max(1, int(guest.max_hp * 0.3))
    item = _create_medicine_item(manor, heal_amount=heal_amount)

    before_hp = guest.current_hp
    result = use_medicine_item_for_guest(manor, guest, item.pk, heal_amount)

    guest.refresh_from_db()
    assert guest.current_hp > before_hp
    assert guest.status == GuestStatus.IDLE
    assert bool(result["injury_cured"]) is True
    assert int(result["remaining_item_quantity"]) == 0
    assert InventoryItem.objects.filter(pk=item.pk).exists() is False


@pytest.mark.django_db
def test_use_medicine_item_for_guest_rolls_back_when_consume_fails(monkeypatch, game_data, django_user_model):
    manor, guest = _bootstrap_injured_guest(game_data, django_user_model, username="medicine_item_atomic_rollback")
    heal_amount = max(1, int(guest.max_hp * 0.25))
    item = _create_medicine_item(manor, heal_amount=heal_amount)

    before_hp = guest.current_hp
    before_status = guest.status

    def _boom(*_args, **_kwargs):
        raise RuntimeError("consume failed")

    monkeypatch.setattr("gameplay.services.inventory.core.consume_inventory_item_locked", _boom)

    with pytest.raises(RuntimeError, match="consume failed"):
        use_medicine_item_for_guest(manor, guest, item.pk, heal_amount)

    guest.refresh_from_db()
    item.refresh_from_db()

    assert guest.current_hp == before_hp
    assert guest.status == before_status
    assert item.quantity == 1


@pytest.mark.django_db
def test_use_medicine_item_for_guest_sanitizes_malformed_heal_result(monkeypatch, game_data, django_user_model):
    manor, guest = _bootstrap_injured_guest(game_data, django_user_model, username="medicine_item_malformed_result")
    heal_amount = max(1, int(guest.max_hp * 0.2))
    item = _create_medicine_item(manor, heal_amount=heal_amount)

    def _malformed_heal(_guest, _heal_amount):
        return {"healed": "bad", "injury_cured": False}

    monkeypatch.setattr("guests.services.health.heal_guest", _malformed_heal)

    result = use_medicine_item_for_guest(manor, guest, item.pk, heal_amount)

    assert result["healed"] == 0
    assert result["remaining_item_quantity"] == 0
    assert InventoryItem.objects.filter(pk=item.pk).exists() is False


@pytest.mark.django_db
def test_use_medicine_item_for_guest_rejects_non_idle_busy_status(game_data, django_user_model):
    manor, guest = _bootstrap_injured_guest(game_data, django_user_model, username="medicine_item_busy_reject")
    guest.status = GuestStatus.WORKING
    guest.save(update_fields=["status"])
    heal_amount = max(1, int(guest.max_hp * 0.2))
    item = _create_medicine_item(manor, heal_amount=heal_amount)

    with pytest.raises(GuestNotIdleError):
        use_medicine_item_for_guest(manor, guest, item.pk, heal_amount)

    guest.refresh_from_db()
    item.refresh_from_db()
    assert guest.status == GuestStatus.WORKING
    assert item.quantity == 1
