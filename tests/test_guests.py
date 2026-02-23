import pytest
from django.core.management import call_command
from django.utils import timezone

from core.exceptions import GuestNotIdleError, RetainerCapacityFullError
from gameplay.services.manor.core import ensure_manor
from guests.models import (
    MAX_GUEST_LEVEL,
    Guest,
    GuestRecruitment,
    GuestStatus,
    GuestTemplate,
    RecruitmentCandidate,
    RecruitmentPool,
)
from guests.services import (
    convert_candidate_to_retainer,
    finalize_candidate,
    finalize_guest_recruitment,
    get_pool_recruitment_duration_seconds,
    recruit_guest,
    reveal_candidate_rarity,
    start_guest_recruitment,
    train_guest,
)
from guests.services.training import finalize_guest_training


@pytest.fixture
def load_guest_data(db):
    """Ensure guest templates and pools are loaded."""
    if not RecruitmentPool.objects.exists():
        call_command("load_guest_templates", verbosity=0, skip_images=True)


@pytest.mark.django_db
def test_recruit_guest_creates_record(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_guest", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 2000
    manor.save()
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidates = recruit_guest(manor, pool, seed=1)
    # 候选数量 = 卡池基础数量 + 酒馆加成（等级）
    expected_count = pool.draw_count + manor.tavern_recruitment_bonus
    assert len(candidates) == expected_count
    guest = finalize_candidate(candidates[0])
    assert Guest.objects.filter(pk=guest.pk).exists()


@pytest.mark.django_db
def test_start_guest_recruitment_creates_pending_and_deducts_cost(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_recruit_async_start", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 20000
    manor.save(update_fields=["silver"])

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

    user = django_user_model.objects.create_user(username="player_recruit_time_scale", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 20000
    manor.save(update_fields=["silver"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    base_duration = int(getattr(pool, "cooldown_seconds", 0) or 0)
    expected_duration = max(1, int(base_duration / 100)) if base_duration > 0 else 0

    assert get_pool_recruitment_duration_seconds(pool) == expected_duration

    recruitment = start_guest_recruitment(manor, pool, seed=7)
    assert recruitment.duration_seconds == expected_duration


@pytest.mark.django_db
def test_start_guest_recruitment_rejects_when_active_exists(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_recruit_async_lock", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 50000
    manor.save(update_fields=["silver"])
    pool = RecruitmentPool.objects.get(key="cunmu")

    start_guest_recruitment(manor, pool, seed=1)

    with pytest.raises(ValueError, match="已有招募正在进行中"):
        start_guest_recruitment(manor, pool, seed=2)


@pytest.mark.django_db
def test_finalize_guest_recruitment_generates_candidates(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_recruit_async_finalize", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 50000
    manor.save(update_fields=["silver"])
    pool = RecruitmentPool.objects.get(key="cunmu")

    recruitment = start_guest_recruitment(manor, pool, seed=42)
    recruitment.complete_at = timezone.now() - timezone.timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])

    assert finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=False) is True

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert manor.candidates.count() == recruitment.draw_count


@pytest.mark.django_db(transaction=True)
def test_train_guest_increases_level(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_train", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 2000
    manor.save()
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidates = recruit_guest(manor, pool, seed=1)
    guest = finalize_candidate(candidates[0])
    guest.manor.grain = guest.manor.silver = 5000
    guest.manor.save()
    train_guest(guest, levels=2)
    # 手动完成训练（测试环境中 Celery 任务不可用）
    guest.refresh_from_db()
    finalize_guest_training(guest, now=guest.training_complete_at)
    guest.refresh_from_db()
    assert guest.level == 3


@pytest.mark.django_db(transaction=True)
def test_train_guest_rejects_non_idle(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_train_non_idle", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 5000
    manor.grain = 5000
    manor.save(update_fields=["silver", "grain"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidates = recruit_guest(manor, pool, seed=2)
    guest = finalize_candidate(candidates[0])
    guest.status = GuestStatus.DEPLOYED
    guest.save(update_fields=["status"])

    with pytest.raises(GuestNotIdleError):
        train_guest(guest, levels=1)


@pytest.mark.django_db
def test_finalize_guest_training_is_idempotent(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_train2", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 2000
    manor.save()

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidates = recruit_guest(manor, pool, seed=1)
    guest = finalize_candidate(candidates[0])

    guest.manor.grain = guest.manor.silver = 500000
    guest.manor.save(update_fields=["grain", "silver"])

    # 将门客置为接近满级，避免 finalize 后自动开启下一轮训练影响幂等断言
    guest.level = MAX_GUEST_LEVEL - 1
    guest.training_complete_at = None
    guest.training_target_level = 0
    guest.save(update_fields=["level", "training_complete_at", "training_target_level"])

    train_guest(guest, levels=1)
    guest.refresh_from_db()
    completed_at = guest.training_complete_at
    assert completed_at is not None

    first = finalize_guest_training(guest, now=completed_at)
    guest.refresh_from_db()
    level_after = guest.level

    second = finalize_guest_training(guest, now=timezone.now())
    guest.refresh_from_db()

    assert first is True
    assert second is False
    assert guest.level == MAX_GUEST_LEVEL
    assert guest.level == level_after


@pytest.mark.django_db
def test_reveal_candidate_rarity_marks_all(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_magnify", password="pass123")
    manor = ensure_manor(user)
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidates = recruit_guest(manor, pool, seed=2)
    assert any(not c.rarity_revealed for c in candidates)

    updated = reveal_candidate_rarity(manor)
    assert updated == len(candidates)
    for candidate in manor.candidates.all():
        assert candidate.rarity_revealed is True


@pytest.mark.django_db
def test_convert_candidate_to_retainer_rejects_missing_candidate(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_retainer_missing_candidate", password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=1)[0]
    candidate_id = candidate.pk
    before_count = manor.retainer_count

    candidate.delete()

    with pytest.raises(ValueError, match="候选门客不存在或已处理"):
        convert_candidate_to_retainer(candidate)

    manor.refresh_from_db()
    assert manor.retainer_count == before_count
    assert RecruitmentCandidate.objects.filter(pk=candidate_id).exists() is False


@pytest.mark.django_db
def test_convert_candidate_to_retainer_rejects_when_capacity_full(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_retainer_capacity_full", password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.retainer_count = manor.retainer_capacity
    manor.save(update_fields=["grain", "silver", "retainer_count"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=1)[0]

    with pytest.raises(RetainerCapacityFullError):
        convert_candidate_to_retainer(candidate)

    manor.refresh_from_db()
    assert manor.retainer_count == manor.retainer_capacity
    assert RecruitmentCandidate.objects.filter(pk=candidate.pk).exists()
