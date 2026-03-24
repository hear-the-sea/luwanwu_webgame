from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from django.db import transaction

from core.config import GUEST
from core.exceptions import (
    GuestItemOwnershipError,
    GuestNotFoundError,
    GuestNotIdleError,
    GuestNotRequirementError,
    GuestSkillAlreadyLearnedError,
    GuestSkillNotFoundError,
    InsufficientStockError,
    SkillSlotFullError,
)

from ..models import Guest, GuestSkill, GuestStatus, Skill

if TYPE_CHECKING:
    from gameplay.models import InventoryItem

MAX_GUEST_SKILL_SLOTS = int(GUEST.MAX_SKILL_SLOTS)
SKILL_REQUIREMENT_FIELDS = (
    ("level", "required_level", "level", "等级"),
    ("force", "required_force", "force", "武力"),
    ("intellect", "required_intellect", "intellect", "智力"),
    ("defense", "required_defense", "defense_stat", "防御"),
    ("agility", "required_agility", "agility", "敏捷"),
)


def _iter_skill_requirements(guest: Guest | None, skill: Skill) -> Iterator[tuple[str, str, int, int | None]]:
    for requirement_type, skill_field, guest_field, label in SKILL_REQUIREMENT_FIELDS:
        required = int(getattr(skill, skill_field, 0) or 0)
        if required <= 0:
            continue
        actual = None if guest is None else int(getattr(guest, guest_field, 0) or 0)
        yield requirement_type, label, required, actual


def collect_skill_requirements(skill: Skill | None) -> list[str]:
    if skill is None:
        return []
    return [f"{label}需 ≥ {required}" for _kind, label, required, _actual in _iter_skill_requirements(None, skill)]


def collect_unmet_skill_requirements(guest: Guest, skill: Skill | None) -> list[str]:
    if skill is None:
        return []
    unmet: list[str] = []
    for _kind, label, required, actual in _iter_skill_requirements(guest, skill):
        if actual is not None and actual < required:
            unmet.append(f"{label}需 ≥ {required}")
    return unmet


def assert_guest_meets_skill_requirements(guest: Guest, skill: Skill) -> None:
    for requirement_type, _label, required, actual in _iter_skill_requirements(guest, skill):
        if actual is not None and actual < required:
            raise GuestNotRequirementError(guest, requirement_type, required, actual)


def learn_guest_skill(guest: Guest, skill: Skill, inventory_item: "InventoryItem") -> None:
    from gameplay.models import InventoryItem
    from gameplay.services.inventory.core import consume_inventory_item_locked

    with transaction.atomic():
        locked_guest = Guest.objects.select_for_update().filter(pk=guest.pk).first()
        if locked_guest is None:
            raise GuestNotFoundError()
        if locked_guest.status != GuestStatus.IDLE:
            raise GuestNotIdleError(locked_guest, message=f"{locked_guest.display_name} 当前非空闲状态，无法学习技能")

        if locked_guest.guest_skills.count() >= MAX_GUEST_SKILL_SLOTS:
            raise SkillSlotFullError("技能位已满")

        if locked_guest.guest_skills.filter(skill=skill).exists():
            raise GuestSkillAlreadyLearnedError(locked_guest, skill)

        assert_guest_meets_skill_requirements(locked_guest, skill)

        locked_item = InventoryItem.objects.select_for_update().filter(pk=inventory_item.pk).first()
        if locked_item is None:
            raise GuestItemOwnershipError(message="技能书不存在或不属于您的庄园")
        if locked_item.quantity < 1:
            raise InsufficientStockError(locked_item.template.name, 1, locked_item.quantity)

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
            raise GuestNotFoundError()
        if locked_guest.status != GuestStatus.IDLE:
            raise GuestNotIdleError(locked_guest, message=f"{locked_guest.display_name} 当前非空闲状态，无法遗忘技能")

        locked_guest_skill = locked_guest.guest_skills.select_related("skill").filter(pk=guest_skill_id).first()
        if locked_guest_skill is None:
            raise GuestSkillNotFoundError("未找到要遗忘的技能")

        skill_name = locked_guest_skill.skill.name
        locked_guest_skill.delete()
        return skill_name
