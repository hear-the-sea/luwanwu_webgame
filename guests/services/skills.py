from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from core.config import GUEST

from ..models import Guest, GuestSkill, GuestStatus, Skill

if TYPE_CHECKING:
    from gameplay.models import InventoryItem

MAX_GUEST_SKILL_SLOTS = int(GUEST.MAX_SKILL_SLOTS)


def learn_guest_skill(guest: Guest, skill: Skill, inventory_item: "InventoryItem") -> None:
    from gameplay.models import InventoryItem
    from gameplay.services.inventory.core import consume_inventory_item_locked

    with transaction.atomic():
        locked_guest = Guest.objects.select_for_update().get(pk=guest.pk)
        if locked_guest.status != GuestStatus.IDLE:
            raise ValueError(f"{locked_guest.display_name} 当前非空闲状态，无法学习技能")

        if locked_guest.guest_skills.count() >= MAX_GUEST_SKILL_SLOTS:
            raise ValueError("技能位已满")

        if locked_guest.guest_skills.filter(skill=skill).exists():
            raise ValueError(f"{locked_guest.display_name} 已掌握 {skill.name}")

        locked_item = InventoryItem.objects.select_for_update().filter(pk=inventory_item.pk).first()
        if not locked_item or locked_item.quantity < 1:
            raise ValueError("技能书数量不足")

        GuestSkill.objects.create(
            guest=locked_guest,
            skill=skill,
            source=GuestSkill.Source.BOOK,
        )
        consume_inventory_item_locked(locked_item)


def forget_guest_skill(guest: Guest, guest_skill_id: int) -> str:
    with transaction.atomic():
        locked_guest = Guest.objects.select_for_update().select_related("template").filter(pk=guest.pk).first()
        if locked_guest is None:
            raise ValueError("门客不存在")
        if locked_guest.status != GuestStatus.IDLE:
            raise ValueError(f"{locked_guest.display_name} 当前非空闲状态，无法遗忘技能")

        locked_guest_skill = locked_guest.guest_skills.select_related("skill").filter(pk=guest_skill_id).first()
        if locked_guest_skill is None:
            raise ValueError("未找到要遗忘的技能")

        skill_name = locked_guest_skill.skill.name
        locked_guest_skill.delete()
        return skill_name
