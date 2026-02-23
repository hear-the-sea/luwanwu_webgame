"""
测试 gameplay.services 模块重构后的功能
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from battle.models import TroopTemplate
from gameplay.models import PlayerTroop, ResourceEvent, ResourceType, TroopBankStorage
from gameplay.services import ensure_manor, grant_resources, spend_resources, sync_resource_production
from gameplay.utils.resource_calculator import get_personnel_grain_cost_per_hour
from guests.models import Guest, GuestTemplate

User = get_user_model()


@pytest.mark.django_db
def test_ensure_manor_creates_new():
    """测试为新用户创建庄园"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)

    assert manor is not None
    assert manor.user == user
    assert manor.grain >= 0
    assert manor.silver >= 0


@pytest.mark.django_db
def test_ensure_manor_returns_existing():
    """测试为已有用户返回现有庄园"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor1 = ensure_manor(user)
    manor2 = ensure_manor(user)

    assert manor1.id == manor2.id


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

    with pytest.raises(ValueError, match="资源不足"):
        spend_resources(manor, {"silver": 100}, "测试消耗")


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
    manor.grain = 90
    manor.resource_updated_at = timezone.now() - timezone.timedelta(hours=1)
    manor.save(update_fields=["grain", "resource_updated_at"])

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
