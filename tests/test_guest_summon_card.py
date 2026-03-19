import logging

import pytest

from core.exceptions import GuestCapacityFullError, InsufficientStockError, ItemNotFoundError
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.inventory.use import use_inventory_item
from gameplay.services.manor.core import ensure_manor
from guests.models import GearSlot, GearTemplate, Guest, GuestTemplate


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

    monkeypatch.setattr("gameplay.services.inventory.use.inventory_random.random", lambda: 0.05)
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

    monkeypatch.setattr("gameplay.services.inventory.use.inventory_random.random", lambda: 0.50)
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

    monkeypatch.setattr("gameplay.services.inventory.use.inventory_random.random", lambda: 0.05)
    with pytest.raises(GuestCapacityFullError):
        use_inventory_item(item)

    item.refresh_from_db()
    assert item.quantity == 1


@pytest.mark.django_db
def test_loot_box_logs_and_tracks_skipped_bonus_items(monkeypatch, caplog, django_user_model):
    user = django_user_model.objects.create_user(username="loot_box_skip_bonus", password="pass123")
    manor = ensure_manor(user)
    initial_silver = manor.silver

    template = ItemTemplate.objects.create(
        key="loot_box_skip_bonus_test",
        name="测试宝箱",
        effect_type=ItemTemplate.EffectType.LOOT_BOX,
        is_usable=True,
        effect_payload={
            "resources": {"silver": 100},
            "skill_book_chance": 1,
            "skill_book_keys": ["missing_bonus_item"],
        },
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    monkeypatch.setattr("gameplay.services.inventory.use.inventory_random.random", lambda: 0.0)
    monkeypatch.setattr("gameplay.services.inventory.use.inventory_random.choice", lambda keys: keys[0])

    def _raise_bonus_item_error(*_args, **_kwargs):
        raise ItemNotFoundError("bonus item template missing")

    monkeypatch.setattr(
        "gameplay.services.inventory.use.add_item_to_inventory",
        _raise_bonus_item_error,
    )

    with caplog.at_level(logging.WARNING):
        payload = use_inventory_item(item)

    manor.refresh_from_db()
    assert manor.silver == initial_silver + 100
    assert payload["skipped_bonus_items"] == ["missing_bonus_item"]
    assert any("loot box bonus item grant skipped" in rec.getMessage() for rec in caplog.records)
    assert not InventoryItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
def test_work_loot_box_grants_random_silver_and_single_gear_drop(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="work_loot_box_logic", password="pass123")
    manor = ensure_manor(user)
    initial_silver = manor.silver
    initial_target_gear_count = manor.gears.filter(template__key__in=["work_loot_gear_a", "work_loot_gear_b"]).count()

    gear_a = GearTemplate.objects.create(
        key="work_loot_gear_a",
        name="测试头盔A",
        slot=GearSlot.HELMET,
        rarity="green",
    )
    GearTemplate.objects.create(
        key="work_loot_gear_b",
        name="测试头盔B",
        slot=GearSlot.HELMET,
        rarity="green",
    )
    ItemTemplate.objects.create(
        key="work_loot_skill_book_a",
        name="测试技能书A",
        effect_type=ItemTemplate.EffectType.SKILL_BOOK,
        is_usable=False,
        effect_payload={"skill_key": "test_skill_a", "skill_name": "测试术法"},
        rarity="green",
    )

    chest_template = ItemTemplate.objects.create(
        key="work_loot_box_test",
        name="打工宝箱（小）测试",
        effect_type=ItemTemplate.EffectType.LOOT_BOX,
        is_usable=True,
        effect_payload={
            "silver_min": 8000,
            "silver_max": 9000,
            "gear_chance": 0.1,
            "gear_keys": ["work_loot_gear_a", "work_loot_gear_b"],
            "skill_book_chance": 0.1,
            "skill_book_keys": ["work_loot_skill_book_a"],
        },
    )
    chest = InventoryItem.objects.create(
        manor=manor,
        template=chest_template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    # gear roll + skill roll 都命中；装备/技能都选第一项；银两固定 8888
    roll_iter = iter([0.01, 0.01])
    monkeypatch.setattr("gameplay.services.inventory.use.inventory_random.random", lambda: next(roll_iter))
    monkeypatch.setattr("gameplay.services.inventory.use.inventory_random.choice", lambda seq: seq[0])
    monkeypatch.setattr("gameplay.services.inventory.use.inventory_random.randint", lambda _a, _b: 8888)

    payload = use_inventory_item(chest)

    manor.refresh_from_db()
    assert manor.silver == initial_silver + 8888
    gained_gears = manor.gears.filter(template__key__in=["work_loot_gear_a", "work_loot_gear_b"])
    assert gained_gears.count() == initial_target_gear_count + 1
    assert gained_gears.filter(template_id=gear_a.id).exists()

    skill_book_entry = InventoryItem.objects.filter(
        manor=manor,
        template__key="work_loot_skill_book_a",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).first()
    assert skill_book_entry is not None
    assert skill_book_entry.quantity == 1

    rewards = payload["rewards"]
    assert "银两+8888" in rewards
    assert len([entry for entry in rewards if entry.startswith("装备【")]) == 1
    assert len([entry for entry in rewards if entry.startswith("技能书【")]) == 1
    assert payload["skipped_bonus_items"] == []
    assert not InventoryItem.objects.filter(pk=chest.pk).exists()


@pytest.mark.django_db
def test_summon_card_rejects_duplicate_unique_guest(django_user_model):
    user = django_user_model.objects.create_user(username="summon_unique_guard", password="pass123")
    manor = ensure_manor(user)
    unique_key = "test_unique_guest_guard_001"

    template = GuestTemplate.objects.create(
        key=unique_key,
        name="潘凤",
        archetype="military",
        rarity="green",
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
    Guest.objects.create(
        manor=manor,
        template=template,
        force=80,
        intellect=90,
        defense_stat=70,
        agility=75,
        luck=60,
        loyalty=60,
        gender="male",
        morality=60,
    )

    card_template = ItemTemplate.objects.create(
        key="panfeng_guest_card_unique_guard_test",
        name="潘凤门客卡",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "summon_guest",
            "exclusive_template_keys": [
                unique_key,
                f"{unique_key}_blue",
                f"{unique_key}_purple",
            ],
            "choices": [
                {"template_key": unique_key, "weight": 100},
            ],
        },
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=card_template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    with pytest.raises(ValueError, match="不可重复获得"):
        use_inventory_item(item)

    item.refresh_from_db()
    assert item.quantity == 1


@pytest.mark.django_db
def test_summon_card_consumes_required_items_on_success(django_user_model):
    user = django_user_model.objects.create_user(username="summon_required_items_ok", password="pass123")
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key="orig_zhu_yingtai_test",
        name="祝英台",
        archetype="civil",
        rarity="purple",
        base_attack=80,
        base_intellect=90,
        base_defense=70,
        base_agility=75,
        base_luck=60,
        base_hp=1000,
        default_gender="female",
        default_morality=60,
        recruitable=False,
    )
    good_card_template = ItemTemplate.objects.create(
        key="haorenka_test",
        name="好人卡",
        effect_type=ItemTemplate.EffectType.RESOURCE,
        is_usable=False,
        rarity="green",
    )
    scroll_template = ItemTemplate.objects.create(
        key="zhuyingtai_guest_scroll_test",
        name="祝英台门客合成卷轴",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "summon_guest",
            "required_items": {"haorenka_test": 360},
            "exclusive_template_keys": [template.key],
            "choices": [{"template_key": template.key, "weight": 100}],
        },
    )
    good_cards = InventoryItem.objects.create(
        manor=manor,
        template=good_card_template,
        quantity=400,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    scroll = InventoryItem.objects.create(
        manor=manor,
        template=scroll_template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    payload = use_inventory_item(scroll)

    assert payload["获得门客"] == "祝英台"
    assert manor.guests.filter(template__key=template.key).count() == 1
    good_cards.refresh_from_db()
    assert good_cards.quantity == 40
    assert not InventoryItem.objects.filter(pk=scroll.pk).exists()


@pytest.mark.django_db
def test_summon_card_keeps_scroll_when_required_items_insufficient(django_user_model):
    user = django_user_model.objects.create_user(username="summon_required_items_fail", password="pass123")
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key="orig_liang_shanbo_test",
        name="梁山伯",
        archetype="civil",
        rarity="blue",
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
    good_card_template = ItemTemplate.objects.create(
        key="haorenka_test_short",
        name="好人卡",
        effect_type=ItemTemplate.EffectType.RESOURCE,
        is_usable=False,
        rarity="green",
    )
    scroll_template = ItemTemplate.objects.create(
        key="liangshanbo_guest_scroll_test",
        name="梁山伯门客合成卷轴",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "summon_guest",
            "required_items": {"haorenka_test_short": 210},
            "exclusive_template_keys": [template.key],
            "choices": [{"template_key": template.key, "weight": 100}],
        },
    )
    good_cards = InventoryItem.objects.create(
        manor=manor,
        template=good_card_template,
        quantity=100,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    scroll = InventoryItem.objects.create(
        manor=manor,
        template=scroll_template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    with pytest.raises(InsufficientStockError):
        use_inventory_item(scroll)

    scroll.refresh_from_db()
    good_cards.refresh_from_db()
    assert scroll.quantity == 1
    assert good_cards.quantity == 100
    assert manor.guests.filter(template__key=template.key).count() == 0
