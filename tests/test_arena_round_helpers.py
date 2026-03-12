from __future__ import annotations

from types import SimpleNamespace

from gameplay.models import ArenaMatch
from gameplay.services.arena.round_helpers import resolve_pending_round_matches


def test_resolve_pending_round_matches_marks_bye_when_defender_missing_id():
    saved = []
    attacker_entry = SimpleNamespace(id=1)
    pending = SimpleNamespace(attacker_entry_id=1, defender_entry_id=None)

    failed = resolve_pending_round_matches(
        pending_matches=[pending],
        entry_map={1: attacker_entry},
        round_number=1,
        now="now",
        bye_status=ArenaMatch.Status.BYE,
        forfeit_status=ArenaMatch.Status.FORFEIT,
        save_resolved_match=lambda **kwargs: saved.append(kwargs),
        resolve_match_locked=lambda **_kwargs: None,
        arena_match_resolution_error=RuntimeError,
    )

    assert failed is False
    assert saved[0]["status"] == ArenaMatch.Status.BYE
    assert saved[0]["note"] == "本轮轮空直接晋级"


def test_resolve_pending_round_matches_marks_forfeit_when_defender_entry_missing():
    saved = []
    attacker_entry = SimpleNamespace(id=1)
    pending = SimpleNamespace(attacker_entry_id=1, defender_entry_id=2)

    failed = resolve_pending_round_matches(
        pending_matches=[pending],
        entry_map={1: attacker_entry},
        round_number=1,
        now="now",
        bye_status=ArenaMatch.Status.BYE,
        forfeit_status=ArenaMatch.Status.FORFEIT,
        save_resolved_match=lambda **kwargs: saved.append(kwargs),
        resolve_match_locked=lambda **_kwargs: None,
        arena_match_resolution_error=RuntimeError,
    )

    assert failed is False
    assert saved[0]["status"] == ArenaMatch.Status.FORFEIT
    assert saved[0]["note"] == "对手报名数据缺失，自动晋级"


def test_resolve_pending_round_matches_flags_resolution_failure_without_raising():
    attacker_entry = SimpleNamespace(id=1)
    defender_entry = SimpleNamespace(id=2)
    pending = SimpleNamespace(
        attacker_entry_id=1,
        defender_entry_id=2,
        tournament="tournament",
        match_index=3,
    )

    failed = resolve_pending_round_matches(
        pending_matches=[pending],
        entry_map={1: attacker_entry, 2: defender_entry},
        round_number=2,
        now="now",
        bye_status=ArenaMatch.Status.BYE,
        forfeit_status=ArenaMatch.Status.FORFEIT,
        save_resolved_match=lambda **_kwargs: None,
        resolve_match_locked=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("retry")),
        arena_match_resolution_error=RuntimeError,
    )

    assert failed is True
