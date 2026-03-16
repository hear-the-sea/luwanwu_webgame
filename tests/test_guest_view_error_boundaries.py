from __future__ import annotations

from itertools import count

import pytest
from django.contrib.messages import get_messages
from django.db import DatabaseError
from django.test import Client
from django.urls import reverse

from core.exceptions import GameError
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from guests.models import (
    GearItem,
    GearSlot,
    GearTemplate,
    Guest,
    GuestSkill,
    GuestTemplate,
    RecruitmentCandidate,
    RecruitmentPool,
    Skill,
)

_SEQ = count()


def _unique(prefix: str) -> str:
    return f"{prefix}_{next(_SEQ)}"


def _ajax_headers() -> dict[str, str]:
    return {
        "HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
        "HTTP_ACCEPT": "application/json",
    }


def _messages(response) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def _login_client(django_user_model, *, prefix: str = "guest_view_boundary"):
    username = _unique(prefix)
    user = django_user_model.objects.create_user(username=username, password="pass123")
    manor = ensure_manor(user)
    client = Client()
    assert client.login(username=username, password="pass123")
    return client, manor


def _create_guest(manor, *, prefix: str = "guest") -> Guest:
    template = GuestTemplate.objects.create(
        key=_unique(f"{prefix}_tpl"),
        name=f"{prefix}模板",
        archetype="military",
        rarity="green",
    )
    guest = Guest.objects.create(
        manor=manor,
        template=template,
        custom_name=f"{prefix}门客",
        level=10,
        force=120,
        intellect=90,
        defense_stat=100,
        agility=95,
        current_hp=1,
        attribute_points=5,
    )
    guest.current_hp = guest.max_hp
    guest.save(update_fields=["current_hp"])
    return guest


def _create_gear(manor, *, guest=None, slot: str = GearSlot.WEAPON) -> GearItem:
    template = GearTemplate.objects.create(
        key=_unique("gear_tpl"),
        name="测试装备",
        slot=slot,
        rarity="green",
    )
    return GearItem.objects.create(manor=manor, template=template, guest=guest)


def _create_item(manor, *, effect_type: str, effect_payload: dict, prefix: str) -> InventoryItem:
    template = ItemTemplate.objects.create(
        key=_unique(prefix),
        name=f"{prefix}道具",
        effect_type=effect_type,
        effect_payload=effect_payload,
        is_usable=True,
    )
    return InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )


def _create_pool(prefix: str = "pool") -> RecruitmentPool:
    return RecruitmentPool.objects.create(
        key=_unique(prefix),
        name=f"{prefix}卡池",
        cost={},
        cooldown_seconds=0,
        draw_count=1,
    )


def _create_candidate(manor, *, prefix: str = "candidate") -> RecruitmentCandidate:
    pool = _create_pool(f"{prefix}_pool")
    template = GuestTemplate.objects.create(
        key=_unique(f"{prefix}_tpl"),
        name=f"{prefix}模板",
        archetype="military",
        rarity="green",
    )
    return RecruitmentCandidate.objects.create(
        manor=manor,
        pool=pool,
        template=template,
        display_name=f"{prefix}候选",
        rarity=template.rarity,
        archetype=template.archetype,
    )


def _create_skill_book(manor, *, prefix: str = "skill_book") -> tuple[Skill, InventoryItem]:
    skill = Skill.objects.create(
        key=_unique(f"{prefix}_skill"),
        name=f"{prefix}技能",
        rarity="green",
    )
    item = _create_item(
        manor,
        effect_type=ItemTemplate.EffectType.SKILL_BOOK,
        effect_payload={"skill_key": skill.key},
        prefix=prefix,
    )
    return skill, item


def _stub_recruit_lock(monkeypatch) -> None:
    monkeypatch.setattr("guests.views.recruit._acquire_recruit_action_lock", lambda *_a, **_k: (True, "lock", "token"))
    monkeypatch.setattr("guests.views.recruit._release_recruit_action_lock", lambda *_a, **_k: None)


def _stub_equip_form(monkeypatch, guest: Guest, gear: GearItem) -> None:
    class DummyEquipForm:
        cleaned_data = {"guest": guest, "gear": gear}

        def __init__(self, *_args, **_kwargs):
            pass

        def is_valid(self) -> bool:
            return True

    monkeypatch.setattr("guests.views.equipment.EquipForm", DummyEquipForm)
    monkeypatch.setattr("guests.services.ensure_inventory_gears", lambda *_a, **_k: None)


@pytest.mark.django_db
def test_equip_view_game_error_shows_business_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="equip_game")
    guest = _create_guest(manor, prefix="equip_game")
    gear = _create_gear(manor)
    _stub_equip_form(monkeypatch, guest, gear)

    monkeypatch.setattr("guests.services.equip_guest", lambda *_a, **_k: (_ for _ in ()).throw(GameError("装备受限")))

    response = client.post(
        reverse("guests:equip"),
        {"guest": str(guest.pk), "gear": str(gear.pk), "slot": gear.template.slot},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "装备受限" in _messages(response)


@pytest.mark.django_db
def test_equip_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="equip_db")
    guest = _create_guest(manor, prefix="equip_db")
    gear = _create_gear(manor)
    _stub_equip_form(monkeypatch, guest, gear)

    monkeypatch.setattr(
        "guests.services.equip_guest",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("guests:equip"),
        {"guest": str(guest.pk), "gear": str(gear.pk), "slot": gear.template.slot},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_equip_view_runtime_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="equip_runtime")
    guest = _create_guest(manor, prefix="equip_runtime")
    gear = _create_gear(manor)
    _stub_equip_form(monkeypatch, guest, gear)

    monkeypatch.setattr("guests.services.equip_guest", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))

    response = client.post(
        reverse("guests:equip"),
        {"guest": str(guest.pk), "gear": str(gear.pk), "slot": gear.template.slot},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_equip_view_cache_invalidation_failure_does_not_hide_success(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="equip_cache")
    guest = _create_guest(manor, prefix="equip_cache")
    gear = _create_gear(manor)
    _stub_equip_form(monkeypatch, guest, gear)

    monkeypatch.setattr("guests.services.equip_guest", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "guests.views.equipment.cache.delete_many",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cache down")),
    )

    response = client.post(
        reverse("guests:equip"),
        {"guest": str(guest.pk), "gear": str(gear.pk), "slot": gear.template.slot},
    )

    assert response.status_code == 302
    assert response.url == reverse("guests:detail", args=[guest.pk])
    assert any("已装备" in m for m in _messages(response))


@pytest.mark.django_db
def test_unequip_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="unequip_db")
    guest = _create_guest(manor, prefix="unequip_db")
    gear = _create_gear(manor, guest=guest)

    monkeypatch.setattr(
        "guests.services.unequip_guest_item",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:unequip"), {"guest": str(guest.pk), "gear": [str(gear.pk)]})

    assert response.status_code == 302
    assert response.url == reverse("guests:roster")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_unequip_view_runtime_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="unequip_runtime")
    guest = _create_guest(manor, prefix="unequip_runtime")
    gear = _create_gear(manor, guest=guest)

    monkeypatch.setattr(
        "guests.services.unequip_guest_item",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(reverse("guests:unequip"), {"guest": str(guest.pk), "gear": [str(gear.pk)]})

    assert response.status_code == 302
    assert response.url == reverse("guests:roster")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_unequip_view_cache_invalidation_failure_does_not_hide_success(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="unequip_cache")
    guest = _create_guest(manor, prefix="unequip_cache")
    gear = _create_gear(manor, guest=guest)

    monkeypatch.setattr("guests.services.unequip_guest_item", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "guests.views.equipment.cache.delete_many",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cache down")),
    )

    response = client.post(reverse("guests:unequip"), {"guest": str(guest.pk), "gear": [str(gear.pk)]})

    assert response.status_code == 302
    assert response.url == reverse("guests:roster")
    assert any("卸下 1 件装备" in m for m in _messages(response))


@pytest.mark.django_db
def test_use_medicine_item_view_game_error_returns_business_json(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="medicine_game")
    guest = _create_guest(manor, prefix="medicine_game")
    guest.current_hp = max(1, guest.max_hp - 50)
    guest.save(update_fields=["current_hp"])
    item = _create_item(
        manor,
        effect_type=ItemTemplate.EffectType.MEDICINE,
        effect_payload={"hp": 100},
        prefix="medicine_game",
    )

    monkeypatch.setattr(
        "guests.views.items.use_medicine_item_for_guest",
        lambda *_a, **_k: (_ for _ in ()).throw(GameError("无法用药")),
    )

    response = client.post(
        reverse("guests:use_medicine_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        **_ajax_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "无法用药"


@pytest.mark.django_db
def test_use_medicine_item_view_database_error_returns_generic_json(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="medicine_db")
    guest = _create_guest(manor, prefix="medicine_db")
    guest.current_hp = max(1, guest.max_hp - 50)
    guest.save(update_fields=["current_hp"])
    item = _create_item(
        manor,
        effect_type=ItemTemplate.EffectType.MEDICINE,
        effect_payload={"hp": 100},
        prefix="medicine_db",
    )

    monkeypatch.setattr(
        "guests.views.items.use_medicine_item_for_guest",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("guests:use_medicine_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        **_ajax_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "操作失败，请稍后重试"


@pytest.mark.django_db
def test_use_medicine_item_view_runtime_error_returns_generic_json(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="medicine_runtime")
    guest = _create_guest(manor, prefix="medicine_runtime")
    item = _create_item(
        manor,
        effect_type=ItemTemplate.EffectType.MEDICINE,
        effect_payload={"hp": 100},
        prefix="medicine_runtime",
    )

    monkeypatch.setattr(
        "guests.views.items.use_medicine_item_for_guest",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(
        reverse("guests:use_medicine_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        **_ajax_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "操作失败，请稍后重试"


@pytest.mark.django_db
def test_recruit_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, _manor = _login_client(django_user_model, prefix="recruit_db")
    pool = _create_pool("recruit_db")
    _stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.start_guest_recruitment",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:recruit"), {"pool": str(pool.pk)})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_recruit_view_runtime_error_degrades_with_message(django_user_model, monkeypatch):
    client, _manor = _login_client(django_user_model, prefix="recruit_runtime")
    pool = _create_pool("recruit_runtime")
    _stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.start_guest_recruitment",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(reverse("guests:recruit"), {"pool": str(pool.pk)})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_accept_candidate_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="accept_db")
    candidate = _create_candidate(manor, prefix="accept_db")
    _stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.bulk_finalize_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("guests:candidate_accept"),
        {"candidate_ids": [str(candidate.pk)], "action": "accept"},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_accept_candidate_view_runtime_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="accept_runtime")
    candidate = _create_candidate(manor, prefix="accept_runtime")
    _stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.bulk_finalize_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(
        reverse("guests:candidate_accept"),
        {"candidate_ids": [str(candidate.pk)], "action": "accept"},
    )

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_use_magnifying_glass_view_game_error_returns_business_json(django_user_model, monkeypatch):
    client, _manor = _login_client(django_user_model, prefix="magnify_game")
    _stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.use_magnifying_glass_for_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(GameError("放大镜失效")),
    )

    response = client.post(
        reverse("guests:use_magnifying_glass"),
        {"item_id": "1"},
        **_ajax_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "放大镜失效"


@pytest.mark.django_db
def test_use_magnifying_glass_view_database_error_returns_generic_json(django_user_model, monkeypatch):
    client, _manor = _login_client(django_user_model, prefix="magnify_db")
    _stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.use_magnifying_glass_for_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("guests:use_magnifying_glass"),
        {"item_id": "1"},
        **_ajax_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "操作失败，请稍后重试"


@pytest.mark.django_db
def test_use_magnifying_glass_view_runtime_error_returns_generic_json(django_user_model, monkeypatch):
    client, _manor = _login_client(django_user_model, prefix="magnify_runtime")
    _stub_recruit_lock(monkeypatch)

    monkeypatch.setattr(
        "guests.views.recruit.use_magnifying_glass_for_candidates",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(
        reverse("guests:use_magnifying_glass"),
        {"item_id": "1"},
        **_ajax_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "操作失败，请稍后重试"


@pytest.mark.django_db
def test_learn_skill_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="learn_db")
    guest = _create_guest(manor, prefix="learn_db")
    _skill, item = _create_skill_book(manor, prefix="learn_db")

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_learning",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:learn_skill", args=[guest.pk]), {"item_id": str(item.pk)})

    assert response.status_code == 302
    assert response.url == reverse("guests:detail", args=[guest.pk])
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_learn_skill_view_runtime_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="learn_runtime")
    guest = _create_guest(manor, prefix="learn_runtime")
    _skill, item = _create_skill_book(manor, prefix="learn_runtime")

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_learning",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(reverse("guests:learn_skill", args=[guest.pk]), {"item_id": str(item.pk)})

    assert response.status_code == 302
    assert response.url == reverse("guests:detail", args=[guest.pk])
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_forget_skill_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="forget_db")
    guest = _create_guest(manor, prefix="forget_db")
    skill = Skill.objects.create(key=_unique("forget_db_skill"), name="遗忘技能", rarity="green")
    guest_skill = GuestSkill.objects.create(guest=guest, skill=skill)

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_forget",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(reverse("guests:forget_skill", args=[guest.pk]), {"guest_skill_id": str(guest_skill.pk)})

    assert response.status_code == 302
    assert response.url == reverse("guests:detail", args=[guest.pk])
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_forget_skill_view_runtime_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="forget_runtime")
    guest = _create_guest(manor, prefix="forget_runtime")
    skill = Skill.objects.create(key=_unique("forget_runtime_skill"), name="遗忘技能", rarity="green")
    guest_skill = GuestSkill.objects.create(guest=guest, skill=skill)

    monkeypatch.setattr(
        "guests.views.skills._persist_skill_forget",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(reverse("guests:forget_skill", args=[guest.pk]), {"guest_skill_id": str(guest_skill.pk)})

    assert response.status_code == 302
    assert response.url == reverse("guests:detail", args=[guest.pk])
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_train_view_database_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="train_db")
    guest = _create_guest(manor, prefix="train_db")

    monkeypatch.setattr(
        "guests.views.training.train_guest", lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down"))
    )

    response = client.post(reverse("guests:train"), {"guest": str(guest.pk), "levels": "1"})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_train_view_runtime_error_degrades_with_message(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="train_runtime")
    guest = _create_guest(manor, prefix="train_runtime")

    monkeypatch.setattr(
        "guests.views.training.train_guest", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    response = client.post(reverse("guests:train"), {"guest": str(guest.pk), "levels": "1"})

    assert response.status_code == 302
    assert response.url == reverse("gameplay:recruitment_hall")
    assert "操作失败，请稍后重试" in _messages(response)


@pytest.mark.django_db
def test_use_experience_item_view_database_error_returns_generic_json(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="exp_db")
    guest = _create_guest(manor, prefix="exp_db")
    item = _create_item(
        manor,
        effect_type=ItemTemplate.EffectType.EXPERIENCE_ITEM,
        effect_payload={"time": 3600},
        prefix="exp_db",
    )

    monkeypatch.setattr(
        "guests.views.training.use_experience_item_for_guest",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("guests:use_exp_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        **_ajax_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "操作失败，请稍后重试"


@pytest.mark.django_db
def test_use_experience_item_view_runtime_error_returns_generic_json(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="exp_runtime")
    guest = _create_guest(manor, prefix="exp_runtime")
    item = _create_item(
        manor,
        effect_type=ItemTemplate.EffectType.EXPERIENCE_ITEM,
        effect_payload={"time": 3600},
        prefix="exp_runtime",
    )

    monkeypatch.setattr(
        "guests.views.training.use_experience_item_for_guest",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(
        reverse("guests:use_exp_item", args=[guest.pk]),
        {"item_id": str(item.pk)},
        **_ajax_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "操作失败，请稍后重试"


@pytest.mark.django_db
def test_allocate_points_view_value_error_returns_business_json(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="allocate_value")
    guest = _create_guest(manor, prefix="allocate_value")

    monkeypatch.setattr(
        "guests.views.training.allocate_attribute_points",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("加点失败")),
    )

    response = client.post(
        reverse("guests:allocate_points", args=[guest.pk]),
        {"guest": str(guest.pk), "attribute": "force", "points": "1"},
        **_ajax_headers(),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "加点失败"


@pytest.mark.django_db
def test_allocate_points_view_database_error_returns_generic_json(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="allocate_db")
    guest = _create_guest(manor, prefix="allocate_db")

    monkeypatch.setattr(
        "guests.views.training.allocate_attribute_points",
        lambda *_a, **_k: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    response = client.post(
        reverse("guests:allocate_points", args=[guest.pk]),
        {"guest": str(guest.pk), "attribute": "force", "points": "1"},
        **_ajax_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "操作失败，请稍后重试"


@pytest.mark.django_db
def test_allocate_points_view_runtime_error_returns_generic_json(django_user_model, monkeypatch):
    client, manor = _login_client(django_user_model, prefix="allocate_runtime")
    guest = _create_guest(manor, prefix="allocate_runtime")

    monkeypatch.setattr(
        "guests.views.training.allocate_attribute_points",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    response = client.post(
        reverse("guests:allocate_points", args=[guest.pk]),
        {"guest": str(guest.pk), "attribute": "force", "points": "1"},
        **_ajax_headers(),
    )

    assert response.status_code == 500
    assert response.json()["error"] == "操作失败，请稍后重试"
