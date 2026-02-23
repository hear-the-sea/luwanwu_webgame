"""Tests for jail/prisoner service logic."""

from __future__ import annotations

import random
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gameplay.services import jail as jail_service

pytestmark = pytest.mark.django_db


# ============ list_held_prisoners tests ============


def test_list_held_prisoners_returns_empty_list_when_no_prisoners():
    """Test that empty list is returned when manor has no prisoners."""
    manor = SimpleNamespace(pk=1)

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.filter.return_value.select_related.return_value.order_by.return_value = []

        result = jail_service.list_held_prisoners(manor)

        assert result == []
        mock_qs.filter.assert_called_once()


# ============ list_oath_bonds tests ============


def test_list_oath_bonds_returns_empty_list_when_no_bonds():
    """Test that empty list is returned when manor has no oath bonds."""
    manor = SimpleNamespace(pk=1)

    with patch.object(jail_service.OathBond, "objects") as mock_qs:
        mock_qs.filter.return_value.select_related.return_value.order_by.return_value = []

        result = jail_service.list_oath_bonds(manor)

        assert result == []


# ============ add_oath_bond tests ============


@patch("gameplay.services.jail.Manor")
def test_add_oath_bond_raises_when_guest_not_found(mock_manor_model):
    """Test that ValueError is raised when guest doesn't exist."""
    manor = SimpleNamespace(pk=1, oath_capacity=5)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    with patch.object(jail_service.Guest, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="门客不存在"):
            jail_service.add_oath_bond(manor, guest_id=999)


@patch("gameplay.services.jail.Manor")
def test_add_oath_bond_raises_when_capacity_full(mock_manor_model):
    """Test that ValueError is raised when oath capacity is full."""
    manor = SimpleNamespace(pk=1, oath_capacity=2)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    guest = SimpleNamespace(pk=10, status=jail_service.GuestStatus.IDLE)

    with patch.object(jail_service.Guest, "objects") as mock_guest_qs:
        mock_guest_qs.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = (
            guest
        )

        with patch.object(jail_service.OathBond, "objects") as mock_bond_qs:
            mock_bond_qs.filter.return_value.count.return_value = 2  # At capacity

            with pytest.raises(ValueError, match="结义人数已满"):
                jail_service.add_oath_bond(manor, guest_id=10)


@patch("gameplay.services.jail.Manor")
def test_add_oath_bond_raises_when_already_bonded(mock_manor_model):
    """Test that ValueError is raised when guest is already bonded."""
    manor = SimpleNamespace(pk=1, oath_capacity=5)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    guest = SimpleNamespace(pk=10, status=jail_service.GuestStatus.IDLE)
    existing_bond = SimpleNamespace(pk=1)

    with patch.object(jail_service.Guest, "objects") as mock_guest_qs:
        mock_guest_qs.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = (
            guest
        )

        with patch.object(jail_service.OathBond, "objects") as mock_bond_qs:
            mock_bond_qs.filter.return_value.count.return_value = 1
            mock_bond_qs.get_or_create.return_value = (existing_bond, False)  # Not created

            with pytest.raises(ValueError, match="该门客已结义"):
                jail_service.add_oath_bond(manor, guest_id=10)


@patch("gameplay.services.jail.Manor")
def test_add_oath_bond_rejects_non_idle_guest(mock_manor_model):
    manor = SimpleNamespace(pk=1, oath_capacity=5)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    guest = SimpleNamespace(pk=10, status=jail_service.GuestStatus.DEPLOYED, display_name="测试门客")

    with patch.object(jail_service.Guest, "objects") as mock_guest_qs:
        mock_guest_qs.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = (
            guest
        )

        with pytest.raises(jail_service.GuestNotIdleError):
            jail_service.add_oath_bond(manor, guest_id=10)


# ============ remove_oath_bond tests ============


def test_remove_oath_bond_returns_deleted_count():
    """Test that remove_oath_bond returns correct deleted count."""
    manor = SimpleNamespace(pk=1)

    with patch.object(jail_service.OathBond, "objects") as mock_qs:
        mock_qs.filter.return_value.delete.return_value = (1, {})

        result = jail_service.remove_oath_bond(manor, guest_id=10)

        assert result == 1


def test_remove_oath_bond_returns_zero_when_not_found():
    """Test that remove_oath_bond returns 0 when bond doesn't exist."""
    manor = SimpleNamespace(pk=1)

    with patch.object(jail_service.OathBond, "objects") as mock_qs:
        mock_qs.filter.return_value.delete.return_value = (0, {})

        result = jail_service.remove_oath_bond(manor, guest_id=999)

        assert result == 0


@patch("gameplay.services.jail.Guest")
def test_remove_oath_bond_rejects_non_idle_guest(mock_guest_model):
    manor = SimpleNamespace(pk=1)
    guest = SimpleNamespace(status=jail_service.GuestStatus.WORKING, display_name="测试门客")
    mock_guest_model.objects.select_for_update.return_value.filter.return_value.first.return_value = guest

    with pytest.raises(jail_service.GuestNotIdleError):
        jail_service.remove_oath_bond(manor, guest_id=10)


# ============ release_prisoner tests ============


def test_release_prisoner_raises_when_not_found():
    """Test that ValueError is raised when prisoner doesn't exist."""
    manor = SimpleNamespace(pk=1)

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="囚徒不存在或已处理"):
            jail_service.release_prisoner(manor, prisoner_id=999)


def test_release_prisoner_sets_status_to_released():
    """Test that release_prisoner sets status to RELEASED."""
    manor = SimpleNamespace(pk=1)
    prisoner = MagicMock()
    prisoner.status = jail_service.JailPrisoner.Status.HELD

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.filter.return_value.first.return_value = prisoner

        result = jail_service.release_prisoner(manor, prisoner_id=1)

        assert result.status == jail_service.JailPrisoner.Status.RELEASED
        prisoner.save.assert_called_once_with(update_fields=["status"])


# ============ draw_pie tests ============


def test_draw_pie_raises_when_prisoner_not_found():
    """Test that ValueError is raised when prisoner doesn't exist."""
    manor = SimpleNamespace(pk=1)

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="囚徒不存在或已处理"):
            jail_service.draw_pie(manor, prisoner_id=999)


def test_draw_pie_raises_when_gold_insufficient():
    """Test that ValueError is raised when gold bars are insufficient."""
    manor = SimpleNamespace(pk=1)
    prisoner = MagicMock()
    prisoner.loyalty = 80

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.filter.return_value.first.return_value = prisoner

        # 修复：Mock InventoryItem 查询链返回 None，避免真实 ORM 尝试解析 SimpleNamespace
        with patch("gameplay.models.InventoryItem") as mock_inventory_item:
            mock_inventory_item.objects.select_for_update.return_value.filter.return_value.first.return_value = None
            with patch.object(jail_service, "get_item_quantity", return_value=0):
                with pytest.raises(ValueError, match="金条不足"):
                    jail_service.draw_pie(manor, prisoner_id=1)


@patch("gameplay.services.jail.Manor")
def test_draw_pie_reduces_loyalty_and_consumes_gold(mock_manor_model):
    """Test that draw_pie reduces loyalty and consumes gold bar."""
    manor = SimpleNamespace(pk=1)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    prisoner = MagicMock()
    prisoner.loyalty = 80

    with patch.object(jail_service.JailPrisoner, "objects") as mock_prisoner_qs:
        mock_prisoner_qs.select_for_update.return_value.filter.return_value.first.return_value = prisoner

        # 修复：Patch gameplay.models.InventoryItem 因为 draw_pie 内部是从那里导入的
        with patch("gameplay.models.InventoryItem") as mock_inventory_item:
            # Mock the query for gold bar
            mock_item_instance = MagicMock()
            mock_item_instance.pk = 100
            mock_item_instance.quantity = 5
            mock_inventory_item.objects.select_for_update.return_value.filter.return_value.first.return_value = (
                mock_item_instance
            )

            # Mock atomic update
            mock_inventory_item.objects.filter.return_value.update.return_value = 1

            # Fix random for deterministic test
            with patch.object(random, "randint", return_value=7):
                result = jail_service.draw_pie(manor, prisoner_id=1)

                # Verify gold bar was consumed via update
                mock_inventory_item.objects.filter.assert_any_call(pk=100)
                assert result.loyalty == 73
                assert result._reduction == 7


@patch("gameplay.services.jail.Manor")
def test_draw_pie_loyalty_cannot_go_below_zero(mock_manor_model):
    """Test that loyalty cannot go below zero."""
    manor = SimpleNamespace(pk=1)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    prisoner = MagicMock()
    prisoner.loyalty = 3  # Low loyalty

    with patch.object(jail_service.JailPrisoner, "objects") as mock_prisoner_qs:
        mock_prisoner_qs.select_for_update.return_value.filter.return_value.first.return_value = prisoner

        with patch("gameplay.models.InventoryItem") as mock_inventory_item:
            mock_item_instance = MagicMock()
            mock_item_instance.pk = 100
            mock_item_instance.quantity = 5
            mock_inventory_item.objects.select_for_update.return_value.filter.return_value.first.return_value = (
                mock_item_instance
            )

            with patch.object(random, "randint", return_value=10):
                result = jail_service.draw_pie(manor, prisoner_id=1)
                assert result.loyalty == 0


@patch("gameplay.services.jail.Manor")
def test_draw_pie_raises_when_gold_insufficient_with_manor_lock(mock_manor_model):
    """Test that ValueError is raised when gold bars are insufficient."""
    manor = SimpleNamespace(pk=1)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    prisoner = MagicMock()
    prisoner.loyalty = 80

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.filter.return_value.first.return_value = prisoner

        # 修复：Mock InventoryItem 查询链返回 None，触发不足逻辑
        with patch("gameplay.models.InventoryItem") as mock_inventory_item:
            mock_inventory_item.objects.select_for_update.return_value.filter.return_value.first.return_value = None

            with patch.object(jail_service, "get_item_quantity", return_value=0):
                with pytest.raises(ValueError, match="金条不足"):
                    jail_service.draw_pie(manor, prisoner_id=1)


# ============ recruit_prisoner tests ============


@patch("gameplay.services.jail.Manor")
def test_recruit_prisoner_raises_when_not_found(mock_manor_model):
    """Test that ValueError is raised when prisoner doesn't exist."""
    manor = SimpleNamespace(pk=1)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="囚徒不存在"):
            jail_service.recruit_prisoner(manor, prisoner_id=999)


@patch("gameplay.services.jail.Manor")
def test_recruit_prisoner_raises_when_already_processed(mock_manor_model):
    """Test that ValueError is raised when prisoner is already processed."""
    manor = SimpleNamespace(pk=1)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    prisoner = MagicMock()
    prisoner.status = jail_service.JailPrisoner.Status.RELEASED

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = (
            prisoner
        )

        with pytest.raises(ValueError, match="囚徒已处理"):
            jail_service.recruit_prisoner(manor, prisoner_id=1)


@patch("gameplay.services.jail.Manor")
def test_recruit_prisoner_raises_when_loyalty_too_high(mock_manor_model):
    """Test that ValueError is raised when prisoner loyalty is too high."""
    manor = SimpleNamespace(pk=1)
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    prisoner = MagicMock()
    prisoner.status = jail_service.JailPrisoner.Status.HELD
    prisoner.loyalty = 50  # Above threshold (30)

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = (
            prisoner
        )

        with pytest.raises(ValueError, match="忠诚度过高"):
            jail_service.recruit_prisoner(manor, prisoner_id=1)


@patch("gameplay.services.jail.Manor")
def test_recruit_prisoner_raises_when_guest_capacity_full(mock_manor_model):
    """Test that GuestCapacityFullError is raised when guest capacity is full."""
    # Create a real Mock that can handle property access
    manor = MagicMock()
    manor.guest_capacity = 10
    manor.guests.count.return_value = 10  # At capacity
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    prisoner = MagicMock()
    prisoner.status = jail_service.JailPrisoner.Status.HELD
    prisoner.loyalty = 20  # Below threshold

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = (
            prisoner
        )

        with pytest.raises(jail_service.GuestCapacityFullError):
            jail_service.recruit_prisoner(manor, prisoner_id=1)


@patch("gameplay.services.jail.Manor")
def test_recruit_prisoner_raises_when_gold_insufficient(mock_manor_model):
    """Test that ValueError is raised when gold bars are insufficient."""
    manor = MagicMock()
    manor.guest_capacity = 10
    manor.guests.count.return_value = 5
    mock_manor_model.objects.select_for_update.return_value.get.return_value = manor

    prisoner = MagicMock()
    prisoner.status = jail_service.JailPrisoner.Status.HELD
    prisoner.loyalty = 20

    with patch.object(jail_service.JailPrisoner, "objects") as mock_qs:
        mock_qs.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = (
            prisoner
        )

        # 修复：Mock InventoryItem 查询链，使其返回 None
        with patch("gameplay.models.InventoryItem") as mock_inventory_item:
            mock_inventory_item.objects.select_for_update.return_value.filter.return_value.first.return_value = None

            with patch.object(jail_service, "get_item_quantity", return_value=0):
                with pytest.raises(ValueError, match="金条不足"):
                    jail_service.recruit_prisoner(manor, prisoner_id=1)


# ============ Constants tests ============


def test_gold_bar_item_key_constant():
    """Test that gold bar item key constant is correctly defined."""
    assert jail_service.GOLD_BAR_ITEM_KEY == "gold_bar"
