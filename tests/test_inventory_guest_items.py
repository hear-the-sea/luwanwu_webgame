import pytest

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.inventory import use_guest_rarity_upgrade_item, use_xisuidan
from gameplay.services.manor.core import ensure_manor
from guests.models import GearItem, GearSlot, GearTemplate, Guest, GuestSkill, GuestStatus, GuestTemplate, Skill
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


class _RangeSpyRng:
    def __init__(self):
        self.last_range = None

    def randint(self, a: int, b: int) -> int:
        self.last_range = (a, b)
        return a

    def choice(self, seq):
        return seq[0]


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
