from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from django.db import transaction

from common.utils.celery import safe_apply_async
from core.exceptions import RecruitmentAlreadyInProgressError, RecruitmentDailyLimitExceededError
from gameplay.services.utils.messages import create_message
from gameplay.services.utils.notifications import notify_user

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


def schedule_guest_recruitment_completion(
    recruitment: GuestRecruitment,
    eta_seconds: int,
    *,
    logger: logging.Logger,
) -> None:
    countdown = max(0, int(eta_seconds))
    try:
        from guests.tasks import complete_guest_recruitment
    except Exception:
        logger.warning("Unable to import complete_guest_recruitment task; skip scheduling", exc_info=True)
        return

    def _dispatch_completion() -> None:
        dispatched = safe_apply_async(
            complete_guest_recruitment,
            args=[recruitment.id],
            countdown=countdown,
            logger=logger,
            log_message="complete_guest_recruitment dispatch failed",
        )
        if not dispatched:
            logger.error(
                "complete_guest_recruitment dispatch returned False; recruitment may remain pending",
                extra={
                    "task_name": "complete_guest_recruitment",
                    "recruitment_id": recruitment.id,
                    "manor_id": recruitment.manor_id,
                    "pool_id": recruitment.pool_id,
                },
            )

    transaction.on_commit(_dispatch_completion)


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


def send_recruitment_completion_notification(
    *,
    manor: Manor,
    pool: RecruitmentPool,
    candidate_count: int,
    logger: logging.Logger,
    recruitment_id: int | None = None,
) -> None:
    from gameplay.models import Message

    title = f"{pool.name}招募完成"
    body = f"您的{pool.name}已完成，生成 {candidate_count} 名候选门客，请前往聚贤庄挑选。"
    try:
        create_message(
            manor=manor,
            kind=Message.Kind.SYSTEM,
            title=title,
            body=body,
        )
        notify_user(
            manor.user_id,
            {
                "kind": "system",
                "title": title,
                "pool_key": pool.key,
                "candidate_count": candidate_count,
            },
            log_context="guest recruitment notification",
        )
    except Exception as exc:
        logger.warning(
            "guest recruitment notification failed: recruitment_id=%s manor_id=%s error=%s",
            recruitment_id,
            getattr(manor, "id", None),
            exc,
            exc_info=True,
        )


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
