from __future__ import annotations

import pytest

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from guests.models import RecruitmentPool
from guests.services import recruit_guest, use_magnifying_glass_for_candidates


def _bootstrap_candidates(game_data, django_user_model, *, username: str) -> tuple:
    user = django_user_model.objects.create_user(username=username, password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidates = recruit_guest(manor, pool, seed=1)
    manor.candidates.update(rarity_revealed=False)
    return manor, len(candidates)


def _create_magnifying_item(manor) -> InventoryItem:
    template, _created = ItemTemplate.objects.get_or_create(
        key="fangdajing",
        defaults={
            "name": "放大镜",
            "effect_type": ItemTemplate.EffectType.TOOL,
            "is_usable": False,
            "tradeable": False,
        },
    )
    return InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )


@pytest.mark.django_db
def test_use_magnifying_glass_for_candidates_is_atomic_success(game_data, django_user_model):
    manor, candidate_count = _bootstrap_candidates(game_data, django_user_model, username="magnify_atomic_ok")
    item = _create_magnifying_item(manor)

    revealed_count = use_magnifying_glass_for_candidates(manor, item.pk)

    assert revealed_count == candidate_count
    assert manor.candidates.filter(rarity_revealed=False).count() == 0
    assert InventoryItem.objects.filter(pk=item.pk).exists() is False


@pytest.mark.django_db
def test_use_magnifying_glass_for_candidates_rolls_back_when_consume_fails(monkeypatch, game_data, django_user_model):
    manor, _candidate_count = _bootstrap_candidates(game_data, django_user_model, username="magnify_atomic_rollback")
    item = _create_magnifying_item(manor)
    before_unrevealed = manor.candidates.filter(rarity_revealed=False).count()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("consume failed")

    monkeypatch.setattr("gameplay.services.inventory.core.consume_inventory_item_locked", _boom)

    with pytest.raises(RuntimeError, match="consume failed"):
        use_magnifying_glass_for_candidates(manor, item.pk)

    item.refresh_from_db()
    assert manor.candidates.filter(rarity_revealed=False).count() == before_unrevealed
    assert item.quantity == 1
