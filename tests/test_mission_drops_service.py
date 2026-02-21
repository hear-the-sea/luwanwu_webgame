from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import IntegrityError
from django.contrib.auth import get_user_model

from gameplay.models import InventoryItem, ItemTemplate, ResourceEvent, ResourceType
from gameplay.services.manor import ensure_manor
from gameplay.services.missions_impl.drops import (
    _get_or_create_skill_book_template,
    award_mission_drops,
    award_mission_drops_locked,
)
from guests.models import Skill, SkillBook

User = get_user_model()


@pytest.mark.django_db
def test_award_mission_drops_grants_resources_and_items():
    user = User.objects.create_user(username="mission_drop_user", password="pass123")
    manor = ensure_manor(user)
    item_template = ItemTemplate.objects.create(key="mission_drop_item", name="任务掉落道具")

    award_mission_drops(manor, {"silver": 30, "mission_drop_item": 2}, note="测试任务")

    manor.refresh_from_db()
    assert manor.silver == 530

    inv = InventoryItem.objects.get(
        manor=manor,
        template=item_template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert inv.quantity == 2

    event = ResourceEvent.objects.filter(
        manor=manor,
        resource_type=ResourceType.SILVER,
        reason=ResourceEvent.Reason.BATTLE_REWARD,
        note="测试任务",
    ).first()
    assert event is not None
    assert event.delta == 30


@pytest.mark.django_db
def test_award_mission_drops_creates_skill_book_template_when_missing():
    user = User.objects.create_user(username="mission_drop_skillbook", password="pass123")
    manor = ensure_manor(user)

    skill = Skill.objects.create(key="mission_skill", name="任务技能")
    SkillBook.objects.create(key="mission_skill_book", name="任务技能书", skill=skill)

    assert ItemTemplate.objects.filter(key="mission_skill_book").exists() is False

    award_mission_drops(manor, {"mission_skill_book": 1}, note="技能书任务")

    created_template = ItemTemplate.objects.get(key="mission_skill_book")
    assert created_template.effect_type == ItemTemplate.EffectType.SKILL_BOOK
    assert created_template.effect_payload["skill_key"] == "mission_skill"
    assert created_template.effect_payload["skill_name"] == "任务技能"

    inv = InventoryItem.objects.get(
        manor=manor,
        template=created_template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert inv.quantity == 1


@pytest.mark.django_db
def test_award_mission_drops_locked_requires_atomic(monkeypatch):
    user = User.objects.create_user(username="mission_drop_locked", password="pass123")
    manor = ensure_manor(user)
    monkeypatch.setattr(
        "gameplay.services.missions_impl.drops.transaction.get_connection",
        lambda: SimpleNamespace(in_atomic_block=False),
    )

    with pytest.raises(RuntimeError, match="must be called inside transaction.atomic"):
        award_mission_drops_locked(manor, {"silver": 1}, note="locked契约")


@pytest.mark.django_db
def test_get_or_create_skill_book_template_recovers_from_integrity_error(monkeypatch):
    skill = Skill.objects.create(key="mission_skill_2", name="任务技能2")
    book = SkillBook.objects.create(key="mission_skill_book_2", name="任务技能书2", skill=skill)

    existing = ItemTemplate.objects.create(
        key="mission_skill_book_2",
        name="任务技能书2",
        effect_type=ItemTemplate.EffectType.SKILL_BOOK,
        effect_payload={"skill_key": skill.key, "skill_name": skill.name},
    )

    get_or_create_mock = Mock(side_effect=IntegrityError("duplicate key"))
    monkeypatch.setattr(
        "gameplay.services.missions_impl.drops.ItemTemplate.objects.get_or_create",
        get_or_create_mock,
    )

    resolved = _get_or_create_skill_book_template("mission_skill_book_2", book)
    assert resolved.pk == existing.pk
