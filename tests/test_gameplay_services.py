"""
测试 gameplay.services 模块重构后的功能
"""
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from gameplay.models import ResourceEvent, ResourceType
from gameplay.services import (
    ensure_manor,
    grant_resources,
    spend_resources,
    sync_resource_production,
)

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
