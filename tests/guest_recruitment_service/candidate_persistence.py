from __future__ import annotations

from types import SimpleNamespace

import pytest

import guests.services.recruitment_candidates as recruitment_candidate_service
from gameplay.services.manor.core import ensure_manor
from guests.models import GuestRarity, GuestTemplate, RecruitmentCandidate, RecruitmentPool


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
