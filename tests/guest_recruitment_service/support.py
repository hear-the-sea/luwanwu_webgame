from __future__ import annotations

from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestStatus, GuestTemplate


def create_guest_for_allocation_tests(django_user_model, suffix: str) -> Guest:
    user = django_user_model.objects.create_user(
        username=f"alloc_guest_{suffix}",
        password="pass123",
        email=f"alloc_guest_{suffix}@test.local",
    )
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key=f"alloc_guest_tpl_{suffix}",
        name="加点测试门客",
        archetype="civil",
        rarity="gray",
        base_attack=80,
        base_intellect=80,
        base_defense=80,
        base_agility=80,
        base_luck=50,
        base_hp=1000,
    )
    return Guest.objects.create(
        manor=manor,
        template=template,
        status=GuestStatus.IDLE,
        attribute_points=10,
        force=50,
        intellect=50,
        defense_stat=50,
        agility=50,
        allocated_force=0,
        allocated_intellect=0,
        allocated_defense=0,
        allocated_agility=0,
    )
