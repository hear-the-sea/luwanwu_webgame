from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from core.exceptions import GuestCapacityFullError
from guests.services import recruitment_finalize_helpers


def test_split_candidates_by_capacity_splits_success_and_failed_lists():
    candidates = [1, 2, 3]

    success, failed = recruitment_finalize_helpers.split_candidates_by_capacity(candidates, available_slots=2)

    assert success == [1, 2]
    assert failed == [3]


def test_build_guest_from_candidate_uses_custom_name_for_common_non_hermit():
    captured = {}
    candidate = SimpleNamespace(
        template=SimpleNamespace(is_hermit=False),
        rarity="gray",
        archetype="civil",
        display_name="候选甲",
    )

    result = recruitment_finalize_helpers.build_guest_from_candidate(
        candidate=candidate,
        manor="manor",
        rng=random.Random(1),
        create_guest_func=lambda **kwargs: captured.update(kwargs) or "guest",
        should_use_candidate_custom_name=lambda _candidate, _template: True,
    )

    assert result == "guest"
    assert captured["custom_name"] == "候选甲"


def test_ensure_guest_capacity_available_raises_when_full():
    manor = SimpleNamespace(guest_capacity=3, guests=SimpleNamespace(count=lambda: 3))

    with pytest.raises(GuestCapacityFullError):
        recruitment_finalize_helpers.ensure_guest_capacity_available(manor)


def test_validate_retainer_candidate_identity_rejects_missing_ids():
    with pytest.raises(ValueError, match="候选门客不存在或已处理"):
        recruitment_finalize_helpers.validate_retainer_candidate_identity(SimpleNamespace(pk=None, manor_id=None))
