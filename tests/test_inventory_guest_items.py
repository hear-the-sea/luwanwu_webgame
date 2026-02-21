import pytest

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.inventory import use_xisuidan
from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestStatus, GuestTemplate


def _prepare_xisuidan_case(django_user_model, suffix: str):
    user = django_user_model.objects.create_user(username=f"xisuidan_{suffix}", password="pass123")
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key=f"xisuidan_guest_tpl_{suffix}",
        name="洗髓测试门客",
        archetype="civil",
        rarity="gray",
        base_attack=80,
        base_intellect=90,
        base_defense=70,
        base_agility=75,
        base_luck=60,
        base_hp=1000,
        default_gender="male",
        default_morality=60,
    )
    guest = Guest.objects.create(
        manor=manor,
        template=template,
        level=100,
        force=150,
        intellect=150,
        defense_stat=150,
        agility=150,
        luck=60,
        loyalty=60,
        gender="male",
        morality=60,
        status=GuestStatus.IDLE,
        initial_force=50,
        initial_intellect=50,
        initial_defense=50,
        initial_agility=50,
        allocated_force=0,
        allocated_intellect=0,
        allocated_defense=0,
        allocated_agility=0,
    )

    item_template = ItemTemplate.objects.create(
        key=f"xisuidan_item_tpl_{suffix}",
        name="洗髓丹",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={"action": "reroll_growth"},
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=item_template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    return manor, guest, item


@pytest.mark.django_db
def test_use_xisuidan_keeps_total_when_reroll_is_worse(monkeypatch, django_user_model):
    manor, guest, item = _prepare_xisuidan_case(django_user_model, "worse")

    monkeypatch.setattr(
        "guests.utils.attribute_growth.allocate_level_up_attributes",
        lambda *_args, **_kwargs: {"force": 10, "intellect": 10, "defense": 10, "agility": 10},
    )

    result = use_xisuidan(manor, item, guest.id)
    guest.refresh_from_db()

    assert result["old_total"] == 400
    assert result["new_total"] == 400
    assert result["growth_diff"] == 0
    assert guest.force == 150
    assert guest.intellect == 150
    assert guest.defense_stat == 150
    assert guest.agility == 150
    assert guest.xisuidan_used == 1
    assert not InventoryItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
def test_use_xisuidan_applies_better_growth(monkeypatch, django_user_model):
    manor, guest, item = _prepare_xisuidan_case(django_user_model, "better")

    monkeypatch.setattr(
        "guests.utils.attribute_growth.allocate_level_up_attributes",
        lambda *_args, **_kwargs: {"force": 120, "intellect": 120, "defense": 120, "agility": 120},
    )

    result = use_xisuidan(manor, item, guest.id)
    guest.refresh_from_db()

    assert result["old_total"] == 400
    assert result["new_total"] == 480
    assert result["growth_diff"] == 80
    assert guest.force == 170
    assert guest.intellect == 170
    assert guest.defense_stat == 170
    assert guest.agility == 170
    assert guest.xisuidan_used == 1
    assert not InventoryItem.objects.filter(pk=item.pk).exists()
