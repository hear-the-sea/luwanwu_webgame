from __future__ import annotations

import random
from types import SimpleNamespace

import guests.services.recruitment_candidates as recruitment_candidates
import guests.services.recruitment_flow as recruitment_flow
from core.exceptions import RecruitmentAlreadyInProgressError, RecruitmentDailyLimitExceededError
from guests.models import GuestRarity


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


def test_validate_recruitment_start_allowed_rejects_active_recruitment():
    manor = SimpleNamespace(pk=1)
    pool = SimpleNamespace(pk=2, name="村募")

    with __import__("pytest").raises(RecruitmentAlreadyInProgressError, match="已有招募正在进行中"):
        recruitment_flow.validate_recruitment_start_allowed(
            locked_manor=manor,
            pool=pool,
            current_time="now",
            has_active_guest_recruitment=lambda _manor: True,
            daily_limit=3,
            count_pool_draws_today=lambda *_args, **_kwargs: 0,
        )


def test_validate_recruitment_start_allowed_rejects_daily_limit():
    manor = SimpleNamespace(pk=1)
    pool = SimpleNamespace(pk=2, name="村募")

    with __import__("pytest").raises(RecruitmentDailyLimitExceededError, match="今日招募次数已达上限"):
        recruitment_flow.validate_recruitment_start_allowed(
            locked_manor=manor,
            pool=pool,
            current_time="now",
            has_active_guest_recruitment=lambda _manor: False,
            daily_limit=2,
            count_pool_draws_today=lambda *_args, **_kwargs: 2,
        )


def test_spend_recruitment_cost_if_needed_skips_empty_cost_and_formats_note():
    calls = []

    recruitment_flow.spend_recruitment_cost_if_needed(
        manor="manor",
        cost={},
        pool_name="村募",
        spend_resources=lambda *args, **kwargs: calls.append((args, kwargs)),
        recruit_cost_reason="reason",
    )
    assert calls == []

    recruitment_flow.spend_recruitment_cost_if_needed(
        manor="manor",
        cost={"silver": 100},
        pool_name="村募",
        spend_resources=lambda *args, **kwargs: calls.append((args, kwargs)),
        recruit_cost_reason="reason",
    )
    assert calls[0][0] == ("manor", {"silver": 100})
    assert calls[0][1]["note"] == "卡池：村募"
    assert calls[0][1]["reason"] == "reason"


def test_load_candidate_generation_context_uses_injected_loaders_once():
    calls = {"by_rarity": 0, "hermit": 0, "excluded": 0}

    class _Entries:
        def select_related(self, *_args, **_kwargs):
            return ["entry-1"]

    context = recruitment_candidates.load_candidate_generation_context(
        manor=SimpleNamespace(tavern_recruitment_bonus=1),
        pool=SimpleNamespace(draw_count=2, entries=_Entries()),
        seed=7,
        total_draw_count=None,
        get_recruitable_templates_by_rarity=lambda: calls.__setitem__("by_rarity", calls["by_rarity"] + 1)
        or {"gray": []},
        get_hermit_templates=lambda: calls.__setitem__("hermit", calls["hermit"] + 1) or [],
        get_excluded_template_ids=lambda _manor: calls.__setitem__("excluded", calls["excluded"] + 1) or {1, 2},
    )

    assert context["pool_entries"] == ["entry-1"]
    assert context["resolved_draw_count"] == 3
    assert context["excluded_ids"] == {1, 2}
    assert calls == {"by_rarity": 1, "hermit": 1, "excluded": 1}
