from __future__ import annotations

import builtins
from datetime import timedelta

import pytest
from django.utils import timezone

from battle.models import TroopTemplate
from core.exceptions import TroopRecruitmentAlreadyInProgressError, TroopRecruitmentError
from gameplay.models import InventoryItem, ItemTemplate, PlayerTroop, TroopRecruitment
from gameplay.services.manor.core import ensure_manor
from gameplay.services.recruitment import lifecycle as troop_recruitment_lifecycle_service
from gameplay.services.recruitment.recruitment import (
    _consume_equipment_for_recruitment,
    finalize_troop_recruitment,
    start_troop_recruitment,
)


@pytest.fixture
def recruit_manor(django_user_model):
    user = django_user_model.objects.create_user(username="troop_recruit_user", password="pass123")
    manor = ensure_manor(user)
    manor.retainer_count = 20
    manor.save(update_fields=["retainer_count"])
    return manor


def _create_tool_template(key: str, name: str) -> ItemTemplate:
    template, _ = ItemTemplate.objects.get_or_create(
        key=key,
        defaults={
            "name": name,
            "effect_type": ItemTemplate.EffectType.TOOL,
            "effect_payload": {},
            "is_usable": True,
        },
    )
    return template


def _set_inventory(manor, template: ItemTemplate, quantity: int) -> None:
    InventoryItem.objects.update_or_create(
        manor=manor,
        template=template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": quantity},
    )


@pytest.mark.django_db
def test_consume_equipment_batch_update_and_delete(recruit_manor):
    manor = recruit_manor
    spear = _create_tool_template("equip_spear", "长枪")
    shield = _create_tool_template("equip_shield", "盾牌")
    _set_inventory(manor, spear, 5)
    _set_inventory(manor, shield, 2)

    costs = _consume_equipment_for_recruitment(manor, ["equip_spear", "equip_shield"], quantity=2)

    assert costs == {"equip_spear": 2, "equip_shield": 2}
    spear_item = InventoryItem.objects.get(
        manor=manor,
        template=spear,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert spear_item.quantity == 3
    assert not InventoryItem.objects.filter(
        manor=manor,
        template=shield,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).exists()


@pytest.mark.django_db
def test_consume_equipment_insufficient_keeps_inventory_unchanged(recruit_manor):
    manor = recruit_manor
    spear = _create_tool_template("equip_spear_short", "短枪")
    shield = _create_tool_template("equip_shield_short", "短盾")
    _set_inventory(manor, spear, 5)
    _set_inventory(manor, shield, 1)

    with pytest.raises(TroopRecruitmentError, match="装备不足: equip_shield_short"):
        _consume_equipment_for_recruitment(manor, ["equip_spear_short", "equip_shield_short"], quantity=2)

    spear_item = InventoryItem.objects.get(
        manor=manor,
        template=spear,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    shield_item = InventoryItem.objects.get(
        manor=manor,
        template=shield,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert spear_item.quantity == 5
    assert shield_item.quantity == 1


@pytest.mark.django_db
def test_start_troop_recruitment_deducts_inventory_and_retainers(monkeypatch, recruit_manor):
    manor = recruit_manor
    spear = _create_tool_template("equip_spear_recruit", "募兵长枪")
    shield = _create_tool_template("equip_shield_recruit", "募兵盾牌")
    _set_inventory(manor, spear, 4)
    _set_inventory(manor, shield, 2)

    troop_data = {
        "name": "长枪兵",
        "recruit": {
            "equipment": ["equip_spear_recruit", "equip_shield_recruit"],
            "retainer_cost": 2,
            "base_duration": 60,
        },
    }

    schedule_calls = []

    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment._validate_start_recruitment_inputs",
        lambda current_manor, troop_key, quantity: troop_data,
    )
    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment._schedule_recruitment_completion",
        lambda recruitment, eta_seconds: schedule_calls.append((recruitment.id, eta_seconds)),
    )

    recruitment = start_troop_recruitment(manor, "spearman", quantity=2)

    manor.refresh_from_db()
    assert manor.retainer_count == 16
    assert recruitment.retainer_cost == 4
    assert recruitment.equipment_costs == {"equip_spear_recruit": 2, "equip_shield_recruit": 2}
    assert recruitment.status == TroopRecruitment.Status.RECRUITING
    assert schedule_calls == [(recruitment.id, recruitment.actual_duration)]

    spear_item = InventoryItem.objects.get(
        manor=manor,
        template=spear,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert spear_item.quantity == 2
    assert not InventoryItem.objects.filter(
        manor=manor,
        template=shield,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).exists()


@pytest.mark.django_db
def test_start_troop_recruitment_rollback_on_insufficient_equipment(monkeypatch, recruit_manor):
    manor = recruit_manor
    spear = _create_tool_template("equip_spear_rollback", "回滚长枪")
    shield = _create_tool_template("equip_shield_rollback", "回滚盾牌")
    _set_inventory(manor, spear, 3)
    _set_inventory(manor, shield, 1)

    troop_data = {
        "name": "回滚兵",
        "recruit": {
            "equipment": ["equip_spear_rollback", "equip_shield_rollback"],
            "retainer_cost": 3,
            "base_duration": 90,
        },
    }

    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment._validate_start_recruitment_inputs",
        lambda current_manor, troop_key, quantity: troop_data,
    )

    with pytest.raises(TroopRecruitmentError, match="装备不足: equip_shield_rollback"):
        start_troop_recruitment(manor, "rollback_unit", quantity=2)

    manor.refresh_from_db()
    assert manor.retainer_count == 20
    assert TroopRecruitment.objects.filter(manor=manor).count() == 0

    spear_item = InventoryItem.objects.get(
        manor=manor,
        template=spear,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    shield_item = InventoryItem.objects.get(
        manor=manor,
        template=shield,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    assert spear_item.quantity == 3
    assert shield_item.quantity == 1


@pytest.mark.django_db
def test_start_troop_recruitment_rechecks_active_queue_after_lock(monkeypatch, recruit_manor):
    manor = recruit_manor
    stale_manor = type(manor).objects.get(pk=manor.pk)

    troop_data = {
        "name": "长枪兵",
        "recruit": {
            "equipment": [],
            "retainer_cost": 2,
            "base_duration": 60,
        },
    }

    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment._validate_start_recruitment_inputs",
        lambda current_manor, troop_key, quantity: troop_data,
    )
    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment._schedule_recruitment_completion",
        lambda recruitment, eta_seconds: None,
    )

    TroopRecruitment.objects.create(
        manor=manor,
        troop_key="existing_spearman",
        troop_name="现有长枪兵",
        quantity=1,
        equipment_costs={},
        retainer_cost=1,
        base_duration=60,
        actual_duration=60,
        complete_at=timezone.now() + timedelta(minutes=1),
    )

    with pytest.raises(TroopRecruitmentAlreadyInProgressError, match="已有募兵正在进行中"):
        start_troop_recruitment(stale_manor, "spearman", quantity=1)

    manor.refresh_from_db()
    assert manor.retainer_count == 20
    assert TroopRecruitment.objects.filter(manor=manor, status=TroopRecruitment.Status.RECRUITING).count() == 1


@pytest.mark.django_db
def test_start_troop_recruitment_uses_locked_retainer_count_instead_of_stale_object(monkeypatch, recruit_manor):
    manor = recruit_manor
    stale_manor = type(manor).objects.get(pk=manor.pk)
    type(manor).objects.filter(pk=manor.pk).update(retainer_count=1)

    troop_data = {
        "name": "刀盾兵",
        "recruit": {
            "equipment": [],
            "retainer_cost": 2,
            "base_duration": 60,
        },
    }

    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment._validate_start_recruitment_inputs",
        lambda current_manor, troop_key, quantity: troop_data,
    )
    monkeypatch.setattr(
        "gameplay.services.recruitment.recruitment._schedule_recruitment_completion",
        lambda recruitment, eta_seconds: None,
    )

    with pytest.raises(TroopRecruitmentError, match="家丁不足，需要2"):
        start_troop_recruitment(stale_manor, "shield_bearer", quantity=1)

    manor.refresh_from_db()
    assert manor.retainer_count == 1
    assert TroopRecruitment.objects.filter(manor=manor).count() == 0


@pytest.mark.django_db
def test_finalize_troop_recruitment_auto_creates_missing_troop_template(recruit_manor):
    manor = recruit_manor
    TroopTemplate.objects.filter(key="scout").delete()

    recruitment = TroopRecruitment.objects.create(
        manor=manor,
        troop_key="scout",
        troop_name="探子",
        quantity=3,
        equipment_costs={},
        retainer_cost=3,
        base_duration=60,
        actual_duration=60,
        complete_at=timezone.now() - timedelta(seconds=1),
    )

    assert finalize_troop_recruitment(recruitment, send_notification=False) is True

    recruitment.refresh_from_db()
    assert recruitment.status == TroopRecruitment.Status.COMPLETED

    template = TroopTemplate.objects.get(key="scout")
    troop = PlayerTroop.objects.get(manor=manor, troop_template=template)
    assert troop.count == 3


@pytest.mark.django_db
def test_finalize_troop_recruitment_keeps_success_when_notification_fails(monkeypatch, recruit_manor):
    manor = recruit_manor
    TroopTemplate.objects.filter(key="scout").delete()

    recruitment = TroopRecruitment.objects.create(
        manor=manor,
        troop_key="scout",
        troop_name="探子",
        quantity=2,
        equipment_costs={},
        retainer_cost=2,
        base_duration=60,
        actual_duration=60,
        complete_at=timezone.now() - timedelta(seconds=1),
    )

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )
    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    assert finalize_troop_recruitment(recruitment, send_notification=True) is True
    recruitment.refresh_from_db()
    assert recruitment.status == TroopRecruitment.Status.COMPLETED


@pytest.mark.django_db
def test_finalize_troop_recruitment_notification_programming_error_bubbles_up(monkeypatch, recruit_manor):
    manor = recruit_manor
    TroopTemplate.objects.filter(key="scout").delete()

    recruitment = TroopRecruitment.objects.create(
        manor=manor,
        troop_key="scout",
        troop_name="探子",
        quantity=2,
        equipment_costs={},
        retainer_cost=2,
        base_duration=60,
        actual_duration=60,
        complete_at=timezone.now() - timedelta(seconds=1),
    )

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken troop notify contract")),
    )

    with pytest.raises(AssertionError, match="broken troop notify contract"):
        finalize_troop_recruitment(recruitment, send_notification=True)

    recruitment.refresh_from_db()
    assert recruitment.status == TroopRecruitment.Status.COMPLETED


def test_schedule_recruitment_completion_runs_after_commit(monkeypatch):
    callbacks = []
    dispatched = []

    monkeypatch.setattr(
        troop_recruitment_lifecycle_service.transaction,
        "on_commit",
        lambda callback: callbacks.append(callback),
    )
    monkeypatch.setattr(
        "gameplay.tasks.complete_troop_recruitment",
        type("_Task", (), {"name": "gameplay.complete_troop_recruitment"})(),
    )
    monkeypatch.setattr(
        troop_recruitment_lifecycle_service,
        "safe_apply_async",
        lambda task, *, args, countdown, **_kwargs: dispatched.append(
            {
                "task_name": getattr(task, "name", str(task)),
                "args": args,
                "countdown": countdown,
            }
        )
        or True,
    )

    recruitment = type("_Recruitment", (), {"id": 17, "manor_id": 3, "troop_key": "scout"})()

    troop_recruitment_lifecycle_service.schedule_recruitment_completion(recruitment, 45)

    assert len(callbacks) == 1
    assert dispatched == []

    callbacks[0]()

    assert dispatched == [
        {
            "task_name": "gameplay.complete_troop_recruitment",
            "args": [17],
            "countdown": 45,
        }
    ]


def test_schedule_recruitment_completion_unexpected_import_error_bubbles_up(monkeypatch):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "gameplay.tasks":
            raise RuntimeError("broken task module")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    recruitment = type("_Recruitment", (), {"id": 17, "manor_id": 3, "troop_key": "scout"})()

    with pytest.raises(RuntimeError, match="broken task module"):
        troop_recruitment_lifecycle_service.schedule_recruitment_completion(recruitment, 45)


def test_schedule_recruitment_completion_nested_import_error_bubbles_up(monkeypatch):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "gameplay.tasks":
            exc = ModuleNotFoundError("No module named 'redis'")
            exc.name = "redis"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    recruitment = type("_Recruitment", (), {"id": 18, "manor_id": 4, "troop_key": "archer"})()

    with pytest.raises(ModuleNotFoundError, match="redis"):
        troop_recruitment_lifecycle_service.schedule_recruitment_completion(recruitment, 30)
