"""
测试 gameplay.services 模块重构后的功能
"""

import logging

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, IntegrityError
from django.db.utils import ProgrammingError
from django.test import override_settings
from django.utils import timezone

from battle.models import TroopTemplate
from core.exceptions import InsufficientResourceError
from gameplay.models import (
    InventoryItem,
    ItemTemplate,
    Manor,
    PlayerTroop,
    ResourceEvent,
    ResourceType,
    TroopBankStorage,
)
from gameplay.services.manor import core as manor_service
from gameplay.services.manor.core import ensure_manor
from gameplay.services.resources import grant_resources, spend_resources, sync_resource_production
from gameplay.utils.resource_calculator import get_personnel_grain_cost_per_hour
from guests.models import Guest, GuestTemplate

User = get_user_model()


def _ensure_grain_template() -> ItemTemplate:
    template, _ = ItemTemplate.objects.get_or_create(
        key="grain",
        defaults={"name": "粮食"},
    )
    if not template.name:
        template.name = "粮食"
        template.save(update_fields=["name"])
    return template


@pytest.mark.django_db
def test_ensure_manor_creates_new():
    """测试为新用户创建庄园"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)

    assert manor is not None
    assert manor.user == user
    assert manor.grain >= 0
    assert manor.silver == 5000
    assert manor.newbie_protection_until is None


@pytest.mark.django_db
def test_ensure_manor_grants_initial_peace_shield_when_template_exists():
    ItemTemplate.objects.create(
        key="peace_shield_small",
        name="免战牌·小",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={"duration": 28800},
    )

    user = User.objects.create_user(username="testuser_init_shield", password="test123")
    manor = ensure_manor(user)

    shield_item = InventoryItem.objects.filter(
        manor=manor,
        template__key="peace_shield_small",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).first()
    assert shield_item is not None
    assert shield_item.quantity == 1


@pytest.mark.django_db
def test_ensure_manor_does_not_duplicate_initial_peace_shield_on_repeat_call():
    ItemTemplate.objects.create(
        key="peace_shield_small",
        name="免战牌·小",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={"duration": 28800},
    )

    user = User.objects.create_user(username="testuser_init_shield_repeat", password="test123")
    first = ensure_manor(user)
    second = ensure_manor(user)

    shield_item = InventoryItem.objects.get(
        manor=second,
        template__key="peace_shield_small",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )
    second.refresh_from_db(fields=["initial_peace_shield_granted_at"])

    assert first.id == second.id
    assert shield_item.quantity == 1
    assert second.initial_peace_shield_granted_at is not None


@pytest.mark.django_db
def test_ensure_manor_initial_peace_shield_runtime_marker_error_bubbles_up(monkeypatch):
    ItemTemplate.objects.create(
        key="peace_shield_small",
        name="免战牌·小",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={"duration": 28800},
    )

    from gameplay.services.inventory.core import add_item_to_inventory_locked as original_add_item

    call_state = {"count": 0}

    def flaky_add_item(*args, **kwargs):
        item_key = args[1] if len(args) > 1 else kwargs.get("item_key")
        if item_key == "peace_shield_small":
            call_state["count"] += 1
        if item_key == "peace_shield_small" and call_state["count"] == 1:
            raise RuntimeError("temporary inventory failure")
        return original_add_item(*args, **kwargs)

    monkeypatch.setattr("gameplay.services.inventory.core.add_item_to_inventory_locked", flaky_add_item)

    user = User(username="testuser_init_shield_retry")
    user.set_password("test123")
    User.objects.bulk_create([user])
    user = User.objects.get(username="testuser_init_shield_retry")

    with pytest.raises(RuntimeError, match="temporary inventory failure"):
        ensure_manor(user)

    first = Manor.objects.get(user=user)
    first.refresh_from_db(fields=["initial_peace_shield_granted_at"])
    assert first.initial_peace_shield_granted_at is None
    assert not InventoryItem.objects.filter(manor=first, template__key="peace_shield_small").exists()

    second = ensure_manor(user)
    second.refresh_from_db(fields=["initial_peace_shield_granted_at"])
    shield_item = InventoryItem.objects.get(
        manor=second,
        template__key="peace_shield_small",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    assert call_state["count"] >= 2
    assert second.initial_peace_shield_granted_at is not None
    assert shield_item.quantity == 1


@pytest.mark.django_db
def test_ensure_manor_returns_existing():
    """测试为已有用户返回现有庄园"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor1 = ensure_manor(user)
    manor2 = ensure_manor(user)

    assert manor1.id == manor2.id


@pytest.mark.django_db
def test_ensure_manor_raises_name_conflict_for_duplicate_initial_name():
    user_a = User(username="manor_name_conflict_user_a")
    user_a.set_password("test123")
    user_b = User(username="manor_name_conflict_user_b")
    user_b.set_password("test123")
    User.objects.bulk_create([user_a, user_b])

    user_a = User.objects.get(username="manor_name_conflict_user_a")
    user_b = User.objects.get(username="manor_name_conflict_user_b")
    ensure_manor(user_a, initial_name="冲突庄园名测试")

    with pytest.raises(manor_service.ManorNameConflictError, match="该庄园名称已被使用"):
        ensure_manor(user_b, initial_name="冲突庄园名测试")


@pytest.mark.django_db
def test_deliver_active_global_mail_campaigns_skips_missing_schema(monkeypatch, caplog):
    user = User(username="global_mail_schema_missing_user")
    user.set_password("test123")
    User.objects.bulk_create([user])
    user = User.objects.get(username="global_mail_schema_missing_user")
    manor = Manor.objects.create(user=user)

    def _raise_missing_schema(_manor):
        raise ProgrammingError("Table 'webgame.gameplay_globalmailcampaign' doesn't exist")

    monkeypatch.setattr("gameplay.services.global_mail.deliver_active_global_mail_campaigns", _raise_missing_schema)

    with caplog.at_level(logging.WARNING):
        manor_service._deliver_active_global_mail_campaigns(manor)

    assert "schema is unavailable" in caplog.text


@pytest.mark.django_db
def test_deliver_active_global_mail_campaigns_runtime_marker_error_bubbles_up(monkeypatch):
    user = User(username="global_mail_runtime_user")
    user.set_password("test123")
    User.objects.bulk_create([user])
    user = User.objects.get(username="global_mail_runtime_user")
    manor = Manor.objects.create(user=user)

    monkeypatch.setattr(
        "gameplay.services.global_mail.deliver_active_global_mail_campaigns",
        lambda _manor: (_ for _ in ()).throw(RuntimeError("global mail bug")),
    )

    with pytest.raises(RuntimeError, match="global mail bug"):
        manor_service._deliver_active_global_mail_campaigns(manor)


@pytest.mark.django_db
def test_ensure_manor_shield_database_error_is_best_effort(monkeypatch):
    ItemTemplate.objects.create(
        key="peace_shield_small",
        name="免战牌·小",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={"duration": 28800},
    )

    monkeypatch.setattr(
        "gameplay.services.inventory.core.add_item_to_inventory_locked",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("db down")),
    )

    user = User.objects.create_user(username="testuser_init_shield_db_fail", password="test123")
    manor = ensure_manor(user)
    manor.refresh_from_db(fields=["initial_peace_shield_granted_at"])

    assert manor.initial_peace_shield_granted_at is None
    assert not InventoryItem.objects.filter(manor=manor, template__key="peace_shield_small").exists()


@pytest.mark.django_db
def test_ensure_manor_recovers_existing_half_initialized_manor(monkeypatch):
    user = User(username="manor_recover_user")
    user.set_password("test123")
    User.objects.bulk_create([user])
    user = User.objects.get(username="manor_recover_user")

    half_ready = Manor.objects.create(user=user, region="overseas", coordinate_x=0, coordinate_y=0)
    monkeypatch.setattr("gameplay.services.manor.core.generate_unique_coordinate", lambda _region: (456, 789))

    manor = ensure_manor(user, region="jiangnan")

    assert manor.id == half_ready.id
    assert manor.region == "jiangnan"
    assert manor.coordinate_x == 456
    assert manor.coordinate_y == 789


@pytest.mark.django_db
def test_ensure_manor_cleans_up_half_initialized_manor_on_repeated_assignment_failure(monkeypatch):
    user = User(username="manor_cleanup_user")
    user.set_password("test123")
    User.objects.bulk_create([user])
    user = User.objects.get(username="manor_cleanup_user")

    original_save = Manor.save

    def _patched_save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self.user_id == user.id and update_fields and "coordinate_x" in update_fields:
            raise IntegrityError("forced coordinate conflict")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr("gameplay.models.manor.Manor.save", _patched_save)

    with pytest.raises(RuntimeError, match="Failed to allocate"):
        ensure_manor(user)

    assert Manor.objects.filter(user=user).exists() is False


@pytest.mark.django_db
def test_ensure_manor_cleans_up_half_initialized_manor_on_name_conflict():
    user_a = User(username="manor_cleanup_name_conflict_a")
    user_a.set_password("test123")
    user_b = User(username="manor_cleanup_name_conflict_b")
    user_b.set_password("test123")
    User.objects.bulk_create([user_a, user_b])
    user_a = User.objects.get(username="manor_cleanup_name_conflict_a")
    user_b = User.objects.get(username="manor_cleanup_name_conflict_b")

    ensure_manor(user_a, initial_name="同名冲突庄园")

    with pytest.raises(manor_service.ManorNameConflictError, match="该庄园名称已被使用"):
        ensure_manor(user_b, initial_name="同名冲突庄园")

    assert Manor.objects.filter(user=user_b).exists() is False


@pytest.mark.django_db
def test_grant_resources():
    """测试发放资源"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)
    initial_silver = manor.silver

    grant_resources(manor, {"silver": 100}, "测试奖励")
    manor.refresh_from_db()

    assert manor.silver == initial_silver + 100


@pytest.mark.django_db
def test_grant_resources_syncs_warehouse_grain_item():
    user = User.objects.create_user(username="grant_grain_sync_user", password="test123", email="g1@test.local")
    manor = ensure_manor(user)
    _ensure_grain_template()

    initial_grain = manor.grain
    InventoryItem.objects.filter(
        manor=manor,
        template__key="grain",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).delete()

    credited = grant_resources(manor, {"grain": 75}, "发粮同步测试")
    manor.refresh_from_db(fields=["grain"])
    warehouse_grain = InventoryItem.objects.filter(
        manor=manor,
        template__key="grain",
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).first()

    assert credited.get("grain", 0) > 0
    assert manor.grain > initial_grain
    assert warehouse_grain is not None
    assert warehouse_grain.quantity == manor.grain


@pytest.mark.django_db
def test_grant_resources_caps_and_logs_actual():
    """奖励被容量截断时，日志和返回值应为实际入账量"""
    user = User.objects.create_user(username="testuser2", password="test123")
    manor = ensure_manor(user)

    manor.silver_capacity = 100
    manor.silver = 95
    manor.save(update_fields=["silver_capacity", "silver"])

    credited = grant_resources(
        manor,
        {"silver": 20},
        note="容量测试",
        reason=ResourceEvent.Reason.TASK_REWARD,
    )
    manor.refresh_from_db()

    assert credited == {"silver": 5}
    assert manor.silver == 100

    event = ResourceEvent.objects.filter(
        manor=manor,
        resource_type=ResourceType.SILVER,
        reason=ResourceEvent.Reason.TASK_REWARD,
        note="容量测试",
    ).first()
    assert event is not None
    assert event.delta == 5


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_grant_resources_rejects_unknown_resource_in_debug():
    user = User.objects.create_user(username="resource_unknown_debug", password="test123")
    manor = ensure_manor(user)

    with pytest.raises(AssertionError, match="unknown resource type: mystery"):
        grant_resources(manor, {"mystery": 10}, "未知资源测试")


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_grant_resources_skips_unknown_resource_and_logs_error(caplog):
    user = User.objects.create_user(username="resource_unknown_prod", password="test123")
    manor = ensure_manor(user)
    initial_silver = manor.silver

    with caplog.at_level(logging.ERROR):
        credited = grant_resources(manor, {"mystery": 10}, "未知资源测试")

    manor.refresh_from_db(fields=["silver"])
    assert credited == {}
    assert manor.silver == initial_silver
    assert "未知资源类型被跳过" in caplog.text


@pytest.mark.django_db
def test_spend_resources_success():
    """测试消耗资源（成功）"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)
    manor.silver = 500
    manor.save()

    spend_resources(manor, {"silver": 100}, "测试消耗")
    manor.refresh_from_db()

    assert manor.silver == 400


@pytest.mark.django_db
def test_spend_resources_insufficient():
    """测试消耗资源（资源不足）"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)
    manor.silver = 50
    manor.save()

    with pytest.raises(InsufficientResourceError, match="银两不足"):
        spend_resources(manor, {"silver": 100}, "测试消耗")


@pytest.mark.django_db
def test_spend_resources_syncs_warehouse_grain_item():
    user = User.objects.create_user(username="spend_grain_sync_user", password="test123", email="s1@test.local")
    manor = ensure_manor(user)
    grain_template = _ensure_grain_template()

    manor.grain = 300
    manor.save(update_fields=["grain"])
    InventoryItem.objects.update_or_create(
        manor=manor,
        template=grain_template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": 500},
    )

    spend_resources(manor, {"grain": 120}, "扣粮同步测试")
    manor.refresh_from_db(fields=["grain"])
    warehouse_grain = InventoryItem.objects.get(
        manor=manor,
        template=grain_template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    assert manor.grain == 180
    assert warehouse_grain.quantity == 180


@pytest.mark.django_db
def test_sync_resource_production():
    """测试资源产出同步"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)
    initial_silver = manor.silver

    # 设置资源更新时间为1小时前
    manor.resource_updated_at = timezone.now() - timezone.timedelta(hours=1)
    manor.save()

    sync_resource_production(manor)
    manor.refresh_from_db()

    # 资源应该有所增加
    assert manor.silver >= initial_silver


@pytest.mark.django_db
def test_sync_resource_production_persist_false_projects_without_db_write(monkeypatch):
    user = User.objects.create_user(username="resource_projection_user", password="test123")
    manor = ensure_manor(user)
    original_updated_at = timezone.now() - timezone.timedelta(hours=1)
    manor.resource_updated_at = original_updated_at
    manor.save(update_fields=["resource_updated_at"])
    initial_silver = manor.silver

    monkeypatch.setattr(
        "gameplay.services.resources.get_hourly_rates",
        lambda _manor: {ResourceType.SILVER: 120, ResourceType.GRAIN: 0},
    )
    monkeypatch.setattr("gameplay.services.resources.get_personnel_grain_cost_per_hour", lambda _manor: 0)
    monkeypatch.setattr("gameplay.services.resources.scale_value", lambda value: value)

    sync_resource_production(manor, persist=False)

    assert manor.silver == initial_silver + 120
    manor.refresh_from_db(fields=["silver", "resource_updated_at"])
    assert manor.silver == initial_silver
    assert manor.resource_updated_at == original_updated_at


@pytest.mark.django_db
def test_spend_resources_applies_offline_production_before_balance_check(monkeypatch):
    user = User.objects.create_user(username="resource_spend_sync_user", password="test123")
    manor = ensure_manor(user)
    manor.silver = 50
    manor.resource_updated_at = timezone.now() - timezone.timedelta(hours=1)
    manor.save(update_fields=["silver", "resource_updated_at"])

    monkeypatch.setattr(
        "gameplay.services.resources.get_hourly_rates",
        lambda _manor: {ResourceType.SILVER: 100, ResourceType.GRAIN: 0},
    )
    monkeypatch.setattr("gameplay.services.resources.get_personnel_grain_cost_per_hour", lambda _manor: 0)
    monkeypatch.setattr("gameplay.services.resources.scale_value", lambda value: value)

    spend_resources(manor, {"silver": 100}, "离线产出后扣费")
    manor.refresh_from_db(fields=["silver"])

    assert manor.silver == 50


@pytest.mark.django_db
def test_get_personnel_grain_cost_per_hour_counts_all_personnel():
    user = User.objects.create_user(username="personnel_cost_user", password="test123", email="p1@test.local")
    manor = ensure_manor(user)
    manor.retainer_count = 5
    manor.save(update_fields=["retainer_count"])

    guest_template = GuestTemplate.objects.create(
        key="personnel_cost_guest_tpl",
        name="耗粮测试门客",
        archetype="civil",
        rarity="green",
    )
    Guest.objects.create(manor=manor, template=guest_template)
    Guest.objects.create(manor=manor, template=guest_template)

    troop_template = TroopTemplate.objects.create(key="personnel_cost_guard_tpl", name="耗粮测试护院")
    PlayerTroop.objects.create(manor=manor, troop_template=troop_template, count=7)
    TroopBankStorage.objects.create(manor=manor, troop_template=troop_template, count=11)

    # 5家丁 + (7+11)护院 + 2门客*100 = 223
    assert get_personnel_grain_cost_per_hour(manor) == 223


@pytest.mark.django_db
def test_sync_resource_production_allows_negative_grain_delta_and_clamps_to_zero(monkeypatch):
    user = User.objects.create_user(username="negative_grain_user", password="test123", email="p2@test.local")
    manor = ensure_manor(user)
    grain_template = _ensure_grain_template()
    manor.grain = 90
    manor.resource_updated_at = timezone.now() - timezone.timedelta(hours=1)
    manor.save(update_fields=["grain", "resource_updated_at"])
    InventoryItem.objects.update_or_create(
        manor=manor,
        template=grain_template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        defaults={"quantity": 90},
    )

    monkeypatch.setattr(
        "gameplay.services.resources.get_hourly_rates",
        lambda _manor: {ResourceType.GRAIN: 50, ResourceType.SILVER: 0},
    )
    monkeypatch.setattr(
        "gameplay.services.resources.get_personnel_grain_cost_per_hour",
        lambda _manor: 200,
    )
    monkeypatch.setattr("gameplay.services.resources.scale_value", lambda value: value)

    sync_resource_production(manor)
    manor.refresh_from_db()

    assert manor.grain == 0
    assert not InventoryItem.objects.filter(
        manor=manor,
        template=grain_template,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    ).exists()
    event = (
        ResourceEvent.objects.filter(
            manor=manor,
            resource_type=ResourceType.GRAIN,
            reason=ResourceEvent.Reason.PRODUCE,
            note="离线产出",
        )
        .order_by("-id")
        .first()
    )
    assert event is not None
    assert event.delta == -90
