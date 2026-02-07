import pytest
from django.core.management import call_command
from django.utils import timezone

from gameplay.services.manor import ensure_manor
from guests.models import MAX_GUEST_LEVEL, Guest, RecruitmentPool
from guests.services import finalize_candidate, recruit_guest, train_guest, reveal_candidate_rarity
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
    pool = RecruitmentPool.objects.get(key="tongshi")
    candidates = recruit_guest(manor, pool, seed=1)
    # 候选数量 = 卡池基础数量 + 酒馆加成（等级）
    expected_count = pool.draw_count + manor.tavern_recruitment_bonus
    assert len(candidates) == expected_count
    guest = finalize_candidate(candidates[0])
    assert Guest.objects.filter(pk=guest.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_train_guest_increases_level(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_train", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 2000
    manor.save()
    pool = RecruitmentPool.objects.get(key="tongshi")
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


@pytest.mark.django_db
def test_finalize_guest_training_is_idempotent(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_train2", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 2000
    manor.save()

    pool = RecruitmentPool.objects.get(key="tongshi")
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
    pool = RecruitmentPool.objects.get(key="tongshi")
    candidates = recruit_guest(manor, pool, seed=2)
    assert any(not c.rarity_revealed for c in candidates)

    updated = reveal_candidate_rarity(manor)
    assert updated == len(candidates)
    for candidate in manor.candidates.all():
        assert candidate.rarity_revealed is True
