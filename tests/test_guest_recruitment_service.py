"""Tests for guest recruitment service logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from guests.services import recruitment as recruitment_service
from guests.models import GuestRarity


# ============ get_excluded_template_ids tests ============


def test_get_excluded_template_ids_excludes_green_and_above():
    """Test that green and above rarities are excluded."""
    manor = MagicMock()
    manor.guests.values_list.return_value = [
        (1, GuestRarity.GREEN, False),
        (2, GuestRarity.BLUE, False),
        (3, GuestRarity.GRAY, False),  # Should NOT be excluded
    ]

    excluded = recruitment_service.get_excluded_template_ids(manor)

    assert 1 in excluded  # GREEN excluded
    assert 2 in excluded  # BLUE excluded
    assert 3 not in excluded  # GRAY not excluded


def test_get_excluded_template_ids_excludes_black_hermit():
    """Test that black hermit templates are excluded."""
    manor = MagicMock()
    manor.guests.values_list.return_value = [
        (1, GuestRarity.BLACK, True),   # Hermit - excluded
        (2, GuestRarity.BLACK, False),  # Not hermit - not excluded
    ]

    excluded = recruitment_service.get_excluded_template_ids(manor)

    assert 1 in excluded  # BLACK hermit excluded
    assert 2 not in excluded  # BLACK non-hermit not excluded


def test_get_excluded_template_ids_empty_when_no_guests():
    """Test that empty set is returned when manor has no guests."""
    manor = MagicMock()
    manor.guests.values_list.return_value = []

    excluded = recruitment_service.get_excluded_template_ids(manor)

    assert excluded == set()


# ============ NON_REPEATABLE_RARITIES tests ============


def test_non_repeatable_rarities_includes_expected():
    """Test that NON_REPEATABLE_RARITIES contains expected rarities."""
    expected = {
        GuestRarity.GREEN,
        GuestRarity.BLUE,
        GuestRarity.RED,
        GuestRarity.PURPLE,
        GuestRarity.ORANGE,
    }
    assert recruitment_service.NON_REPEATABLE_RARITIES == expected


def test_non_repeatable_rarities_excludes_gray_and_black():
    """Test that gray and black are not in NON_REPEATABLE_RARITIES."""
    assert GuestRarity.GRAY not in recruitment_service.NON_REPEATABLE_RARITIES
    assert GuestRarity.BLACK not in recruitment_service.NON_REPEATABLE_RARITIES


# ============ _filter_templates tests ============


def test_filter_templates_removes_excluded():
    """Test that excluded template IDs are filtered out."""
    t1 = SimpleNamespace(id=1)
    t2 = SimpleNamespace(id=2)
    t3 = SimpleNamespace(id=3)
    templates = [t1, t2, t3]
    excluded = {2}

    result = recruitment_service._filter_templates(templates, excluded)

    assert len(result) == 2
    assert t1 in result
    assert t2 not in result
    assert t3 in result


def test_filter_templates_returns_all_when_no_exclusions():
    """Test that all templates are returned when excluded_ids is empty."""
    t1 = SimpleNamespace(id=1)
    t2 = SimpleNamespace(id=2)
    templates = [t1, t2]

    result = recruitment_service._filter_templates(templates, set())

    assert result == templates


# ============ allocate_attribute_points tests ============


def test_allocate_attribute_points_rejects_zero_points():
    """Test that zero points allocation is rejected."""
    guest = MagicMock()
    guest.attribute_points = 10

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "force", 0)


def test_allocate_attribute_points_rejects_negative_points():
    """Test that negative points allocation is rejected."""
    guest = MagicMock()
    guest.attribute_points = 10

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "force", -5)


def test_allocate_attribute_points_rejects_insufficient_points():
    """Test that allocation fails when not enough points available."""
    guest = MagicMock()
    guest.attribute_points = 5

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "force", 10)


def test_allocate_attribute_points_rejects_unknown_attribute():
    """Test that unknown attribute is rejected."""
    guest = MagicMock()
    guest.attribute_points = 10

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "unknown_attr", 5)


def test_allocate_attribute_points_rejects_overflow():
    """Test that attribute overflow is rejected."""
    guest = MagicMock()
    guest.attribute_points = 100
    guest.force = 9950  # Near max

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "force", 100)


def test_allocate_attribute_points_success():
    """Test successful attribute point allocation."""
    guest = MagicMock()
    guest.attribute_points = 10
    guest.force = 50
    guest.allocated_force = 0

    result = recruitment_service.allocate_attribute_points(guest, "force", 5)

    assert result.attribute_points == 5
    assert result.force == 55
    assert result.allocated_force == 5
    guest.save.assert_called_once()


# ============ clear_template_cache tests ============


def test_clear_template_cache_clears_both_caches():
    """Test that clear_template_cache clears both caches."""
    # Just verify it doesn't raise
    recruitment_service.clear_template_cache()


# ============ CORE_POOL_TIERS tests ============


def test_core_pool_tiers_has_expected_tiers():
    """Test that CORE_POOL_TIERS contains expected tiers."""
    from guests.models import RecruitmentPool

    expected = (
        RecruitmentPool.Tier.TONGSHI,
        RecruitmentPool.Tier.XIANGSHI,
        RecruitmentPool.Tier.HUISHI,
        RecruitmentPool.Tier.DIANSHI,
    )
    assert recruitment_service.CORE_POOL_TIERS == expected


# ============ reveal_candidate_rarity tests ============


def test_reveal_candidate_rarity_updates_unrevealed():
    """Test that reveal_candidate_rarity updates unrevealed candidates."""
    manor = MagicMock()
    manor.candidates.filter.return_value.update.return_value = 3

    count = recruitment_service.reveal_candidate_rarity(manor)

    assert count == 3
    manor.candidates.filter.assert_called_once_with(rarity_revealed=False)
