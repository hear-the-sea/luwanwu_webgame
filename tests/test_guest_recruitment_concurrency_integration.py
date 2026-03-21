from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from core.exceptions import RecruitmentAlreadyInProgressError, RecruitmentCandidateStateError
from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestRecruitment, RecruitmentCandidate, RecruitmentPool, RecruitmentRecord
from guests.services.recruitment import (
    finalize_guest_recruitment,
    recruit_guest,
    refresh_guest_recruitments,
    start_guest_recruitment,
)
from guests.services.recruitment_guests import finalize_candidate

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("load_guest_data")]


@pytest.mark.django_db(transaction=True)
def test_start_guest_recruitment_concurrent_requests_allow_only_one_pending(game_data, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    user = django_user_model.objects.create_user(username="guest_recruit_concurrent_user", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[Exception] = []

    def _worker(seed: int) -> None:
        try:
            local_manor = type(manor).objects.get(pk=manor.pk)
            local_pool = RecruitmentPool.objects.get(pk=pool.pk)
            barrier.wait(timeout=5)
            recruitment = start_guest_recruitment(local_manor, local_pool, seed=seed)
            results.append(recruitment.pk)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [
        threading.Thread(target=_worker, args=(101,)),
        threading.Thread(target=_worker, args=(202,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], RecruitmentAlreadyInProgressError)
    assert GuestRecruitment.objects.filter(manor=manor, status=GuestRecruitment.Status.PENDING).count() == 1


@pytest.mark.django_db(transaction=True)
def test_finalize_guest_recruitment_concurrent_requests_only_one_completes(game_data, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    user = django_user_model.objects.create_user(username="guest_recruit_finalize_user", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    recruitment = start_guest_recruitment(manor, pool, seed=303)
    recruitment.complete_at = timezone.now() - timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])

    barrier = threading.Barrier(2)
    results: list[bool] = []
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            local_recruitment = GuestRecruitment.objects.get(pk=recruitment.pk)
            barrier.wait(timeout=5)
            results.append(finalize_guest_recruitment(local_recruitment, now=timezone.now()))
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    recruitment.refresh_from_db()

    assert sorted(results) == [False, True]
    assert errors == []
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert recruitment.result_count == RecruitmentCandidate.objects.filter(manor=manor).count()
    assert recruitment.result_count > 0


@pytest.mark.django_db(transaction=True)
def test_finalize_candidate_concurrent_requests_create_only_one_guest(game_data, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    user = django_user_model.objects.create_user(username="guest_candidate_finalize_user", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    candidate = recruit_guest(manor, pool, seed=404)[0]

    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            local_candidate = RecruitmentCandidate.objects.get(pk=candidate.pk)
            barrier.wait(timeout=5)
            guest = finalize_candidate(local_candidate)
            results.append(guest.pk)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], RecruitmentCandidateStateError)
    assert Guest.objects.filter(manor=manor).count() == 1
    assert RecruitmentRecord.objects.filter(manor=manor).count() == 1
    assert RecruitmentCandidate.objects.filter(pk=candidate.pk).exists() is False


@pytest.mark.django_db(transaction=True)
def test_refresh_guest_recruitments_concurrent_with_finalize_guest_recruitment_completes_only_once(
    game_data, django_user_model, monkeypatch
):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    user = django_user_model.objects.create_user(username="guest_recruit_refresh_finalize_user", password="pass123")
    manor = ensure_manor(user)
    manor.silver = 500000
    manor.grain = 500000
    manor.save(update_fields=["silver", "grain"])

    pool = RecruitmentPool.objects.get(key="cunmu")
    recruitment = start_guest_recruitment(manor, pool, seed=505)
    recruitment.complete_at = timezone.now() - timedelta(seconds=1)
    recruitment.save(update_fields=["complete_at"])

    built: list[int] = []
    sent_notifications: list[int] = []
    build_lock = threading.Lock()
    notify_lock = threading.Lock()

    def _build_candidates(_manor, _pool, **_kwargs):
        with build_lock:
            built.append(recruitment.pk)
        return [object(), object()]

    def _record_notification(*, recruitment_id=None, **_kwargs):
        with notify_lock:
            if recruitment_id is not None:
                sent_notifications.append(int(recruitment_id))

    monkeypatch.setattr("guests.services.recruitment._build_recruitment_candidates", _build_candidates)
    monkeypatch.setattr(
        "guests.services.recruitment._send_recruitment_completion_notification",
        _record_notification,
    )

    barrier = threading.Barrier(2)
    errors: list[Exception] = []
    finalize_results: list[bool] = []
    refresh_results: list[int] = []

    def _finalize_worker() -> None:
        try:
            local_recruitment = GuestRecruitment.objects.get(pk=recruitment.pk)
            barrier.wait(timeout=5)
            finalize_results.append(finalize_guest_recruitment(local_recruitment, now=timezone.now()))
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    def _refresh_worker() -> None:
        try:
            local_manor = type(manor).objects.get(pk=manor.pk)
            barrier.wait(timeout=5)
            refresh_results.append(refresh_guest_recruitments(local_manor))
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [
        threading.Thread(target=_finalize_worker),
        threading.Thread(target=_refresh_worker),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    recruitment.refresh_from_db()

    assert errors == []
    assert len(finalize_results) == 1
    assert len(refresh_results) == 1
    assert int(finalize_results[0]) + refresh_results[0] == 1
    assert built == [recruitment.pk]
    assert recruitment.status == GuestRecruitment.Status.COMPLETED
    assert recruitment.result_count == 2
    assert sent_notifications in [[], [recruitment.pk]]
