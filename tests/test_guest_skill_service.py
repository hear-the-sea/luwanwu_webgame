from __future__ import annotations

from itertools import count

import pytest

from core.exceptions import GuestNotFoundError, GuestNotIdleError, GuestNotRequirementError, GuestSkillNotFoundError
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestSkill, GuestStatus, GuestTemplate, Skill
from guests.services.skills import forget_guest_skill, learn_guest_skill

_COUNTER = count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}_{next(_COUNTER)}"


def _create_guest(manor, **overrides) -> Guest:
    template = GuestTemplate.objects.create(
        key=_unique("skill_service_guest_tpl"),
        name="技能服务门客",
        rarity="green",
        archetype="military",
    )
    payload = {
        "manor": manor,
        "template": template,
        "level": 10,
        "force": 100,
        "intellect": 90,
        "defense_stat": 80,
        "agility": 85,
        "status": GuestStatus.IDLE,
    }
    payload.update(overrides)
    return Guest.objects.create(**payload)


def _create_skill_book_item(manor, **skill_overrides) -> tuple[Skill, InventoryItem]:
    payload = {
        "key": _unique("skill_service_skill"),
        "name": "技能服务技能",
        "rarity": "green",
    }
    payload.update(skill_overrides)
    skill = Skill.objects.create(**payload)
    template = ItemTemplate.objects.create(
        key=_unique("skill_service_book"),
        name="技能服务技能书",
        effect_type=ItemTemplate.EffectType.SKILL_BOOK,
        effect_payload={"skill_key": skill.key},
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=2,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    return skill, item


@pytest.mark.django_db
def test_learn_guest_skill_creates_guest_skill_and_consumes_book(django_user_model):
    user = django_user_model.objects.create_user(username=_unique("skill_service_user"), password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor)
    skill, item = _create_skill_book_item(manor)

    learn_guest_skill(guest, skill, item)

    item.refresh_from_db(fields=["quantity"])
    assert item.quantity == 1
    assert GuestSkill.objects.filter(guest=guest, skill=skill, source=GuestSkill.Source.BOOK).exists()


@pytest.mark.django_db
def test_learn_guest_skill_rejects_busy_guest_without_consuming_book(django_user_model):
    user = django_user_model.objects.create_user(username=_unique("skill_service_busy_user"), password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor)
    guest.status = GuestStatus.WORKING
    guest.save(update_fields=["status"])
    skill, item = _create_skill_book_item(manor)

    with pytest.raises(GuestNotIdleError, match="非空闲状态"):
        learn_guest_skill(guest, skill, item)

    item.refresh_from_db(fields=["quantity"])
    assert item.quantity == 2
    assert not GuestSkill.objects.filter(guest=guest, skill=skill).exists()


@pytest.mark.django_db
def test_learn_guest_skill_rejects_low_level_without_consuming_book(django_user_model):
    user = django_user_model.objects.create_user(username=_unique("skill_service_level_user"), password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor, level=9)
    skill, item = _create_skill_book_item(manor, required_level=12)

    with pytest.raises(GuestNotRequirementError, match="等级不足"):
        learn_guest_skill(guest, skill, item)

    item.refresh_from_db(fields=["quantity"])
    assert item.quantity == 2
    assert not GuestSkill.objects.filter(guest=guest, skill=skill).exists()


@pytest.mark.django_db
def test_learn_guest_skill_rejects_low_attribute_without_consuming_book(django_user_model):
    user = django_user_model.objects.create_user(username=_unique("skill_service_attr_user"), password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor, agility=84)
    skill, item = _create_skill_book_item(manor, required_agility=100)

    with pytest.raises(GuestNotRequirementError, match="敏捷不足"):
        learn_guest_skill(guest, skill, item)

    item.refresh_from_db(fields=["quantity"])
    assert item.quantity == 2
    assert not GuestSkill.objects.filter(guest=guest, skill=skill).exists()


@pytest.mark.django_db
def test_forget_guest_skill_deletes_skill_record(django_user_model):
    user = django_user_model.objects.create_user(username=_unique("skill_service_forget_user"), password="pass123")
    manor = ensure_manor(user)
    guest = _create_guest(manor)
    skill = Skill.objects.create(key=_unique("skill_service_forget_skill"), name="遗忘服务技能", rarity="green")
    guest_skill = GuestSkill.objects.create(guest=guest, skill=skill)

    skill_name = forget_guest_skill(guest, guest_skill.id)

    assert skill_name == skill.name
    assert not GuestSkill.objects.filter(pk=guest_skill.pk).exists()


@pytest.mark.django_db
def test_forget_guest_skill_rejects_missing_guest(django_user_model):
    user = django_user_model.objects.create_user(
        username=_unique("skill_service_missing_guest_user"), password="pass123"
    )
    manor = ensure_manor(user)
    guest = _create_guest(manor)
    guest_id = guest.pk
    guest.delete()

    with pytest.raises(GuestNotFoundError, match="门客不存在"):
        forget_guest_skill(guest, 999999)

    assert not Guest.objects.filter(pk=guest_id).exists()


@pytest.mark.django_db
def test_forget_guest_skill_rejects_missing_skill_record(django_user_model):
    user = django_user_model.objects.create_user(
        username=_unique("skill_service_missing_skill_user"), password="pass123"
    )
    manor = ensure_manor(user)
    guest = _create_guest(manor)

    with pytest.raises(GuestSkillNotFoundError, match="未找到要遗忘的技能"):
        forget_guest_skill(guest, 999999)
