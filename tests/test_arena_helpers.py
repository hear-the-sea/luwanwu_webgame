from __future__ import annotations

import random
from types import SimpleNamespace

import pytest
from django.utils import timezone

from core.exceptions import ArenaGuestSelectionError
from gameplay.services.arena.helpers import (
    build_round_pairings,
    calculate_ranked_entries,
    collect_round_outcome_entry_ids,
    normalize_guest_ids,
    resolve_random_reward_items,
    reward_for_rank,
    round_interval_delta,
    round_interval_seconds,
    today_bounds,
    today_local_date,
)
from gameplay.services.arena.rewards import ArenaRandomItemOption


def test_normalize_guest_ids_deduplicates_and_validates_limit():
    assert normalize_guest_ids([3, "1", 3, 2], max_guests_per_entry=4) == [3, 1, 2]

    with pytest.raises(ArenaGuestSelectionError, match="请至少选择 1 名门客"):
        normalize_guest_ids([], max_guests_per_entry=4)

    with pytest.raises(ArenaGuestSelectionError, match="每次最多选择 2 名门客"):
        normalize_guest_ids([1, 2, 3], max_guests_per_entry=2)


def test_round_interval_helpers_return_positive_values():
    assert round_interval_seconds(600) >= 1
    assert int(round_interval_delta(90).total_seconds()) == 90


def test_today_bounds_and_local_date_use_same_day():
    now = timezone.now()
    day_start, day_end = today_bounds(now=now)

    assert day_start < day_end
    assert day_start.date() == today_local_date(now=now)


def test_resolve_random_reward_items_aggregates_weighted_rolls(monkeypatch):
    options = (
        ArenaRandomItemOption(item_key="item_a", weight=3, amount=1),
        ArenaRandomItemOption(item_key="item_b", weight=1, amount=2),
    )
    rolls = iter([0.1, 0.9, 0.05])
    monkeypatch.setattr("gameplay.services.arena.helpers.random.random", lambda: next(rolls))

    grants = resolve_random_reward_items(options, 3)

    assert grants == {"item_a": 2, "item_b": 2}


def test_build_round_pairings_uses_shuffled_order():
    pairings = build_round_pairings([1, 2, 3, 4, 5], rng=random.Random(7))

    flattened = [entry_id for pair in pairings for entry_id in pair if entry_id is not None]
    assert sorted(flattened) == [1, 2, 3, 4, 5]
    assert len(pairings) == 3
    assert pairings[-1][1] is None


def test_calculate_ranked_entries_and_reward_for_rank():
    winner = SimpleNamespace(pk=2, id=2, matches_won=1, eliminated_round=2)
    third = SimpleNamespace(pk=3, id=3, matches_won=1, eliminated_round=1)
    second = SimpleNamespace(pk=1, id=1, matches_won=0, eliminated_round=2)

    ranked = calculate_ranked_entries([second, winner, third], winner)

    assert [entry.id for entry in ranked] == [2, 1, 3]
    assert reward_for_rank(1, base_participation_coins=30, rank_bonus_coins={1: 280}) == 310


def test_collect_round_outcome_entry_ids_deduplicates_winners_and_losers():
    matches = [
        SimpleNamespace(winner_entry_id=1, attacker_entry_id=1, defender_entry_id=2),
        SimpleNamespace(winner_entry_id=3, attacker_entry_id=4, defender_entry_id=3),
        SimpleNamespace(winner_entry_id=1, attacker_entry_id=1, defender_entry_id=5),
        SimpleNamespace(winner_entry_id=None, attacker_entry_id=6, defender_entry_id=7),
    ]

    winner_ids, loser_ids = collect_round_outcome_entry_ids(matches)

    assert winner_ids == [1, 3]
    assert loser_ids == [2, 4, 5]
