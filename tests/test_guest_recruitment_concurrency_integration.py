from __future__ import annotations

import threading

import pytest
from django.db import connection

from core.exceptions import RecruitmentAlreadyInProgressError
from gameplay.services.manor.core import ensure_manor
from guests.models import GuestRecruitment, RecruitmentPool
from guests.services.recruitment import start_guest_recruitment


@pytest.mark.integration
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
