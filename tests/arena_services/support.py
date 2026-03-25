from __future__ import annotations

from django.contrib.auth import get_user_model

from gameplay.models import ItemTemplate, Manor
from guests.models import Guest, GuestTemplate

User = get_user_model()


def create_guest_template(key: str) -> GuestTemplate:
    return GuestTemplate.objects.create(
        key=key,
        name=f"测试门客-{key}",
        archetype="military",
        rarity="green",
        base_attack=120,
        base_intellect=90,
        base_defense=100,
        base_agility=90,
        base_luck=50,
        base_hp=1500,
    )


def create_guest(manor: Manor, template: GuestTemplate, suffix: str) -> Guest:
    return Guest.objects.create(
        manor=manor,
        template=template,
        custom_name=f"门客{suffix}",
        level=30,
        force=180,
        intellect=120,
        defense_stat=150,
        agility=130,
    )


def fund_manor(manor: Manor, silver: int = 100000) -> None:
    manor.silver = silver
    manor.save(update_fields=["silver"])


def ensure_gladiator_item_templates() -> None:
    key_to_name = {
        "equip_jiaodoushitoukui": "角斗士头盔",
        "equip_jiaodoushixiongjia": "角斗士胸甲",
        "equip_jiaodoushizhixue": "角斗士之靴",
        "equip_jiaodoushizhichui": "角斗士之锤",
    }
    for key, name in key_to_name.items():
        ItemTemplate.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "effect_type": ItemTemplate.EffectType.TOOL,
            },
        )


def ensure_sanguoyanyi_arena_item_templates() -> None:
    key_to_name = {
        "panfeng_guest_card": "潘凤门客卡",
        "xingdaorong_guest_card": "邢道荣门客卡",
        "peerless_general_upgrade_token": "《上将的自我修养》残卷1",
        "peerless_general_upgrade_token_2": "《上将的自我修养》残卷2",
    }
    for key, name in key_to_name.items():
        ItemTemplate.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "effect_type": ItemTemplate.EffectType.TOOL,
            },
        )


def snapshot_from_guest(guest: Guest) -> dict:
    stats = guest.stat_block()
    return {
        "template_key": guest.template.key,
        "display_name": guest.display_name,
        "rarity": guest.rarity,
        "level": guest.level,
        "force": guest.force,
        "intellect": guest.intellect,
        "defense_stat": guest.defense_stat,
        "agility": guest.agility,
        "luck": guest.luck,
        "attack": stats["attack"],
        "defense": stats["defense"],
        "max_hp": guest.max_hp,
        "current_hp": guest.current_hp,
        "skill_keys": [],
    }
