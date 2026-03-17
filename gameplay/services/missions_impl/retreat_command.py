from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone


def request_retreat(run, *, mission_run_model, schedule_mission_completion) -> None:
    now = timezone.now()
    with transaction.atomic():
        locked_run = mission_run_model.objects.select_for_update().filter(pk=run.pk).first()
        if not locked_run or locked_run.status != mission_run_model.Status.ACTIVE:
            raise ValueError("任务已结束，无法撤退")
        if locked_run.is_retreating:
            raise ValueError("任务已在撤退中")

        outbound_finish = locked_run.started_at + timedelta(seconds=locked_run.travel_time)
        if now >= outbound_finish:
            raise ValueError("已进入返程，无法撤退")

        elapsed = max(0, int((now - locked_run.started_at).total_seconds()))
        return_time = max(1, elapsed)
        locked_run.is_retreating = True
        locked_run.return_at = now + timedelta(seconds=return_time)
        locked_run.save(update_fields=["is_retreating", "return_at"])

    run.is_retreating = True
    run.return_at = locked_run.return_at
    schedule_mission_completion(locked_run)


def can_retreat(run, now=None) -> bool:
    if run.status != run.Status.ACTIVE:
        return False
    if run.is_retreating:
        return False
    now = now or timezone.now()
    outbound_finish = run.started_at + timedelta(seconds=run.travel_time)
    return now < outbound_finish
