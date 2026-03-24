from __future__ import annotations

import pytest
from django.utils import timezone

import guests.services.recruitment_queries as recruitment_query_service
import guests.services.recruitment_templates as recruitment_template_service
from core.exceptions import RecruitmentAlreadyInProgressError, RecruitmentDailyLimitExceededError
from guests.models import Guest, GuestRecruitment, GuestTemplate, RecruitmentCandidate, RecruitmentPool
from guests.services.recruitment import recruit_guest, start_guest_recruitment
from guests.services.recruitment_guests import finalize_candidate
from guests.services.recruitment_queries import get_pool_recruitment_duration_seconds
from tests.guests.support import create_manor


@pytest.mark.django_db
def test_recruit_guest_creates_record(game_data, django_user_model, load_guest_data):
    manor = create_manor(django_user_model, username="player_guest", silver=2000)
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidates = recruit_guest(manor, pool, seed=1)
    expected_count = pool.draw_count + manor.tavern_recruitment_bonus
    assert len(candidates) == expected_count
    guest = finalize_candidate(candidates[0])
    assert Guest.objects.filter(pk=guest.pk).exists()
    assert guest.training_complete_at is not None
    assert guest.training_target_level == 2


@pytest.mark.django_db
def test_recruit_guest_preloads_template_data_once_per_batch(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    manor = create_manor(django_user_model, username="player_guest_cache", silver=500000, grain=500000)
    pool = RecruitmentPool.objects.get(key="cunmu")
    pool.draw_count = 30
    pool.save(update_fields=["draw_count"])

    calls = {"by_rarity": 0, "hermit": 0}
    original_by_rarity = recruitment_template_service._get_recruitable_templates_by_rarity
    original_hermit = recruitment_template_service._get_hermit_templates

    def _counted_by_rarity():
        calls["by_rarity"] += 1
        return original_by_rarity()

    def _counted_hermit():
        calls["hermit"] += 1
        return original_hermit()

    monkeypatch.setattr(recruitment_template_service, "_get_recruitable_templates_by_rarity", _counted_by_rarity)
    monkeypatch.setattr(recruitment_template_service, "_get_hermit_templates", _counted_hermit)

    candidates = recruit_guest(manor, pool, seed=3)

    assert len(candidates) == pool.draw_count + manor.tavern_recruitment_bonus
    assert calls["by_rarity"] == 1
    assert calls["hermit"] == 1


@pytest.mark.django_db
def test_start_guest_recruitment_creates_pending_and_deducts_cost(game_data, django_user_model, load_guest_data):
    manor = create_manor(django_user_model, username="player_recruit_async_start", silver=20000)

    pool = RecruitmentPool.objects.get(key="cunmu")
    template = GuestTemplate.objects.filter(recruitable=True).first()
    assert template is not None
    RecruitmentCandidate.objects.create(
        manor=manor,
        pool=pool,
        template=template,
        display_name=template.name,
        rarity=template.rarity,
        archetype=template.archetype,
    )

    before_silver = manor.silver
    recruitment = start_guest_recruitment(manor, pool, seed=1234)

    manor.refresh_from_db()
    recruitment.refresh_from_db()
    expected_cost = int((pool.cost or {}).get("silver", 0))
    assert manor.silver == before_silver - expected_cost
    assert recruitment.status == GuestRecruitment.Status.PENDING
    assert recruitment.duration_seconds > 0
    assert recruitment.draw_count == pool.draw_count + manor.tavern_recruitment_bonus
    assert manor.candidates.count() == 0


@pytest.mark.django_db
def test_guest_recruitment_duration_respects_game_time_multiplier(
    game_data, django_user_model, load_guest_data, settings
):
    settings.GAME_TIME_MULTIPLIER = 100

    manor = create_manor(django_user_model, username="player_recruit_time_scale", silver=20000)
    pool = RecruitmentPool.objects.get(key="cunmu")
    base_duration = int(getattr(pool, "cooldown_seconds", 0) or 0)
    expected_duration = max(1, int(base_duration / 100)) if base_duration > 0 else 0

    assert get_pool_recruitment_duration_seconds(pool) == expected_duration

    recruitment = start_guest_recruitment(manor, pool, seed=7)
    assert recruitment.duration_seconds == expected_duration


@pytest.mark.django_db
def test_start_guest_recruitment_rejects_when_active_exists(game_data, django_user_model, load_guest_data):
    manor = create_manor(django_user_model, username="player_recruit_async_lock", silver=50000)
    pool = RecruitmentPool.objects.get(key="cunmu")

    start_guest_recruitment(manor, pool, seed=1)

    with pytest.raises(RecruitmentAlreadyInProgressError, match="已有招募正在进行中"):
        start_guest_recruitment(manor, pool, seed=2)


@pytest.mark.django_db
def test_start_guest_recruitment_rejects_when_pool_daily_limit_reached(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    manor = create_manor(django_user_model, username="player_recruit_daily_limit", silver=500000, grain=500000)
    pool = RecruitmentPool.objects.get(key="cunmu")

    monkeypatch.setattr(recruitment_query_service, "_get_pool_daily_draw_limit", lambda: 2)
    now = timezone.now()
    GuestRecruitment.objects.create(
        manor=manor,
        pool=pool,
        cost={},
        draw_count=1,
        duration_seconds=0,
        seed=1,
        status=GuestRecruitment.Status.COMPLETED,
        complete_at=now,
        finished_at=now,
    )
    GuestRecruitment.objects.create(
        manor=manor,
        pool=pool,
        cost={},
        draw_count=1,
        duration_seconds=0,
        seed=2,
        status=GuestRecruitment.Status.COMPLETED,
        complete_at=now,
        finished_at=now,
    )

    with pytest.raises(RecruitmentDailyLimitExceededError, match="今日招募次数已达上限"):
        start_guest_recruitment(manor, pool, seed=3)


@pytest.mark.django_db
def test_start_guest_recruitment_daily_limit_is_per_pool(game_data, django_user_model, load_guest_data, monkeypatch):
    manor = create_manor(django_user_model, username="player_recruit_daily_per_pool", silver=500000, grain=500000)
    first_pool = RecruitmentPool.objects.get(key="cunmu")
    second_pool = RecruitmentPool.objects.exclude(pk=first_pool.pk).order_by("id").first()
    assert second_pool is not None
    second_pool.cost = {}
    second_pool.save(update_fields=["cost"])

    monkeypatch.setattr(recruitment_query_service, "_get_pool_daily_draw_limit", lambda: 1)
    now = timezone.now()
    GuestRecruitment.objects.create(
        manor=manor,
        pool=first_pool,
        cost={},
        draw_count=1,
        duration_seconds=0,
        seed=1,
        status=GuestRecruitment.Status.COMPLETED,
        complete_at=now,
        finished_at=now,
    )

    recruitment = start_guest_recruitment(manor, second_pool, seed=2)
    assert recruitment.pool_id == second_pool.id
    assert recruitment.status == GuestRecruitment.Status.PENDING
