from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import guests.services.recruitment_queries as recruitment_query_service
import guests.services.recruitment_shared as recruitment_shared
import guests.services.recruitment_templates as recruitment_template_service
from guests.models import GuestRarity
from guests.utils.recruitment_utils import HERMIT_RARITY, RARITY_DISTRIBUTION, RARITY_WEIGHTS, TOTAL_WEIGHT


def test_get_excluded_template_ids_excludes_green_and_above():
    manor = MagicMock()
    manor.guests.values_list.return_value = [
        (1, GuestRarity.GREEN, False),
        (2, GuestRarity.BLUE, False),
        (3, GuestRarity.GRAY, False),
    ]

    excluded = recruitment_query_service.get_excluded_template_ids(manor)

    assert 1 in excluded
    assert 2 in excluded
    assert 3 not in excluded


def test_get_excluded_template_ids_excludes_black_hermit():
    manor = MagicMock()
    manor.guests.values_list.return_value = [
        (1, GuestRarity.BLACK, True),
        (2, GuestRarity.BLACK, False),
    ]

    excluded = recruitment_query_service.get_excluded_template_ids(manor)

    assert 1 in excluded
    assert 2 not in excluded


def test_get_excluded_template_ids_empty_when_no_guests():
    manor = MagicMock()
    manor.guests.values_list.return_value = []

    excluded = recruitment_query_service.get_excluded_template_ids(manor)

    assert excluded == set()


def test_non_repeatable_rarities_includes_expected():
    expected = {
        GuestRarity.GREEN,
        GuestRarity.BLUE,
        GuestRarity.RED,
        GuestRarity.PURPLE,
        GuestRarity.ORANGE,
    }
    assert recruitment_shared.NON_REPEATABLE_RARITIES == expected


def test_non_repeatable_rarities_excludes_gray_and_black():
    assert GuestRarity.GRAY not in recruitment_shared.NON_REPEATABLE_RARITIES
    assert GuestRarity.BLACK not in recruitment_shared.NON_REPEATABLE_RARITIES


def test_recruitment_weights_raise_hermit_and_disable_red_for_testing():
    weight_map = dict(RARITY_WEIGHTS)
    assert weight_map[HERMIT_RARITY] == 6000
    assert weight_map[GuestRarity.RED] == 0


def test_recruitment_rarity_distribution_keeps_total_weight():
    assert sum(weight for _, weight in RARITY_DISTRIBUTION) == TOTAL_WEIGHT


def test_filter_templates_removes_excluded():
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


def test_core_pool_tiers_has_expected_tiers():
    from guests.models import RecruitmentPool

    expected = (
        RecruitmentPool.Tier.CUNMU,
        RecruitmentPool.Tier.XIANGSHI,
        RecruitmentPool.Tier.HUISHI,
        RecruitmentPool.Tier.DIANSHI,
    )
    assert recruitment_shared.CORE_POOL_TIERS == expected
