from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from core.exceptions import RecruitmentAlreadyInProgressError, RecruitmentDailyLimitExceededError

from ..models import GuestRecruitment

if TYPE_CHECKING:
    from gameplay.models import Manor

    from ..models import RecruitmentPool

InvalidateCacheFunc = Callable[[int | None], None]


def resolve_recruitment_seed(seed: int | None) -> int:
    return int(seed if seed is not None else random.SystemRandom().randint(1, 2**31 - 1))


def resolve_recruitment_cost(pool: RecruitmentPool) -> dict:
    return dict(pool.cost or {})


def create_pending_recruitment(
    *,
    recruitment_model: type[GuestRecruitment],
    manor: Manor,
    pool: RecruitmentPool,
    current_time: datetime,
    cost: dict[str, Any],
    draw_count: int,
    duration_seconds: int,
    seed: int,
) -> GuestRecruitment:
    resolved_duration_seconds = max(0, int(duration_seconds))
    return recruitment_model.objects.create(
        manor=manor,
        pool=pool,
        cost=cost,
        draw_count=max(1, int(draw_count)),
        duration_seconds=resolved_duration_seconds,
        seed=int(seed),
        complete_at=current_time + timedelta(seconds=resolved_duration_seconds),
    )


def mark_recruitment_failed_locked(
    recruitment: GuestRecruitment,
    *,
    current_time: datetime,
    reason: str,
    invalidate_cache: InvalidateCacheFunc,
) -> None:
    recruitment.status = GuestRecruitment.Status.FAILED
    recruitment.finished_at = current_time
    recruitment.error_message = str(reason)[:255]
    recruitment.save(update_fields=["status", "finished_at", "error_message"])
    invalidate_cache(getattr(recruitment, "manor_id", None))


def mark_recruitment_completed_locked(
    recruitment: GuestRecruitment,
    *,
    current_time: datetime,
    result_count: int,
    invalidate_cache: InvalidateCacheFunc,
) -> None:
    recruitment.status = GuestRecruitment.Status.COMPLETED
    recruitment.finished_at = current_time
    recruitment.result_count = max(0, int(result_count))
    recruitment.error_message = ""
    recruitment.save(update_fields=["status", "finished_at", "result_count", "error_message"])
    invalidate_cache(getattr(recruitment, "manor_id", None))


def validate_recruitment_start_allowed(
    *,
    locked_manor: Manor,
    pool: RecruitmentPool,
    current_time: datetime,
    has_active_guest_recruitment: Callable[[Manor], bool],
    daily_limit: int,
    count_pool_draws_today: Callable[..., int],
) -> None:
    if has_active_guest_recruitment(locked_manor):
        raise RecruitmentAlreadyInProgressError()

    draws_today = count_pool_draws_today(locked_manor.pk, int(pool.pk), now=current_time)
    if draws_today >= daily_limit:
        raise RecruitmentDailyLimitExceededError(pool.name, daily_limit)


def spend_recruitment_cost_if_needed(
    *,
    manor: Manor,
    cost: dict[str, Any],
    pool_name: str,
    spend_resources: Callable[..., object],
    recruit_cost_reason: object,
) -> None:
    if not cost:
        return
    spend_resources(
        manor,
        cost,
        note=f"卡池：{pool_name}",
        reason=recruit_cost_reason,
    )


def clear_manor_candidates(manor: Manor) -> None:
    manor.candidates.all().delete()
