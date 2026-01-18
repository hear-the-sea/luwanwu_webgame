import pytest

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.inventory import use_inventory_item
from gameplay.services.manor import ensure_manor
from guests.models import Guest, GuestTemplate
from core.exceptions import GuestCapacityFullError


def _make_pubayi_template(key: str, rarity: str) -> GuestTemplate:
    return GuestTemplate.objects.create(
        key=key,
        name="蒲巴乙",
        archetype="civil",
        rarity=rarity,
        base_attack=80,
        base_intellect=90,
        base_defense=70,
        base_agility=75,
        base_luck=60,
        base_hp=1000,
        default_gender="male",
        default_morality=60,
        recruitable=False,
    )


@pytest.mark.django_db
def test_summon_card_rolls_blue(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="summon_blue", password="pass123")
    manor = ensure_manor(user)

    blue = _make_pubayi_template("pubayi_blue_test", "blue")
    green = _make_pubayi_template("pubayi_green_test", "green")

    template = ItemTemplate.objects.create(
        key="pubayi_guest_card_test",
        name="蒲巴乙门客卡",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "summon_guest",
            "choices": [
                {"template_key": blue.key, "weight": 10},
                {"template_key": green.key, "weight": 90},
            ],
        },
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    monkeypatch.setattr("gameplay.services.inventory.random.random", lambda: 0.05)
    payload = use_inventory_item(item)

    assert payload["获得门客"] == "蒲巴乙"
    assert payload["稀有度"] == "蓝"
    assert manor.guests.filter(template__key=blue.key).count() == 1
    assert not InventoryItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
def test_summon_card_rolls_green(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="summon_green", password="pass123")
    manor = ensure_manor(user)

    blue = _make_pubayi_template("pubayi_blue_test2", "blue")
    green = _make_pubayi_template("pubayi_green_test2", "green")

    template = ItemTemplate.objects.create(
        key="pubayi_guest_card_test2",
        name="蒲巴乙门客卡",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "summon_guest",
            "choices": [
                {"template_key": blue.key, "weight": 10},
                {"template_key": green.key, "weight": 90},
            ],
        },
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    monkeypatch.setattr("gameplay.services.inventory.random.random", lambda: 0.50)
    payload = use_inventory_item(item)

    assert payload["获得门客"] == "蒲巴乙"
    assert payload["稀有度"] == "绿"
    assert manor.guests.filter(template__key=green.key).count() == 1
    assert not InventoryItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
def test_summon_card_respects_guest_capacity(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="summon_full", password="pass123")
    manor = ensure_manor(user)

    blue = _make_pubayi_template("pubayi_blue_test3", "blue")
    green = _make_pubayi_template("pubayi_green_test3", "green")

    # Fill capacity
    capacity = manor.guest_capacity
    for _ in range(capacity):
        Guest.objects.create(
            manor=manor,
            template=green,
            force=80,
            intellect=90,
            defense_stat=70,
            agility=75,
            luck=60,
            loyalty=60,
            gender="male",
            morality=60,
        )

    template = ItemTemplate.objects.create(
        key="pubayi_guest_card_test3",
        name="蒲巴乙门客卡",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "summon_guest",
            "choices": [
                {"template_key": blue.key, "weight": 10},
                {"template_key": green.key, "weight": 90},
            ],
        },
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    monkeypatch.setattr("gameplay.services.inventory.random.random", lambda: 0.05)
    with pytest.raises(GuestCapacityFullError):
        use_inventory_item(item)

    item.refresh_from_db()
    assert item.quantity == 1
