import builtins

import pytest
from django.core.management import call_command
from django.utils import timezone

import guests.services.recruitment_queries as recruitment_query_service
import guests.services.recruitment_templates as recruitment_template_service
from core.config import GUEST
from core.exceptions import (
    GuestNotIdleError,
    MessageError,
    NoTemplateAvailableError,
    RecruitmentAlreadyInProgressError,
    RecruitmentCandidateStateError,
    RecruitmentDailyLimitExceededError,
    RetainerCapacityFullError,
)
from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestRecruitment, GuestStatus, GuestTemplate, RecruitmentCandidate, RecruitmentPool
from guests.services import recruitment_followups as recruitment_followups_service
from guests.services.recruitment import (
    finalize_guest_recruitment,
    recruit_guest,
    reveal_candidate_rarity,
    start_guest_recruitment,
)
from guests.services.recruitment_guests import convert_candidate_to_retainer, finalize_candidate
from guests.services.recruitment_queries import get_pool_recruitment_duration_seconds
from guests.services.training import finalize_guest_training, train_guest

MAX_GUEST_LEVEL = int(GUEST.MAX_LEVEL)


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
    assert guest.training_complete_at is not None
    assert guest.training_target_level == 2


@pytest.mark.django_db
def test_recruit_guest_preloads_template_data_once_per_batch(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    user = django_user_model.objects.create_user(username="player_guest_cache", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])

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

    with pytest.raises(RecruitmentAlreadyInProgressError, match="已有招募正在进行中"):
        start_guest_recruitment(manor, pool, seed=2)


@pytest.mark.django_db
def test_start_guest_recruitment_rejects_when_pool_daily_limit_reached(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    user = django_user_model.objects.create_user(username="player_recruit_daily_limit", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])
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
    user = django_user_model.objects.create_user(username="player_recruit_daily_per_pool", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])
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


@pytest.mark.django_db
def test_finalize_guest_recruitment_keeps_success_when_notification_fails(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    user = django_user_model.objects.create_user(username="player_recruit_async_notify_fail", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 50000
    manor.save(update_fields=["silver"])
    pool = RecruitmentPool.objects.get(key="cunmu")

    recruitment = start_guest_recruitment(manor, pool, seed=99)
    recruitment.complete_at = timezone.now() - timezone.timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])

    monkeypatch.setattr(
        "guests.services.recruitment_followups.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MessageError("message backend down")),
    )
    monkeypatch.setattr(
        "guests.services.recruitment_followups.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("ws backend down")),
    )

    assert finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=True) is True

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert manor.candidates.count() == recruitment.draw_count


@pytest.mark.django_db
def test_finalize_guest_recruitment_runtime_marker_notification_error_bubbles_up(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    user = django_user_model.objects.create_user(
        username="player_recruit_async_notify_runtime_backend", password="pass123"
    )
    manor = ensure_manor(user)
    manor.silver = 50000
    manor.save(update_fields=["silver"])
    pool = RecruitmentPool.objects.get(key="cunmu")

    recruitment = start_guest_recruitment(manor, pool, seed=109)
    recruitment.complete_at = timezone.now() - timezone.timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])

    monkeypatch.setattr(
        "guests.services.recruitment_followups.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=True)

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert manor.candidates.count() == recruitment.draw_count


@pytest.mark.django_db
def test_finalize_guest_recruitment_notification_programming_error_bubbles_up(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    user = django_user_model.objects.create_user(
        username="player_recruit_async_notify_program_error", password="pass123"
    )
    manor = ensure_manor(user)
    manor.silver = 50000
    manor.save(update_fields=["silver"])
    pool = RecruitmentPool.objects.get(key="cunmu")

    recruitment = start_guest_recruitment(manor, pool, seed=199)
    recruitment.complete_at = timezone.now() - timezone.timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])

    monkeypatch.setattr(
        "guests.services.recruitment_followups.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken message contract")),
    )

    with pytest.raises(AssertionError, match="broken message contract"):
        finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=True)

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert manor.candidates.count() == recruitment.draw_count


@pytest.mark.django_db
def test_finalize_guest_recruitment_marks_failed_for_known_recruitment_error(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    user = django_user_model.objects.create_user(username="player_recruit_async_known_error", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 50000
    manor.save(update_fields=["silver"])
    pool = RecruitmentPool.objects.get(key="cunmu")

    recruitment = start_guest_recruitment(manor, pool, seed=808)
    recruitment.complete_at = timezone.now() - timezone.timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])

    monkeypatch.setattr(
        "guests.services.recruitment._build_recruitment_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(NoTemplateAvailableError()),
    )

    assert finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=False) is False

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.FAILED
    assert "缺少可用的门客模板" in recruitment.error_message


@pytest.mark.django_db
def test_finalize_guest_recruitment_does_not_mask_contract_error(
    game_data, django_user_model, load_guest_data, monkeypatch
):
    user = django_user_model.objects.create_user(username="player_recruit_async_contract_error", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 50000
    manor.save(update_fields=["silver"])
    pool = RecruitmentPool.objects.get(key="cunmu")

    recruitment = start_guest_recruitment(manor, pool, seed=909)
    recruitment.complete_at = timezone.now() - timezone.timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])

    monkeypatch.setattr(
        "guests.services.recruitment._build_recruitment_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("invalid recruitment contract")),
    )

    with pytest.raises(AssertionError, match="invalid recruitment contract"):
        finalize_guest_recruitment(recruitment, now=timezone.now(), send_notification=False)

    recruitment.refresh_from_db()
    assert recruitment.status == GuestRecruitment.Status.PENDING
    assert recruitment.error_message == ""


def test_schedule_guest_recruitment_completion_runs_after_commit(monkeypatch):
    callbacks = []
    dispatched = []

    monkeypatch.setattr(
        recruitment_followups_service.transaction,
        "on_commit",
        lambda callback: callbacks.append(callback),
    )
    monkeypatch.setattr(
        "guests.tasks.complete_guest_recruitment",
        type("_Task", (), {"name": "guests.complete_recruitment"})(),
    )
    monkeypatch.setattr(
        recruitment_followups_service,
        "safe_apply_async",
        lambda task, *, args, countdown, **_kwargs: dispatched.append(
            {
                "task_name": getattr(task, "name", str(task)),
                "args": args,
                "countdown": countdown,
            }
        )
        or True,
    )

    recruitment = type("_Recruitment", (), {"id": 17, "manor_id": 3, "pool_id": 5})()

    recruitment_followups_service.schedule_guest_recruitment_completion(
        recruitment,
        45,
        logger=recruitment_followups_service.logging.getLogger(__name__),
    )

    assert len(callbacks) == 1
    assert dispatched == []

    callbacks[0]()

    assert dispatched == [
        {
            "task_name": "guests.complete_recruitment",
            "args": [17],
            "countdown": 45,
        }
    ]


def test_schedule_guest_recruitment_completion_rejects_negative_eta():
    recruitment = type("_Recruitment", (), {"id": 17, "manor_id": 3, "pool_id": 5})()

    with pytest.raises(AssertionError, match="invalid guest recruitment completion eta"):
        recruitment_followups_service.schedule_guest_recruitment_completion(
            recruitment,
            -1,
            logger=recruitment_followups_service.logging.getLogger(__name__),
        )


def test_schedule_guest_recruitment_completion_unexpected_import_error_bubbles_up(monkeypatch):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "guests.tasks":
            raise RuntimeError("broken task module")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    recruitment = type("_Recruitment", (), {"id": 17, "manor_id": 3, "pool_id": 5})()

    with pytest.raises(RuntimeError, match="broken task module"):
        recruitment_followups_service.schedule_guest_recruitment_completion(
            recruitment,
            45,
            logger=recruitment_followups_service.logging.getLogger(__name__),
        )


def test_schedule_guest_recruitment_completion_nested_import_error_bubbles_up(monkeypatch):
    original_import = builtins.__import__

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "guests.tasks":
            exc = ModuleNotFoundError("No module named 'redis'")
            exc.name = "redis"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    recruitment = type("_Recruitment", (), {"id": 18, "manor_id": 4, "pool_id": 6})()

    with pytest.raises(ModuleNotFoundError, match="redis"):
        recruitment_followups_service.schedule_guest_recruitment_completion(
            recruitment,
            30,
            logger=recruitment_followups_service.logging.getLogger(__name__),
        )


def test_schedule_guest_recruitment_completion_missing_target_module_degrades(monkeypatch):
    original_import = builtins.__import__
    callbacks = []

    def _raising_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "guests.tasks":
            exc = ModuleNotFoundError("No module named 'guests.tasks'")
            exc.name = "guests.tasks"
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raising_import)
    monkeypatch.setattr(
        recruitment_followups_service.transaction, "on_commit", lambda callback: callbacks.append(callback)
    )

    recruitment = type("_Recruitment", (), {"id": 19, "manor_id": 5, "pool_id": 7})()

    recruitment_followups_service.schedule_guest_recruitment_completion(
        recruitment,
        20,
        logger=recruitment_followups_service.logging.getLogger(__name__),
    )

    assert callbacks == []


@pytest.mark.django_db(transaction=True)
def test_train_guest_increases_level(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_train", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 2000
    manor.save()
    pool = RecruitmentPool.objects.get(key="cunmu")
    candidates = recruit_guest(manor, pool, seed=1)
    guest = finalize_candidate(candidates[0])
    guest.training_complete_at = None
    guest.training_target_level = 0
    guest.save(update_fields=["training_complete_at", "training_target_level"])
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

    with pytest.raises(RecruitmentCandidateStateError, match="候选门客不存在或已处理"):
        convert_candidate_to_retainer(candidate)

    manor.refresh_from_db()
    assert manor.retainer_count == before_count
    assert RecruitmentCandidate.objects.filter(pk=candidate_id).exists() is False


@pytest.mark.django_db
def test_finalize_candidate_rejects_missing_candidate(game_data, django_user_model, load_guest_data):
    user = django_user_model.objects.create_user(username="player_finalize_missing_candidate", password="pass123")
    manor = ensure_manor(user)
    manor.grain = manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=7)[0]
    candidate_id = candidate.pk

    candidate.delete()

    with pytest.raises(RecruitmentCandidateStateError, match="候选门客不存在或已处理"):
        finalize_candidate(candidate)

    assert RecruitmentCandidate.objects.filter(pk=candidate_id).exists() is False
    assert Guest.objects.filter(manor=manor).count() == 0


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
