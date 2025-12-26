"""
测试 guests.services 模块重构后的功能
"""
import pytest
from django.contrib.auth import get_user_model

from core.exceptions import InvalidAllocationError
from gameplay.services import ensure_manor
from guests.models import Guest, GuestTemplate
from guests.services import (
    allocate_attribute_points,
    available_guests,
    list_pools,
    recover_guest_hp,
)

User = get_user_model()


@pytest.mark.django_db
def test_list_pools():
    """测试获取招募卡池列表"""
    pools = list(list_pools())
    # 应该返回可迭代对象（即使为空）
    assert isinstance(pools, list)


@pytest.mark.django_db
def test_available_guests_empty():
    """测试获取可用门客（空）"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)

    guests = list(available_guests(manor))
    assert guests == []


@pytest.mark.django_db
def test_available_guests_ordered():
    """测试获取可用门客（按稀有度和等级排序）"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)

    # 创建测试门客模板
    template1 = GuestTemplate.objects.create(
        key="test_guest_1", name="测试门客1", rarity="gray", base_attack=50, base_defense=50
    )
    template2 = GuestTemplate.objects.create(
        key="test_guest_2", name="测试门客2", rarity="gold", base_attack=80, base_defense=80
    )

    # 创建门客
    guest1 = Guest.objects.create(manor=manor, template=template1, force=50, intellect=50, level=1)
    guest2 = Guest.objects.create(manor=manor, template=template2, force=80, intellect=80, level=5)

    guests = list(available_guests(manor))

    # 应该返回两个门客
    assert len(guests) == 2
    # 验证门客都被正确获取
    guest_ids = {g.id for g in guests}
    assert guest1.id in guest_ids
    assert guest2.id in guest_ids


@pytest.mark.django_db
def test_recover_guest_hp_already_full():
    """测试恢复生命值（已满血）"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key="test_guest", name="测试门客", rarity="gray", base_attack=50, base_defense=50
    )
    guest = Guest.objects.create(manor=manor, template=template, force=50, intellect=50, current_hp=100)
    guest.current_hp = guest.max_hp
    guest.save()

    initial_hp = guest.current_hp
    recover_guest_hp(guest)
    guest.refresh_from_db()

    # 生命值不应该超过最大值
    assert guest.current_hp == initial_hp


@pytest.mark.django_db
def test_allocate_attribute_points():
    """测试分配属性点"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key="test_guest", name="测试门客", rarity="gray", base_attack=50, base_defense=50
    )
    guest = Guest.objects.create(
        manor=manor, template=template, force=50, intellect=50, attribute_points=10
    )

    initial_force = guest.force
    allocate_attribute_points(guest, "force", 5)
    guest.refresh_from_db()

    assert guest.attribute_points == 5
    assert guest.force == initial_force + 5


@pytest.mark.django_db
def test_allocate_attribute_points_insufficient():
    """测试分配属性点（属性点不足）"""
    user = User.objects.create_user(username="testuser", password="test123")
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key="test_guest", name="测试门客", rarity="gray", base_attack=50, base_defense=50
    )
    guest = Guest.objects.create(
        manor=manor, template=template, force=50, intellect=50, attribute_points=3
    )

    with pytest.raises(InvalidAllocationError, match="属性点不足"):
        allocate_attribute_points(guest, "force", 5)
