from gameplay.models import InventoryItem, ItemTemplate
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
