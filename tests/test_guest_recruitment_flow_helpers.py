from __future__ import annotations

import random
from types import SimpleNamespace

from guests.models import GuestRarity
from guests.services import recruitment_candidates, recruitment_flow


def test_resolve_recruitment_seed_keeps_explicit_value():
    assert recruitment_flow.resolve_recruitment_seed(12345) == 12345


def test_resolve_recruitment_cost_returns_copy():
    pool = SimpleNamespace(cost={"silver": 100})

    resolved = recruitment_flow.resolve_recruitment_cost(pool)
    resolved["silver"] = 200

    assert pool.cost["silver"] == 100


def test_resolve_candidate_draw_count_includes_tavern_bonus():
    pool = SimpleNamespace(draw_count=2)
    manor = SimpleNamespace(tavern_recruitment_bonus=3)

    assert recruitment_candidates.resolve_candidate_draw_count(pool=pool, manor=manor, total_draw_count=None) == 5


def test_build_candidate_display_name_uses_random_name_for_common_candidates():
    template = SimpleNamespace(name="模板名", rarity=GuestRarity.GRAY, is_hermit=False)

    result = recruitment_candidates.build_candidate_display_name(
        template,
        random.Random(1),
        generate_random_name=lambda _rng: "随机名",
    )

    assert result == "随机名"


def test_build_candidate_display_name_keeps_template_name_for_hermit():
    template = SimpleNamespace(name="隐士", rarity=GuestRarity.BLACK, is_hermit=True)

    result = recruitment_candidates.build_candidate_display_name(
        template,
        random.Random(1),
        generate_random_name=lambda _rng: "随机名",
    )

    assert result == "隐士"


def test_candidate_template_rules_match_repeat_and_reveal_design():
    red_template = SimpleNamespace(id=1, rarity=GuestRarity.RED, is_hermit=False)
    hermit_template = SimpleNamespace(id=2, rarity=GuestRarity.BLACK, is_hermit=True)

    assert recruitment_candidates.should_reveal_candidate_rarity(red_template) is True
    assert (
        recruitment_candidates.should_exclude_candidate_template(
            hermit_template,
            non_repeatable_rarities=frozenset({GuestRarity.GREEN, GuestRarity.BLUE, GuestRarity.RED}),
        )
        is True
    )
