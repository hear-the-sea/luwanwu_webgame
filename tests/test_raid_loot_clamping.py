import pytest
from django.contrib.auth import get_user_model
from django.db import transaction

from gameplay.models import InventoryItem, ItemTemplate, ResourceEvent
from gameplay.services.manor.core import ensure_manor
from gameplay.services.raid.combat import (
    _apply_loot,
    _format_battle_rewards_description,
    _format_loot_description,
    _grant_loot_items,
)

User = get_user_model()


@pytest.mark.django_db
def test_apply_loot_clamps_to_available_resources():
    user = User.objects.create_user(username="raid_defender", password="pass123")
    defender = ensure_manor(user)
    defender.grain = 50
    defender.silver = 20
    defender.save(update_fields=["grain", "silver"])

    with transaction.atomic():
        actual_resources, actual_items = _apply_loot(
            defender,
            loot_resources={"grain": 100, "silver": 10},
            loot_items={},
        )

    defender.refresh_from_db()
    assert actual_resources == {"grain": 50, "silver": 10}
    assert actual_items == {}
    assert defender.grain == 0
    assert defender.silver == 10

    deltas = {
        event.resource_type: event.delta
        for event in ResourceEvent.objects.filter(
            manor=defender,
            reason=ResourceEvent.Reason.ADMIN_ADJUST,
            note="踢馆被掠夺",
        )
    }
    assert deltas == {"grain": -50, "silver": -10}


@pytest.mark.django_db
def test_grant_loot_items_normalizes_quantities():
    user = User.objects.create_user(username="raid_loot_grant", password="pass123")
    manor = ensure_manor(user)
    template = ItemTemplate.objects.create(key="raid_loot_item", name="Raid Loot", tradeable=True)

    _grant_loot_items(
        manor,
        {
            "raid_loot_item": "2",
            "raid_loot_item_bad": -3,
            "": 5,
        },
    )

    item = InventoryItem.objects.get(
        manor=manor,
        template=template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert item.quantity == 2


def test_formatters_tolerate_invalid_mapping_shapes():
    assert _format_loot_description(["bad"], ["shape"]) == "无"
    assert _format_battle_rewards_description(["bad"]) == ""
    assert "经验果 x3" in _format_battle_rewards_description({"exp_fruit": "3", "equipment": ["bad"]})
