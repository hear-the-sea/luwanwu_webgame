import pytest

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.inventory.guest_items import (
    use_guest_rarity_upgrade_item,
    use_guest_rebirth_card,
    use_soul_container,
    use_xidianka,
    use_xisuidan,
)
from gameplay.services.manor.core import ensure_manor
from guests.models import GearItem, GearSlot, GearTemplate, Guest, GuestSkill, GuestStatus, GuestTemplate, Skill
from guests.services.equipment import ensure_inventory_gears, equip_guest, unequip_guest_item
from guests.utils.attribute_growth import allocate_level_up_attributes


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


def _prepare_rarity_upgrade_case(django_user_model, suffix: str):
    user = django_user_model.objects.create_user(username=f"rarity_upgrade_{suffix}", password="pass123")
    manor = ensure_manor(user)

    green_template = GuestTemplate.objects.create(
        key=f"hist_sljnbc_0589_{suffix}",
        name="邢道荣",
        archetype="military",
        rarity="green",
        base_attack=120,
        base_intellect=80,
        base_defense=100,
        base_agility=90,
        base_luck=50,
        base_hp=1200,
        growth_range=[4, 8],
        attribute_weights={"force": 40, "intellect": 30, "defense": 15, "agility": 15},
    )
    blue_template = GuestTemplate.objects.create(
        key=f"hist_sljnbc_0589_blue_{suffix}",
        name="邢道荣",
        archetype="military",
        rarity="blue",
        base_attack=150,
        base_intellect=100,
        base_defense=130,
        base_agility=110,
        base_luck=60,
        base_hp=1500,
        growth_range=[],
        attribute_weights={"force": 40, "intellect": 30, "defense": 15, "agility": 15},
        recruitable=False,
    )
    guest = Guest.objects.create(
        manor=manor,
        template=green_template,
        level=50,
        force=220,
        intellect=180,
        defense_stat=200,
        agility=170,
        luck=60,
        loyalty=80,
        gender="male",
        morality=60,
        status=GuestStatus.IDLE,
        initial_force=80,
        initial_intellect=70,
        initial_defense=75,
        initial_agility=72,
    )

    item_template = ItemTemplate.objects.create(
        key=f"rarity_upgrade_item_tpl_{suffix}",
        name="进击的无双上将",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "upgrade_guest_rarity",
            "target_template_map": {
                green_template.key: blue_template.key,
            },
        },
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=item_template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    return manor, guest, item, green_template, blue_template


def _prepare_rarity_upgrade_blue_to_purple_case(django_user_model, suffix: str):
    user = django_user_model.objects.create_user(username=f"rarity_upgrade_bp_{suffix}", password="pass123")
    manor = ensure_manor(user)

    blue_template = GuestTemplate.objects.create(
        key=f"hist_sljnbc_0589_blue_{suffix}",
        name="邢道荣",
        archetype="military",
        rarity="blue",
        base_attack=150,
        base_intellect=100,
        base_defense=130,
        base_agility=110,
        base_luck=60,
        base_hp=1500,
        growth_range=[],
        attribute_weights={"force": 40, "intellect": 30, "defense": 15, "agility": 15},
        recruitable=False,
    )
    purple_template = GuestTemplate.objects.create(
        key=f"hist_sljnbc_0589_purple_{suffix}",
        name="邢道荣",
        archetype="military",
        rarity="purple",
        base_attack=180,
        base_intellect=120,
        base_defense=150,
        base_agility=130,
        base_luck=70,
        base_hp=1800,
        growth_range=[],
        attribute_weights={"force": 40, "intellect": 30, "defense": 15, "agility": 15},
        recruitable=False,
    )
    guest = Guest.objects.create(
        manor=manor,
        template=blue_template,
        level=60,
        force=280,
        intellect=220,
        defense_stat=230,
        agility=210,
        luck=65,
        loyalty=80,
        gender="male",
        morality=60,
        status=GuestStatus.IDLE,
        initial_force=100,
        initial_intellect=90,
        initial_defense=95,
        initial_agility=92,
    )

    item_template = ItemTemplate.objects.create(
        key=f"rarity_upgrade_item_tpl_bp_{suffix}",
        name="《上将的自我修养》残卷2",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "upgrade_guest_rarity",
            "target_template_map": {
                blue_template.key: purple_template.key,
            },
        },
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=item_template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    return manor, guest, item, blue_template, purple_template


def _prepare_rebirth_case(django_user_model, suffix: str):
    user = django_user_model.objects.create_user(username=f"rebirth_{suffix}", password="pass123")
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key=f"rebirth_guest_tpl_{suffix}",
        name="重生测试门客",
        archetype="military",
        rarity="green",
        base_attack=90,
        base_intellect=70,
        base_defense=80,
        base_agility=75,
        base_luck=45,
        base_hp=1200,
        default_gender="male",
        default_morality=60,
    )
    guest = Guest.objects.create(
        manor=manor,
        template=template,
        level=35,
        experience=987,
        force=180,
        intellect=120,
        defense_stat=150,
        agility=142,
        luck=55,
        loyalty=80,
        gender="male",
        morality=60,
        status=GuestStatus.IDLE,
        attribute_points=11,
        attack_bonus=5,
        defense_bonus=6,
        hp_bonus=120,
        initial_force=70,
        initial_intellect=55,
        initial_defense=60,
        initial_agility=58,
        allocated_force=9,
        allocated_intellect=5,
        allocated_defense=4,
        allocated_agility=3,
        xisuidan_used=4,
        training_target_level=40,
    )
    guest.restore_full_hp()

    item_template = ItemTemplate.objects.create(
        key=f"rebirth_item_tpl_{suffix}",
        name="门客重生卡",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={"action": "rebirth_guest"},
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=item_template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    return manor, guest, item


def _prepare_xidianka_case(django_user_model, suffix: str):
    user = django_user_model.objects.create_user(username=f"xidianka_{suffix}", password="pass123")
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key=f"xidianka_guest_tpl_{suffix}",
        name="洗点测试门客",
        archetype="civil",
        rarity="blue",
        base_attack=88,
        base_intellect=96,
        base_defense=82,
        base_agility=86,
        base_luck=50,
        base_hp=1300,
        default_gender="male",
        default_morality=60,
    )
    guest = Guest.objects.create(
        manor=manor,
        template=template,
        level=42,
        force=166,
        intellect=194,
        defense_stat=154,
        agility=161,
        luck=58,
        loyalty=82,
        gender="male",
        morality=60,
        status=GuestStatus.IDLE,
        attribute_points=7,
        initial_force=90,
        initial_intellect=100,
        initial_defense=86,
        initial_agility=88,
        allocated_force=12,
        allocated_intellect=9,
        allocated_defense=7,
        allocated_agility=5,
    )

    item_template = ItemTemplate.objects.create(
        key=f"xidianka_item_tpl_{suffix}",
        name="洗点卡",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={"action": "reset_allocation"},
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=item_template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    return manor, guest, item


def _prepare_soul_container_case(
    django_user_model,
    suffix: str,
    *,
    guest_rarity: str,
    archetype: str,
    level: int,
    force: int,
    intellect: int,
    defense: int,
    agility: int,
    luck: int,
):
    user = django_user_model.objects.create_user(username=f"soul_container_{suffix}", password="pass123")
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key=f"soul_container_guest_tpl_{suffix}",
        name=f"灵魂融合门客{suffix}",
        archetype=archetype,
        rarity=guest_rarity,
        base_attack=max(80, force - 40),
        base_intellect=max(80, intellect - 30),
        base_defense=max(80, defense - 30),
        base_agility=max(70, agility - 30),
        base_luck=max(40, luck - 10),
        base_hp=1200,
        default_gender="male",
        default_morality=60,
    )
    guest = Guest.objects.create(
        manor=manor,
        template=template,
        level=level,
        force=force,
        intellect=intellect,
        defense_stat=defense,
        agility=agility,
        luck=luck,
        loyalty=80,
        gender="male",
        morality=60,
        status=GuestStatus.IDLE,
        initial_force=max(40, force - 90),
        initial_intellect=max(40, intellect - 80),
        initial_defense=max(40, defense - 80),
        initial_agility=max(40, agility - 80),
    )

    item_template = ItemTemplate.objects.create(
        key=f"soul_container_item_tpl_{suffix}",
        name="灵魂容器",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "soul_fusion",
            "min_level": 30,
            "allowed_rarities": ["green", "blue", "purple"],
        },
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


@pytest.mark.django_db
def test_use_xisuidan_rejects_non_idle_guest(django_user_model):
    manor, guest, item = _prepare_xisuidan_case(django_user_model, "non_idle")
    guest.status = GuestStatus.WORKING
    guest.save(update_fields=["status"])

    with pytest.raises(ValueError, match="非空闲状态"):
        use_xisuidan(manor, item, guest.id)

    item.refresh_from_db()
    assert item.quantity == 1


@pytest.mark.django_db
def test_use_guest_rebirth_card_resets_guest_progression_and_clears_gear(django_user_model):
    manor, guest, item = _prepare_rebirth_case(django_user_model, "ok")

    gear_template = GearTemplate.objects.create(
        key="rebirth_test_blade",
        name="重生测试佩刀",
        slot=GearSlot.WEAPON,
        rarity="green",
    )
    returned_item_template = ItemTemplate.objects.create(
        key="rebirth_test_blade",
        name="重生测试佩刀",
        effect_type="equip_weapon",
        rarity="green",
    )
    GearItem.objects.create(manor=manor, template=gear_template, guest=guest)
    skill = Skill.objects.create(key="rebirth_test_skill", name="重生测试技能")
    GuestSkill.objects.create(guest=guest, skill=skill)

    result = use_guest_rebirth_card(manor, item, guest.id)

    guest.refresh_from_db()
    assert guest.level == 1
    assert guest.experience == 0
    assert guest.attribute_points == 0
    assert guest.attack_bonus == 0
    assert guest.defense_bonus == 0
    assert guest.hp_bonus == 0
    assert guest.training_target_level == 2
    assert guest.training_complete_at is not None
    assert guest.xisuidan_used == 0
    assert guest.allocated_force == 0
    assert guest.allocated_intellect == 0
    assert guest.allocated_defense == 0
    assert guest.allocated_agility == 0
    assert guest.status == GuestStatus.IDLE
    assert guest.current_hp == guest.max_hp
    assert guest.gear_items.count() == 0
    assert guest.guest_skills.count() == 0
    assert guest.initial_force == guest.force
    assert guest.initial_intellect == guest.intellect
    assert guest.initial_defense == guest.defense_stat
    assert guest.initial_agility == guest.agility
    assert result["old_level"] == 35
    assert result["unequipped_count"] == 1
    assert result["skills_cleared"] == 1
    assert "技能已清空（1个）" in result["_message"]
    assert "装备已卸下（1件）" in result["_message"]
    assert not InventoryItem.objects.filter(pk=item.pk).exists()
    returned_weapon = InventoryItem.objects.get(manor=manor, template=returned_item_template)
    assert returned_weapon.quantity == 1


@pytest.mark.django_db
def test_use_xidianka_resets_allocated_points_and_refunds_attribute_points(django_user_model):
    manor, guest, item = _prepare_xidianka_case(django_user_model, "ok")

    result = use_xidianka(manor, item, guest.id)

    guest.refresh_from_db()
    assert guest.force == 154
    assert guest.intellect == 185
    assert guest.defense_stat == 147
    assert guest.agility == 156
    assert guest.attribute_points == 40
    assert guest.allocated_force == 0
    assert guest.allocated_intellect == 0
    assert guest.allocated_defense == 0
    assert guest.allocated_agility == 0
    assert result["total_returned"] == 33
    assert result["details"] == {"force": 12, "intellect": 9, "defense": 7, "agility": 5}
    assert "返还 33 属性点" in result["_message"]
    assert "武力-12" in result["_message"]
    assert "智力-9" in result["_message"]
    assert not InventoryItem.objects.filter(pk=item.pk).exists()


class _RangeSpyRng:
    def __init__(self):
        self.last_range = None

    def randint(self, a: int, b: int) -> int:
        self.last_range = (a, b)
        return a

    def choice(self, seq):
        return seq[0]


class _SoulFusionFixedRng:
    def randint(self, a: int, b: int) -> int:
        return (a + b) // 2

    def uniform(self, _a: float, _b: float) -> float:
        return 0.0


def _attach_soul_fusion_gear_state(
    guest: Guest,
    *,
    manor,
    key: str,
    name: str,
    slot: str = GearSlot.WEAPON,
    rarity: str = "green",
    extra_stats: dict | None = None,
    set_bonus: dict | None = None,
) -> ItemTemplate:
    extra_stats = extra_stats or {}
    set_bonus = set_bonus or {}

    item_template = ItemTemplate.objects.create(
        key=key,
        name=name,
        effect_type="equip_weapon" if slot == GearSlot.WEAPON else "equip_ornament",
        rarity=rarity,
    )
    gear_template = GearTemplate.objects.create(
        key=key,
        name=name,
        slot=slot,
        rarity=rarity,
        extra_stats=extra_stats,
    )
    GearItem.objects.create(manor=manor, template=gear_template, guest=guest)

    guest.force += int(extra_stats.get("force", 0) or 0) + int(set_bonus.get("force", 0) or 0)
    guest.intellect += int(extra_stats.get("intellect", 0) or 0) + int(set_bonus.get("intellect", 0) or 0)
    guest.defense_stat += int(extra_stats.get("defense", 0) or 0)
    guest.agility += int(extra_stats.get("agility", 0) or 0) + int(set_bonus.get("agility", 0) or 0)
    guest.luck += int(extra_stats.get("luck", 0) or 0) + int(set_bonus.get("luck", 0) or 0)
    guest.gear_set_bonus = set_bonus
    guest.save(update_fields=["force", "intellect", "defense_stat", "agility", "luck", "gear_set_bonus"])

    return item_template


@pytest.mark.django_db
def test_use_guest_rarity_upgrade_item_switches_template_and_uses_blue_standard_growth_range(django_user_model):
    manor, guest, item, _green, blue = _prepare_rarity_upgrade_case(django_user_model, "ok")
    guest.level = 50
    guest.experience = 999
    guest.xisuidan_used = 6
    guest.allocated_force = 7
    guest.allocated_intellect = 8
    guest.allocated_defense = 9
    guest.allocated_agility = 10
    guest.save(
        update_fields=[
            "level",
            "experience",
            "xisuidan_used",
            "allocated_force",
            "allocated_intellect",
            "allocated_defense",
            "allocated_agility",
        ]
    )
    gear_template = GearTemplate.objects.create(
        key="rarity_upgrade_test_helmet",
        name="测试头盔",
        slot=GearSlot.HELMET,
        rarity="green",
    )
    GearItem.objects.create(manor=manor, template=gear_template, guest=guest)
    skill = Skill.objects.create(key="rarity_upgrade_test_skill", name="测试技能")
    GuestSkill.objects.create(guest=guest, skill=skill)

    result = use_guest_rarity_upgrade_item(manor, item, guest.id)

    guest.refresh_from_db()
    assert guest.template_id == blue.id
    assert guest.rarity == "blue"
    assert guest.level == 1
    assert guest.experience == 0
    assert guest.xisuidan_used == 0
    assert guest.allocated_force == 0
    assert guest.allocated_intellect == 0
    assert guest.allocated_defense == 0
    assert guest.allocated_agility == 0
    assert guest.gear_items.count() == 0
    assert guest.guest_skills.count() == 0
    assert result["new_rarity"] == "蓝"
    assert result["new_level"] == 1
    assert result["skills_cleared"] == 1
    assert "等级重置为1级" in result["_message"]
    assert "洗髓丹计数已重置" in result["_message"]
    assert "技能已清空（1个）" in result["_message"]
    assert not InventoryItem.objects.filter(pk=item.pk).exists()

    spy_rng = _RangeSpyRng()
    allocate_level_up_attributes(guest, levels=1, rng=spy_rng)
    assert spy_rng.last_range == (5, 9)


@pytest.mark.django_db
def test_use_guest_rarity_upgrade_item_rejects_unsupported_guest(django_user_model):
    manor, _guest, item, _green, _blue = _prepare_rarity_upgrade_case(django_user_model, "unsupported")
    other_template = GuestTemplate.objects.create(
        key="rarity_upgrade_other_tpl",
        name="其他门客",
        archetype="civil",
        rarity="green",
    )
    other_guest = Guest.objects.create(
        manor=manor,
        template=other_template,
        status=GuestStatus.IDLE,
    )

    with pytest.raises(ValueError, match="无法使用此升阶道具"):
        use_guest_rarity_upgrade_item(manor, item, other_guest.id)

    item.refresh_from_db()
    assert item.quantity == 1


@pytest.mark.django_db
def test_use_guest_rarity_upgrade_item_switches_blue_to_purple_and_uses_purple_standard_growth_range(django_user_model):
    manor, guest, item, _blue, purple = _prepare_rarity_upgrade_blue_to_purple_case(django_user_model, "ok")

    result = use_guest_rarity_upgrade_item(manor, item, guest.id)

    guest.refresh_from_db()
    assert guest.template_id == purple.id
    assert guest.rarity == "purple"
    assert guest.level == 1
    assert guest.xisuidan_used == 0
    assert result["new_rarity"] == "紫"
    assert "等级重置为1级" in result["_message"]
    assert not InventoryItem.objects.filter(pk=item.pk).exists()

    spy_rng = _RangeSpyRng()
    allocate_level_up_attributes(guest, levels=1, rng=spy_rng)
    assert spy_rng.last_range == (6, 11)


@pytest.mark.django_db
def test_use_soul_container_generates_green_ornament_with_military_bias_and_returns_gear(
    monkeypatch, django_user_model
):
    manor, guest, item = _prepare_soul_container_case(
        django_user_model,
        "military_green",
        guest_rarity="green",
        archetype="military",
        level=80,
        force=240,
        intellect=128,
        defense=176,
        agility=190,
        luck=72,
    )
    monkeypatch.setattr(
        "gameplay.services.inventory.guest_items.inventory_random.Random", lambda: _SoulFusionFixedRng()
    )

    gear_item_template = _attach_soul_fusion_gear_state(
        guest,
        manor=manor,
        key="soul_fusion_returned_gear",
        name="灵魂融合测试佩剑",
        extra_stats={"force": 120, "agility": 30},
    )

    result = use_soul_container(manor, item, guest.id)

    generated_item = InventoryItem.objects.select_related("template").get(pk=result["generated_item_id"])
    payload = generated_item.template.effect_payload

    assert generated_item.template.name == "玉海棠"
    assert generated_item.template.rarity == "green"
    assert generated_item.template.effect_type == "equip_ornament"
    assert set(payload.keys()) == {"hp", "force", "intellect", "agility", "luck"}
    assert 42 <= payload["force"] + payload["intellect"] + payload["agility"] + payload["luck"] <= 54
    assert 130 <= payload["hp"] <= 210
    assert payload["force"] > payload["intellect"]
    assert payload["agility"] >= payload["luck"]
    assert not Guest.objects.filter(pk=guest.pk).exists()
    assert not InventoryItem.objects.filter(pk=item.pk).exists()
    returned_gear = InventoryItem.objects.get(manor=manor, template=gear_item_template)
    assert returned_gear.quantity == 1
    assert "玉海棠" in result["_message"]
    assert "装备已归还仓库（1件）" in result["_message"]


@pytest.mark.django_db
def test_use_soul_container_ignores_equipment_and_set_bonuses_when_rolling_stats(monkeypatch, django_user_model):
    base_kwargs = {
        "guest_rarity": "purple",
        "archetype": "military",
        "level": 92,
        "force": 260,
        "intellect": 148,
        "defense": 188,
        "agility": 176,
        "luck": 98,
    }
    equipped_manor, equipped_guest, equipped_item = _prepare_soul_container_case(
        django_user_model,
        "equipped_compare",
        **base_kwargs,
    )
    plain_manor, plain_guest, plain_item = _prepare_soul_container_case(
        django_user_model,
        "plain_compare",
        **base_kwargs,
    )

    returned_gear_template = _attach_soul_fusion_gear_state(
        equipped_guest,
        manor=equipped_manor,
        key="soul_fusion_compare_blade",
        name="灵魂融合对照佩刃",
        rarity="purple",
        extra_stats={"force": 48, "intellect": 16, "defense": 24, "agility": 14, "luck": 6},
        set_bonus={"force": 10, "agility": 7, "defense": 60},
    )

    monkeypatch.setattr(
        "gameplay.services.inventory.guest_items.inventory_random.Random", lambda: _SoulFusionFixedRng()
    )

    equipped_result = use_soul_container(equipped_manor, equipped_item, equipped_guest.id)
    plain_result = use_soul_container(plain_manor, plain_item, plain_guest.id)

    equipped_payload = (
        InventoryItem.objects.select_related("template")
        .get(pk=equipped_result["generated_item_id"])
        .template.effect_payload
    )
    plain_payload = (
        InventoryItem.objects.select_related("template")
        .get(pk=plain_result["generated_item_id"])
        .template.effect_payload
    )

    assert equipped_payload == plain_payload
    returned_gear = InventoryItem.objects.get(manor=equipped_manor, template=returned_gear_template)
    assert returned_gear.quantity == 1
    assert equipped_result["unequipped_count"] == 1


@pytest.mark.django_db
def test_use_soul_container_generated_ornament_can_be_equipped_and_unequipped(monkeypatch, django_user_model):
    manor, guest, item = _prepare_soul_container_case(
        django_user_model,
        "equip_cycle",
        guest_rarity="blue",
        archetype="civil",
        level=86,
        force=158,
        intellect=244,
        defense=168,
        agility=162,
        luck=112,
    )
    monkeypatch.setattr(
        "gameplay.services.inventory.guest_items.inventory_random.Random", lambda: _SoulFusionFixedRng()
    )

    result = use_soul_container(manor, item, guest.id)
    generated_item = InventoryItem.objects.select_related("template").get(pk=result["generated_item_id"])
    generated_stats = generated_item.template.effect_payload

    wearer_template = GuestTemplate.objects.create(
        key="soul_fusion_ornament_wearer_tpl",
        name="佩戴测试门客",
        archetype="civil",
        rarity="blue",
        base_attack=120,
        base_intellect=130,
        base_defense=100,
        base_agility=110,
        base_luck=80,
        base_hp=1400,
        default_gender="male",
        default_morality=60,
    )
    wearer = Guest.objects.create(
        manor=manor,
        template=wearer_template,
        level=50,
        force=180,
        intellect=220,
        defense_stat=170,
        agility=165,
        luck=95,
        status=GuestStatus.IDLE,
    )

    ensure_inventory_gears(manor, slot=GearSlot.ORNAMENT)
    free_gear = GearItem.objects.select_related("template").get(
        manor=manor,
        guest__isnull=True,
        template__key=generated_item.template.key,
    )

    equip_guest(free_gear, wearer)
    wearer.refresh_from_db()
    assert wearer.gear_items.filter(template__key=generated_item.template.key).exists()
    assert wearer.force == 180 + int(generated_stats.get("force", 0) or 0)
    assert wearer.intellect == 220 + int(generated_stats.get("intellect", 0) or 0)
    assert wearer.agility == 165 + int(generated_stats.get("agility", 0) or 0)
    assert wearer.luck == 95 + int(generated_stats.get("luck", 0) or 0)
    assert wearer.hp_bonus == int(generated_stats.get("hp", 0) or 0)
    assert not InventoryItem.objects.filter(
        manor=manor,
        template=generated_item.template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).exists()

    equipped_gear = wearer.gear_items.get(template__key=generated_item.template.key)
    unequip_guest_item(equipped_gear, wearer)
    wearer.refresh_from_db()
    returned_item = InventoryItem.objects.get(
        manor=manor,
        template=generated_item.template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert returned_item.quantity == 1
    assert wearer.gear_items.filter(template__key=generated_item.template.key).count() == 0
    assert wearer.force == 180
    assert wearer.intellect == 220
    assert wearer.agility == 165
    assert wearer.luck == 95
    assert wearer.hp_bonus == 0


@pytest.mark.django_db
def test_use_soul_container_generates_blue_ornament_with_civil_bias(monkeypatch, django_user_model):
    manor, guest, item = _prepare_soul_container_case(
        django_user_model,
        "civil_blue",
        guest_rarity="blue",
        archetype="civil",
        level=88,
        force=150,
        intellect=255,
        defense=162,
        agility=166,
        luck=104,
    )
    monkeypatch.setattr(
        "gameplay.services.inventory.guest_items.inventory_random.Random", lambda: _SoulFusionFixedRng()
    )

    result = use_soul_container(manor, item, guest.id)

    generated_item = InventoryItem.objects.select_related("template").get(pk=result["generated_item_id"])
    payload = generated_item.template.effect_payload

    assert generated_item.template.name == "北冥冰链"
    assert generated_item.template.rarity == "blue"
    assert 60 <= payload["force"] + payload["intellect"] + payload["agility"] + payload["luck"] <= 76
    assert 210 <= payload["hp"] <= 320
    assert payload["intellect"] > payload["force"]
    assert payload["intellect"] >= payload["agility"]
    assert all(payload[stat] > 0 for stat in ["force", "intellect", "agility", "luck"])
    assert not Guest.objects.filter(pk=guest.pk).exists()
    assert not InventoryItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
def test_use_soul_container_rejects_low_level_or_unsupported_rarity(django_user_model):
    manor, guest, item = _prepare_soul_container_case(
        django_user_model,
        "low_level",
        guest_rarity="green",
        archetype="military",
        level=29,
        force=180,
        intellect=110,
        defense=150,
        agility=140,
        luck=70,
    )

    with pytest.raises(ValueError, match="30级及以上"):
        use_soul_container(manor, item, guest.id)

    item.refresh_from_db()
    assert item.quantity == 1

    gray_template = GuestTemplate.objects.create(
        key="soul_container_gray_guest_tpl",
        name="灰色门客",
        archetype="civil",
        rarity="gray",
    )
    gray_guest = Guest.objects.create(
        manor=manor,
        template=gray_template,
        level=50,
        status=GuestStatus.IDLE,
    )

    with pytest.raises(ValueError, match="绿色、蓝色或紫色门客"):
        use_soul_container(manor, item, gray_guest.id)

    item.refresh_from_db()
    assert item.quantity == 1
