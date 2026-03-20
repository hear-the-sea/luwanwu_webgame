"""Tests for guest recruitment service logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import guests.services.recruitment as recruitment_command_service
import guests.services.recruitment_candidates as recruitment_candidate_service
import guests.services.recruitment_guests as recruitment_guest_service
import guests.services.recruitment_queries as recruitment_query_service
import guests.services.recruitment_shared as recruitment_shared
import guests.services.recruitment_templates as recruitment_template_service
from core.exceptions import GuestNotFoundError, GuestNotIdleError, InvalidAllocationError, RecruitmentItemOwnershipError
from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from guests.models import (
    Guest,
    GuestRarity,
    GuestStatus,
    GuestTemplate,
    RecruitmentCandidate,
    RecruitmentPool,
    RecruitmentRecord,
    Skill,
)
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

    excluded = recruitment_query_service.get_excluded_template_ids(manor)

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

    excluded = recruitment_query_service.get_excluded_template_ids(manor)

    assert 1 in excluded  # BLACK hermit excluded
    assert 2 not in excluded  # BLACK non-hermit not excluded


def test_get_excluded_template_ids_empty_when_no_guests():
    """Test that empty set is returned when manor has no guests."""
    manor = MagicMock()
    manor.guests.values_list.return_value = []

    excluded = recruitment_query_service.get_excluded_template_ids(manor)

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
    assert recruitment_shared.NON_REPEATABLE_RARITIES == expected


def test_non_repeatable_rarities_excludes_gray_and_black():
    """Test that gray and black are not in NON_REPEATABLE_RARITIES."""
    assert GuestRarity.GRAY not in recruitment_shared.NON_REPEATABLE_RARITIES
    assert GuestRarity.BLACK not in recruitment_shared.NON_REPEATABLE_RARITIES


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

    result = recruitment_template_service._filter_templates(templates, excluded)

    assert len(result) == 2
    assert t1 in result
    assert t2 not in result
    assert t3 in result


def test_filter_templates_returns_all_when_no_exclusions():
    """Test that all templates are returned when excluded_ids is empty."""
    t1 = SimpleNamespace(id=1)
    t2 = SimpleNamespace(id=2)
    templates = [t1, t2]

    result = recruitment_template_service._filter_templates(templates, set())

    assert result == templates


def test_build_rarity_search_order_starts_with_target_and_covers_all_rarities():
    order = recruitment_template_service._build_rarity_search_order(GuestRarity.BLUE)

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


@pytest.mark.django_db
def test_persist_candidate_batch_falls_back_to_row_inserts_when_bulk_return_is_unavailable(
    django_user_model, monkeypatch
):
    user = django_user_model.objects.create_user(username="candidate_persist_reload", password="pass123")
    manor = ensure_manor(user)
    pool = RecruitmentPool.objects.create(
        key="candidate_persist_reload_pool",
        name="候选回填卡池",
        cost={},
        tier=RecruitmentPool.Tier.CUNMU,
        draw_count=1,
    )
    template = GuestTemplate.objects.create(
        key="candidate_persist_reload_tpl",
        name="候选回填模板",
        archetype="civil",
        rarity=GuestRarity.GRAY,
    )
    monkeypatch.setattr(
        "guests.services.recruitment_candidates.connections",
        {
            RecruitmentCandidate.objects.db: SimpleNamespace(
                features=SimpleNamespace(can_return_rows_from_bulk_insert=False)
            )
        },
    )
    bulk_calls = {"count": 0}
    original_bulk_create = RecruitmentCandidate.objects.bulk_create

    def _unexpected_bulk_create(*args, **kwargs):
        bulk_calls["count"] += 1
        return original_bulk_create(*args, **kwargs)

    monkeypatch.setattr(RecruitmentCandidate.objects, "bulk_create", _unexpected_bulk_create)

    created = recruitment_candidate_service.persist_candidate_batch(
        recruitment_candidate_model=RecruitmentCandidate,
        manor=manor,
        candidates_to_create=[
            RecruitmentCandidate(
                manor=manor,
                pool=pool,
                template=template,
                display_name="候选甲",
                rarity=template.rarity,
                archetype=template.archetype,
                rarity_revealed=False,
            ),
            RecruitmentCandidate(
                manor=manor,
                pool=pool,
                template=template,
                display_name="候选乙",
                rarity=template.rarity,
                archetype=template.archetype,
                rarity_revealed=False,
            ),
        ],
        invalidate_cache=lambda *_args, **_kwargs: None,
    )

    assert len(created) == 2
    assert bulk_calls["count"] == 0
    assert all(candidate.pk for candidate in created)
    assert [candidate.display_name for candidate in created] == ["候选甲", "候选乙"]


@pytest.mark.django_db
def test_persist_candidate_batch_row_insert_fallback_remains_atomic(django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="candidate_persist_atomic", password="pass123")
    manor = ensure_manor(user)
    pool = RecruitmentPool.objects.create(
        key="candidate_persist_atomic_pool",
        name="候选原子卡池",
        cost={},
        tier=RecruitmentPool.Tier.CUNMU,
        draw_count=1,
    )
    template = GuestTemplate.objects.create(
        key="candidate_persist_atomic_tpl",
        name="候选原子模板",
        archetype="civil",
        rarity=GuestRarity.GRAY,
    )

    monkeypatch.setattr(
        "guests.services.recruitment_candidates.connections",
        {
            RecruitmentCandidate.objects.db: SimpleNamespace(
                features=SimpleNamespace(can_return_rows_from_bulk_insert=False)
            )
        },
    )

    original_save = RecruitmentCandidate.save
    calls = {"count": 0}

    def _save_then_fail(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("save failed")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(RecruitmentCandidate, "save", _save_then_fail)

    with pytest.raises(RuntimeError, match="save failed"):
        recruitment_candidate_service.persist_candidate_batch(
            recruitment_candidate_model=RecruitmentCandidate,
            manor=manor,
            candidates_to_create=[
                RecruitmentCandidate(
                    manor=manor,
                    pool=pool,
                    template=template,
                    display_name="候选甲",
                    rarity=template.rarity,
                    archetype=template.archetype,
                    rarity_revealed=False,
                ),
                RecruitmentCandidate(
                    manor=manor,
                    pool=pool,
                    template=template,
                    display_name="候选乙",
                    rarity=template.rarity,
                    archetype=template.archetype,
                    rarity_revealed=False,
                ),
            ],
            invalidate_cache=lambda *_args, **_kwargs: None,
        )

    assert RecruitmentCandidate.objects.filter(manor=manor).count() == 0


def test_choose_template_by_rarity_cached_falls_back_to_next_available_rarity():
    green_template = SimpleNamespace(id=11, key="green_tpl")
    blue_template = SimpleNamespace(id=12, key="blue_tpl")

    result = recruitment_template_service._choose_template_by_rarity_cached(
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

    with pytest.raises(InvalidAllocationError):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 0)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_missing_unsaved_guest(django_user_model):
    user = django_user_model.objects.create_user(username="alloc_guest_unsaved", password="pass123")
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(
        key="alloc_guest_unsaved_tpl",
        name="未保存门客模板",
        archetype="civil",
        rarity="gray",
    )
    guest = Guest(manor=manor, template=template, attribute_points=1, force=1, intellect=1, defense_stat=1, agility=1)

    with pytest.raises(GuestNotFoundError, match="门客不存在"):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 1)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_deleted_guest(django_user_model):
    guest = _create_guest_for_allocation_tests(django_user_model, "deleted")
    guest.delete()

    with pytest.raises(GuestNotFoundError, match="门客不存在"):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 1)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_negative_points(django_user_model):
    """Test that negative points allocation is rejected."""
    guest = _create_guest_for_allocation_tests(django_user_model, "negative")

    with pytest.raises(InvalidAllocationError):
        recruitment_guest_service.allocate_attribute_points(guest, "force", -5)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_insufficient_points(django_user_model):
    """Test that allocation fails when not enough points available."""
    guest = _create_guest_for_allocation_tests(django_user_model, "insufficient")
    guest.attribute_points = 5
    guest.save(update_fields=["attribute_points"])

    with pytest.raises(InvalidAllocationError):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 10)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_unknown_attribute(django_user_model):
    """Test that unknown attribute is rejected."""
    guest = _create_guest_for_allocation_tests(django_user_model, "unknown")

    with pytest.raises(InvalidAllocationError):
        recruitment_guest_service.allocate_attribute_points(guest, "unknown_attr", 5)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_overflow(django_user_model):
    """Test that attribute overflow is rejected."""
    guest = _create_guest_for_allocation_tests(django_user_model, "overflow")
    guest.attribute_points = 100
    guest.force = 9950  # Near max
    guest.save(update_fields=["attribute_points", "force"])

    with pytest.raises(InvalidAllocationError):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 100)


@pytest.mark.django_db
def test_allocate_attribute_points_rejects_non_idle_guest(django_user_model):
    guest = _create_guest_for_allocation_tests(django_user_model, "non_idle")
    guest.status = GuestStatus.DEPLOYED
    guest.save(update_fields=["status"])

    with pytest.raises(GuestNotIdleError):
        recruitment_guest_service.allocate_attribute_points(guest, "force", 1)


@pytest.mark.django_db
def test_allocate_attribute_points_success(django_user_model):
    """Test successful attribute point allocation."""
    guest = _create_guest_for_allocation_tests(django_user_model, "success")

    result = recruitment_guest_service.allocate_attribute_points(guest, "force", 5)
    result.refresh_from_db()

    assert result.attribute_points == 5
    assert result.force == 55
    assert result.allocated_force == 5


# ============ clear_template_cache tests ============


def test_clear_template_cache_clears_both_caches():
    """Test that clear_template_cache clears both caches."""
    # Just verify it doesn't raise
    recruitment_template_service.clear_template_cache()


@pytest.mark.django_db
def test_guest_template_signal_clears_recruitment_template_cache(monkeypatch):
    calls: list[str] = []

    def _spy_clear_template_cache():
        calls.append("cleared")

    monkeypatch.setattr(recruitment_template_service, "clear_template_cache", _spy_clear_template_cache)

    GuestTemplate.objects.create(
        key="signal_clear_tpl",
        name="信号清缓存模板",
        archetype="civil",
        rarity="gray",
    )

    assert calls == ["cleared"]


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
    assert recruitment_shared.CORE_POOL_TIERS == expected


# ============ reveal_candidate_rarity tests ============


def test_reveal_candidate_rarity_updates_unrevealed():
    """Test that reveal_candidate_rarity updates unrevealed candidates."""
    manor = MagicMock()
    manor.candidates.filter.return_value.update.return_value = 3

    count = recruitment_command_service.reveal_candidate_rarity(manor)

    assert count == 3
    manor.candidates.filter.assert_called_once_with(rarity_revealed=False)


@pytest.mark.django_db
def test_use_magnifying_glass_for_candidates_rejects_item_not_owned(django_user_model):
    user = django_user_model.objects.create_user(
        username="recruitment_magnifier_missing_user",
        password="pass123",
        email="recruitment_magnifier_missing_user@test.local",
    )
    manor = ensure_manor(user)
    template = ItemTemplate.objects.create(
        key="recruitment_magnifier_missing",
        name="放大镜",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
        tradeable=False,
    )
    InventoryItem.objects.create(
        manor=manor,
        template=template,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    with pytest.raises(RecruitmentItemOwnershipError, match="道具不存在或不属于您的庄园"):
        recruitment_command_service.use_magnifying_glass_for_candidates(manor, item_id=999999)


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

    pool = RecruitmentPool.objects.create(
        key="bulk_finalize_pool",
        name="批量测试卡池",
        cost={},
        tier=RecruitmentPool.Tier.CUNMU,
        draw_count=1,
    )

    for idx in range(3):
        Guest.objects.create(manor=manor, template=template, custom_name=f"已有门客{idx}")

    candidate_1 = RecruitmentCandidate.objects.create(
        manor=manor,
        pool=pool,
        template=template,
        display_name="候选一",
        rarity="gray",
        archetype="civil",
    )
    candidate_2 = RecruitmentCandidate.objects.create(
        manor=manor,
        pool=pool,
        template=template,
        display_name="候选二",
        rarity="gray",
        archetype="civil",
    )

    created, failed = recruitment_guest_service.bulk_finalize_candidates([candidate_1, candidate_2])

    assert len(created) == 1
    assert len(failed) == 1
    assert failed[0].id == candidate_2.id
    created_guest = created[0]
    assert created_guest.custom_name == "候选一"
    assert RecruitmentRecord.objects.filter(manor=manor, guest=created_guest).count() == 1
    assert set(created_guest.guest_skills.values_list("skill__key", flat=True)) == {
        "bulk_finalize_skill_a",
        "bulk_finalize_skill_b",
    }
    assert created_guest.training_complete_at is not None
    assert created_guest.training_target_level == 2
    assert RecruitmentCandidate.objects.filter(id=candidate_1.id).exists() is False
    assert RecruitmentCandidate.objects.filter(id=candidate_2.id).exists() is True


@pytest.mark.django_db
def test_bulk_finalize_candidates_marks_missing_candidates_as_failed(django_user_model):
    user = django_user_model.objects.create_user(
        username="bulk_finalize_missing_user",
        password="pass123",
        email="bulk_finalize_missing_user@test.local",
    )
    manor = ensure_manor(user)

    template = GuestTemplate.objects.create(
        key="bulk_finalize_missing_tpl",
        name="批量缺失模板",
        archetype="civil",
        rarity="gray",
        base_attack=60,
        base_intellect=80,
        base_defense=50,
        base_agility=40,
        base_luck=30,
        base_hp=500,
    )
    pool = RecruitmentPool.objects.create(
        key="bulk_finalize_missing_pool",
        name="批量缺失卡池",
        cost={},
        tier=RecruitmentPool.Tier.CUNMU,
        draw_count=1,
    )

    candidate_1 = RecruitmentCandidate.objects.create(
        manor=manor,
        pool=pool,
        template=template,
        display_name="缺失候选一",
        rarity="gray",
        archetype="civil",
    )
    candidate_2 = RecruitmentCandidate.objects.create(
        manor=manor,
        pool=pool,
        template=template,
        display_name="缺失候选二",
        rarity="gray",
        archetype="civil",
    )
    stale_candidate = RecruitmentCandidate.objects.get(pk=candidate_1.pk)
    RecruitmentCandidate.objects.filter(pk=candidate_1.pk).delete()

    created, failed = recruitment_guest_service.bulk_finalize_candidates([stale_candidate, candidate_2])

    assert len(created) == 1
    assert created[0].custom_name == "缺失候选二"
    assert [candidate.id for candidate in failed] == [candidate_1.id]
