"""Raid run lifecycle helpers (start/finalize/retreat/list) split from legacy combat.py."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from common.utils.celery import safe_apply_async, safe_apply_async_with_dedup
from gameplay.services.battle_snapshots import build_guest_battle_snapshots
from gameplay.services.raid import combat as combat_pkg
from guests.models import Guest, GuestStatus

from ....models import Manor, RaidRun, ResourceEvent
from ...utils.messages import create_message
from .finalize import finalize_raid as _finalize_raid_command
from .loot import _grant_loot_items
from .raid_inputs import (
    _load_and_validate_attacker_guests,
    _normalize_and_validate_raid_loadout,
    _validate_and_normalize_raid_inputs,
)
from .refresh import refresh_raid_runs as _refresh_raid_runs_command
from .refresh_flow import collect_due_raid_run_ids, dispatch_async_raid_refresh, process_due_raid_run_ids
from .retreat import can_raid_retreat as _can_raid_retreat_command
from .retreat import finalize_raid_retreat as _finalize_raid_retreat_command
from .retreat import request_raid_retreat as _request_raid_retreat_command
from .start import start_raid as _start_raid_command
from .travel import calculate_raid_travel_time, get_active_raid_count

# Import troop management helpers (moved to troop_ops, re-exported for callers).
from .troop_ops import (  # noqa: F401
    _add_troops,
    _add_troops_batch,
    _bulk_create_troops_with_fallback,
    _deduct_troops,
    _return_surviving_troops,
)

# Import normalization helpers from the troops sub-module (still used in this file).
from .troops import _coerce_positive_int, _normalize_mapping, _normalize_positive_int_mapping  # noqa: F401

logger = logging.getLogger(__name__)


_REFRESH_DISPATCH_DEDUP_SECONDS = 5


def _try_dispatch_raid_refresh_task(task: Any, run_id: int, stage: str) -> bool:
    return safe_apply_async_with_dedup(
        task,
        dedup_key=f"pvp:refresh_dispatch:raid:{stage}:{run_id}",
        dedup_timeout=_REFRESH_DISPATCH_DEDUP_SECONDS,
        args=[run_id],
        countdown=0,
        logger=logger,
        log_message=f"raid refresh dispatch failed: stage={stage} run_id={run_id}",
    )


def _import_raid_refresh_tasks() -> tuple[Any, Any]:
    from gameplay.tasks import complete_raid_task, process_raid_battle_task

    return complete_raid_task, process_raid_battle_task


def _lock_manor_pair(attacker_id: int, defender_id: int) -> tuple[Manor, Manor]:
    """Lock attacker/defender rows in a stable order to avoid deadlocks."""
    ids = [attacker_id] if attacker_id == defender_id else sorted([attacker_id, defender_id])
    locked = {m.pk: m for m in Manor.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    attacker = locked.get(attacker_id)
    defender = locked.get(defender_id)
    if attacker is None or defender is None:
        raise ValueError("目标庄园不存在")
    return attacker, defender


def _recheck_can_attack_target(attacker: Manor, defender: Manor, now: datetime) -> tuple[bool, str]:
    from ..utils import can_attack_target

    return can_attack_target(attacker, defender, now=now, use_cached_recent_attacks=False)


def _invalidate_recent_attacks_cache_on_commit(defender_id: int) -> None:
    from ..utils import invalidate_recent_attacks_cache

    transaction.on_commit(lambda: invalidate_recent_attacks_cache(defender_id))


def _create_raid_run_record(
    attacker: Manor,
    defender: Manor,
    guests: list[Guest],
    loadout: Dict[str, int],
    travel_time: int,
) -> RaidRun:
    for guest in guests:
        guest.status = GuestStatus.DEPLOYED
    Guest.objects.bulk_update(guests, ["status"])

    now = timezone.now()
    guest_snapshots = build_guest_battle_snapshots(guests, include_identity=True)
    run = RaidRun.objects.create(
        attacker=attacker,
        defender=defender,
        guest_snapshots=guest_snapshots,
        troop_loadout=loadout,
        status=RaidRun.Status.MARCHING,
        travel_time=travel_time,
        battle_at=now + timedelta(seconds=travel_time),
        return_at=now + timedelta(seconds=travel_time * 2),
    )
    run.guests.set(guests)
    return run


def _dispatch_raid_battle_task(run: RaidRun, travel_time: int) -> None:
    def _fallback_sync_when_due() -> None:
        if travel_time > 0:
            return
        logger.warning(
            "process_raid_battle_task dispatch failed for due raid; processing synchronously: run_id=%s", run.id
        )
        from .battle import process_raid_battle

        process_raid_battle(run)

    try:
        from gameplay.tasks import process_raid_battle_task
    except Exception as exc:
        logger.warning(
            "process_raid_battle_task dispatch failed: run_id=%s error=%s",
            run.id,
            exc,
            exc_info=True,
        )
        _fallback_sync_when_due()
        return

    dispatched = safe_apply_async(
        process_raid_battle_task,
        args=[run.id],
        countdown=travel_time,
        logger=logger,
        log_message="process_raid_battle_task dispatch failed",
    )
    if not dispatched:
        logger.error(
            "process_raid_battle_task dispatch returned False; raid battle may not execute",
            extra={
                "task_name": "process_raid_battle_task",
                "run_id": run.id,
                "attacker_id": getattr(run, "attacker_id", None),
                "defender_id": getattr(run, "defender_id", None),
            },
        )
        _fallback_sync_when_due()


# ============ Public API: raid lifecycle ============


def _load_locked_raid_run(run_pk: int) -> RaidRun | None:
    return (
        RaidRun.objects.select_for_update()
        .select_related("attacker", "defender", "battle_report")
        .prefetch_related("guests")
        .filter(pk=run_pk)
        .first()
    )


def _load_locked_attacker(attacker_id: int) -> Manor:
    return Manor.objects.select_for_update().get(pk=attacker_id)


def start_raid(
    attacker: Manor, defender: Manor, guest_ids: List[int], troop_loadout: Dict[str, int], seed: Optional[int] = None
) -> RaidRun:
    """
    发起踢馆出征。

    Args:
        attacker: 进攻方庄园
        defender: 防守方庄园
        guest_ids: 出征门客ID列表
        troop_loadout: 兵种配置
        seed: 随机数种子（可选）

    Returns:
        踢馆记录

    Raises:
        ValueError: 无法发起踢馆时
    """
    del seed
    return _start_raid_command(
        attacker,
        defender,
        guest_ids,
        troop_loadout,
        validate_and_normalize_inputs=_validate_and_normalize_raid_inputs,
        transaction_atomic=transaction.atomic,
        lock_manor_pair=_lock_manor_pair,
        now_func=timezone.now,
        recheck_can_attack_target=_recheck_can_attack_target,
        get_active_raid_count=get_active_raid_count,
        raid_max_concurrent=combat_pkg.PVPConstants.RAID_MAX_CONCURRENT,
        load_and_validate_attacker_guests=_load_and_validate_attacker_guests,
        normalize_and_validate_raid_loadout=_normalize_and_validate_raid_loadout,
        deduct_troops=_deduct_troops,
        calculate_raid_travel_time=calculate_raid_travel_time,
        create_raid_run_record=_create_raid_run_record,
        invalidate_recent_attacks_cache_on_commit=_invalidate_recent_attacks_cache_on_commit,
        send_raid_incoming_message=_send_raid_incoming_message,
        dispatch_raid_battle_task=_dispatch_raid_battle_task,
        logger=logger,
    )


def _send_raid_incoming_message(run: RaidRun) -> None:
    """发送来袭警报消息"""
    battle_at = run.battle_at
    arrive_time = battle_at.strftime("%Y-%m-%d %H:%M:%S") if battle_at else "未知"

    body = f"""来自 {run.attacker.location_display} 的 {run.attacker.display_name} 正在向你发起进攻！

预计抵达时间：{arrive_time}

请立即做好防守准备！"""

    create_message(
        manor=run.defender,
        kind="system",
        title="紧急警报 - 敌军来袭！",
        body=body,
    )


def finalize_raid(run: RaidRun, now: Optional[datetime] = None) -> None:
    """
    完成踢馆返程，释放门客和发放战利品。

    Args:
        run: 踢馆记录
        now: 当前时间（可选）
    """
    from gameplay.services.resources import grant_resources_locked

    _finalize_raid_command(
        run,
        now=now,
        load_locked_raid_run=_load_locked_raid_run,
        normalize_positive_int_mapping=_normalize_positive_int_mapping,
        return_surviving_troops=_return_surviving_troops,
        load_locked_attacker=_load_locked_attacker,
        grant_resources_locked=grant_resources_locked,
        grant_loot_items=_grant_loot_items,
        battle_reward_reason=ResourceEvent.Reason.BATTLE_REWARD,
    )


def _schedule_raid_retreat_completion(run_id: int, countdown: int) -> None:
    try:
        from gameplay.tasks import complete_raid_task
    except Exception as exc:
        logger.warning(
            "complete_raid_task dispatch failed for retreat: run_id=%s error=%s",
            run_id,
            exc,
            exc_info=True,
        )
        return

    dispatched = safe_apply_async(
        complete_raid_task,
        args=[run_id],
        countdown=countdown,
        logger=logger,
        log_message="complete_raid_task dispatch failed for retreat",
    )
    if not dispatched:
        logger.error(
            "complete_raid_task dispatch returned False after retreat request; raid may remain retreated",
            extra={
                "task_name": "complete_raid_task",
                "run_id": run_id,
            },
        )


def request_raid_retreat(run: RaidRun) -> None:
    """
    请求踢馆撤退（仅在行军阶段可用）。

    Args:
        run: 踢馆记录

    Raises:
        ValueError: 无法撤退时
    """
    _request_raid_retreat_command(
        run,
        raid_run_model=RaidRun,
        schedule_retreat_completion=_schedule_raid_retreat_completion,
    )


def _finalize_raid_retreat(run: RaidRun, now: Optional[datetime] = None) -> None:
    """完成撤退，归还所有护院和门客"""
    _finalize_raid_retreat_command(
        run,
        now=now,
        normalize_positive_int_mapping=_normalize_positive_int_mapping,
        add_troops_batch=_add_troops_batch,
        completed_status=RaidRun.Status.COMPLETED,
    )


def can_raid_retreat(run: RaidRun, now: Optional[datetime] = None) -> bool:
    """判断踢馆是否可以撤退"""
    return _can_raid_retreat_command(run, marching_status=RaidRun.Status.MARCHING, now=now)


def refresh_raid_runs(manor: Manor, *, prefer_async: bool = False) -> None:
    """刷新庄园的踢馆状态（支持异步优先结算）。"""
    from .battle import process_raid_battle

    _refresh_raid_runs_command(
        manor,
        prefer_async=prefer_async,
        now_func=timezone.now,
        raid_run_model=RaidRun,
        collect_due_raid_run_ids=collect_due_raid_run_ids,
        dispatch_async_raid_refresh=dispatch_async_raid_refresh,
        logger=logger,
        import_raid_refresh_tasks=_import_raid_refresh_tasks,
        try_dispatch_raid_refresh_task=_try_dispatch_raid_refresh_task,
        process_due_raid_run_ids=process_due_raid_run_ids,
        process_raid_battle=process_raid_battle,
        finalize_raid=finalize_raid,
    )


def get_active_raids(manor: Manor) -> List[RaidRun]:
    """获取进行中的踢馆列表"""
    return list(
        RaidRun.objects.filter(
            attacker=manor,
            status__in=[
                RaidRun.Status.MARCHING,
                RaidRun.Status.RETURNING,
                RaidRun.Status.RETREATED,
            ],
        )
        .select_related("defender", "battle_report")
        .order_by("-started_at")
    )


def get_raid_history(manor: Manor, limit: int = 20) -> List[RaidRun]:
    """获取踢馆历史记录"""
    return list(
        RaidRun.objects.filter(Q(attacker=manor) | Q(defender=manor))
        .select_related("attacker", "defender", "battle_report")
        .order_by("-started_at")[:limit]
    )
