from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from guests.models import RecruitmentPool
from guests.services.recruitment import recruit_guest
from guests.services.recruitment_guests import finalize_candidate
from guests.services.training import ensure_auto_training, use_experience_item_for_guest


def _bootstrap_training_guest(game_data, django_user_model, *, username: str):
    user = django_user_model.objects.create_user(username=username, password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=1)[0]
    guest = finalize_candidate(candidate)

    ensure_auto_training(guest)
    guest.refresh_from_db()
    guest.training_complete_at = timezone.now() + timezone.timedelta(seconds=600)
    guest.training_target_level = guest.level + 1
    guest.save(update_fields=["training_complete_at", "training_target_level"])

    return manor, guest


def _create_experience_item(manor, *, seconds: int = 120) -> InventoryItem:
    suffix = uuid.uuid4().hex[:10]
    template = ItemTemplate.objects.create(
        key=f"test_exp_item_{suffix}",
        name="训练加速符",
        effect_type=ItemTemplate.EffectType.EXPERIENCE_ITEM,
        is_usable=True,
        tradeable=False,
        effect_payload={"time": seconds},
    )
    return InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )


@pytest.mark.django_db
def test_use_experience_item_for_guest_is_atomic_success(game_data, django_user_model):
    manor, guest = _bootstrap_training_guest(game_data, django_user_model, username="exp_item_atomic_ok")
    item = _create_experience_item(manor, seconds=120)

    before_eta = guest.training_complete_at
    result = use_experience_item_for_guest(manor, guest, item.pk, 120)

    guest.refresh_from_db()
    assert before_eta is not None
    assert guest.training_complete_at is not None
    assert guest.training_complete_at < before_eta
    assert int(result["time_reduced"]) > 0
    assert int(result["remaining_item_quantity"]) == 0
    assert InventoryItem.objects.filter(pk=item.pk).exists() is False


@pytest.mark.django_db
def test_use_experience_item_for_guest_rolls_back_when_consume_fails(monkeypatch, game_data, django_user_model):
    manor, guest = _bootstrap_training_guest(game_data, django_user_model, username="exp_item_atomic_rollback")
    item = _create_experience_item(manor, seconds=180)

    before_eta = guest.training_complete_at

    def _boom(*_args, **_kwargs):
        raise RuntimeError("consume failed")

    monkeypatch.setattr("gameplay.services.inventory.core.consume_inventory_item_locked", _boom)

    with pytest.raises(RuntimeError, match="consume failed"):
        use_experience_item_for_guest(manor, guest, item.pk, 180)

    guest.refresh_from_db()
    item.refresh_from_db()

    assert guest.training_complete_at == before_eta
    assert item.quantity == 1


@pytest.mark.django_db
def test_use_experience_item_for_guest_sanitizes_malformed_reduce_result(monkeypatch, game_data, django_user_model):
    manor, guest = _bootstrap_training_guest(game_data, django_user_model, username="exp_item_malformed_result")
    item = _create_experience_item(manor, seconds=120)

    def _malformed_reduce(_guest, _seconds):
        return {"time_reduced": "bad", "applied_levels": "bad", "next_eta": _guest.training_complete_at}

    monkeypatch.setattr("guests.services.training.reduce_training_time_for_guest", _malformed_reduce)

    result = use_experience_item_for_guest(manor, guest, item.pk, 120)

    assert result["time_reduced"] == 0
    assert result["applied_levels"] == 0
    assert result["remaining_item_quantity"] == 0
    assert InventoryItem.objects.filter(pk=item.pk).exists() is False
