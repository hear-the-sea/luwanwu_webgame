"""Tests for guest recruitment service logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.exceptions import GuestNotIdleError
from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestRarity, GuestStatus, GuestTemplate, Skill
from guests.services import recruitment as recruitment_service
from guests.utils.recruitment_utils import HERMIT_RARITY, RARITY_DISTRIBUTION, RARITY_WEIGHTS, TOTAL_WEIGHT

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
        (1, GuestRarity.BLACK, True),  # Hermit - excluded
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


def test_recruitment_weights_raise_hermit_and_disable_red_for_testing():
    weight_map = dict(RARITY_WEIGHTS)
    assert weight_map[HERMIT_RARITY] == 6000
    assert weight_map[GuestRarity.RED] == 0


def test_recruitment_rarity_distribution_keeps_total_weight():
    assert sum(weight for _, weight in RARITY_DISTRIBUTION) == TOTAL_WEIGHT


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


def test_build_rarity_search_order_starts_with_target_and_covers_all_rarities():
    order = recruitment_service._build_rarity_search_order(GuestRarity.BLUE)

    assert order[0] == GuestRarity.BLUE
    assert len(order) == len(set(order))
    assert set(order) >= {
        GuestRarity.BLACK,
        GuestRarity.GRAY,
        GuestRarity.GREEN,
        GuestRarity.RED,
        GuestRarity.BLUE,
        GuestRarity.PURPLE,
        GuestRarity.ORANGE,
    }


def test_choose_template_by_rarity_cached_falls_back_to_next_available_rarity():
    green_template = SimpleNamespace(id=11, key="green_tpl")
    blue_template = SimpleNamespace(id=12, key="blue_tpl")

    result = recruitment_service._choose_template_by_rarity_cached(
        GuestRarity.RED,
        excluded_ids=set(),
        rng=__import__("random").Random(1),
        templates_by_rarity={
            GuestRarity.GREEN: [green_template],
            GuestRarity.BLUE: [blue_template],
        },
    )

    assert result in [green_template, blue_template]


# ============ allocate_attribute_points tests ============


def _create_guest_for_allocation_tests(django_user_model, suffix: str) -> Guest:
    user = django_user_model.objects.create_user(
        username=f"alloc_guest_{suffix}",
        password="pass123",
        email=f"alloc_guest_{suffix}@test.local",
    )
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key=f"alloc_guest_tpl_{suffix}",
        name="加点测试门客",
        archetype="civil",
        rarity="gray",
        base_attack=80,
        base_intellect=80,
        base_defense=80,
        base_agility=80,
        base_luck=50,
        base_hp=1000,
    )
    return Guest.objects.create(
        manor=manor,
        template=template,
        status=GuestStatus.IDLE,
        attribute_points=10,
        force=50,
        intellect=50,
        defense_stat=50,
        agility=50,
        allocated_force=0,
        allocated_intellect=0,
        allocated_defense=0,
        allocated_agility=0,
    )


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_zero_points(django_user_model):
    """Test that zero points allocation is rejected."""
    guest = _create_guest_for_allocation_tests(django_user_model, "zero")

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "force", 0)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_negative_points(django_user_model):
    """Test that negative points allocation is rejected."""
    guest = _create_guest_for_allocation_tests(django_user_model, "negative")

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "force", -5)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_insufficient_points(django_user_model):
    """Test that allocation fails when not enough points available."""
    guest = _create_guest_for_allocation_tests(django_user_model, "insufficient")
    guest.attribute_points = 5
    guest.save(update_fields=["attribute_points"])

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "force", 10)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_unknown_attribute(django_user_model):
    """Test that unknown attribute is rejected."""
    guest = _create_guest_for_allocation_tests(django_user_model, "unknown")

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "unknown_attr", 5)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_overflow(django_user_model):
    """Test that attribute overflow is rejected."""
    guest = _create_guest_for_allocation_tests(django_user_model, "overflow")
    guest.attribute_points = 100
    guest.force = 9950  # Near max
    guest.save(update_fields=["attribute_points", "force"])

    with pytest.raises(recruitment_service.InvalidAllocationError):
        recruitment_service.allocate_attribute_points(guest, "force", 100)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_non_idle_guest(django_user_model):
    guest = _create_guest_for_allocation_tests(django_user_model, "non_idle")
    guest.status = GuestStatus.DEPLOYED
    guest.save(update_fields=["status"])

    with pytest.raises(GuestNotIdleError):
        recruitment_service.allocate_attribute_points(guest, "force", 1)


@pytest.mark.django_db
def test_allocate_attribute_points_success(django_user_model):
    """Test successful attribute point allocation."""
    guest = _create_guest_for_allocation_tests(django_user_model, "success")

    result = recruitment_service.allocate_attribute_points(guest, "force", 5)
    result.refresh_from_db()

    assert result.attribute_points == 5
    assert result.force == 55
    assert result.allocated_force == 5


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
        RecruitmentPool.Tier.CUNMU,
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


@pytest.mark.django_db
def test_bulk_finalize_candidates_respects_capacity_and_grants_template_skills(django_user_model):
    user = django_user_model.objects.create_user(
        username="bulk_finalize_user",
        password="pass123",
        email="bulk_finalize_user@test.local",
    )
    manor = ensure_manor(user)

    skill_a = Skill.objects.create(key="bulk_finalize_skill_a", name="技能A")
    skill_b = Skill.objects.create(key="bulk_finalize_skill_b", name="技能B")

    template = GuestTemplate.objects.create(
        key="bulk_finalize_tpl",
        name="批量门客模板",
        archetype="civil",
        rarity="gray",
        base_attack=60,
        base_intellect=80,
        base_defense=50,
        base_agility=40,
        base_luck=30,
        base_hp=500,
    )
    template.initial_skills.add(skill_a, skill_b)

    pool = recruitment_service.RecruitmentPool.objects.create(
        key="bulk_finalize_pool",
        name="批量测试卡池",
        cost={},
        tier=recruitment_service.RecruitmentPool.Tier.CUNMU,
        draw_count=1,
    )

    for idx in range(3):
        Guest.objects.create(manor=manor, template=template, custom_name=f"已有门客{idx}")

    candidate_1 = recruitment_service.RecruitmentCandidate.objects.create(
        manor=manor,
        pool=pool,
        template=template,
        display_name="候选一",
        rarity="gray",
        archetype="civil",
    )
    candidate_2 = recruitment_service.RecruitmentCandidate.objects.create(
        manor=manor,
        pool=pool,
        template=template,
        display_name="候选二",
        rarity="gray",
        archetype="civil",
    )

    created, failed = recruitment_service.bulk_finalize_candidates([candidate_1, candidate_2])

    assert len(created) == 1
    assert len(failed) == 1
    assert failed[0].id == candidate_2.id
    created_guest = created[0]
    assert created_guest.custom_name == "候选一"
    assert recruitment_service.RecruitmentRecord.objects.filter(manor=manor, guest=created_guest).count() == 1
    assert set(created_guest.guest_skills.values_list("skill__key", flat=True)) == {
        "bulk_finalize_skill_a",
        "bulk_finalize_skill_b",
    }
    assert recruitment_service.RecruitmentCandidate.objects.filter(id=candidate_1.id).exists() is False
    assert recruitment_service.RecruitmentCandidate.objects.filter(id=candidate_2.id).exists() is True
