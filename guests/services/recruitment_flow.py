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
    try:
        resolved_seed = int(seed if seed is not None else random.SystemRandom().randint(1, 2**31 - 1))
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"invalid recruitment seed: {seed!r}") from exc
    if resolved_seed <= 0:
        raise AssertionError(f"invalid recruitment seed: {seed!r}")
    return resolved_seed


def resolve_recruitment_cost(pool: RecruitmentPool) -> dict:
    raw_cost = pool.cost
    if raw_cost is None:
        return {}
    if isinstance(raw_cost, bool):
        raise AssertionError(f"invalid recruitment cost payload: {raw_cost!r}")
    # Accept mappings and iterable-of-pairs, but normalize contract errors into an explicit AssertionError.
    try:
        return dict(raw_cost)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"invalid recruitment cost payload: {raw_cost!r}") from exc


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
    try:
        resolved_duration_seconds = int(duration_seconds)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"invalid recruitment duration: {duration_seconds!r}") from exc
    if resolved_duration_seconds <= 0:
        raise AssertionError(f"invalid recruitment duration: {duration_seconds!r}")

    try:
        resolved_draw_count = int(draw_count)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"invalid recruitment draw count: {draw_count!r}") from exc
    if resolved_draw_count <= 0:
        raise AssertionError(f"invalid recruitment draw count: {draw_count!r}")

    try:
        resolved_seed = int(seed)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"invalid recruitment seed: {seed!r}") from exc
    if resolved_seed <= 0:
        raise AssertionError(f"invalid recruitment seed: {seed!r}")

    return recruitment_model.objects.create(
        manor=manor,
        pool=pool,
        cost=cost,
        draw_count=resolved_draw_count,
        duration_seconds=resolved_duration_seconds,
        seed=resolved_seed,
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
    try:
        resolved_result_count = int(result_count)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"invalid recruitment result count: {result_count!r}") from exc
    if resolved_result_count < 0:
        raise AssertionError(f"invalid recruitment result count: {result_count!r}")

    recruitment.status = GuestRecruitment.Status.COMPLETED
    recruitment.finished_at = current_time
    recruitment.result_count = resolved_result_count
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
