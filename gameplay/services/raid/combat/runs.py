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
from .loot import _grant_loot_items
from .raid_inputs import (
    _load_and_validate_attacker_guests,
    _normalize_and_validate_raid_loadout,
    _validate_and_normalize_raid_inputs,
)
from .refresh_flow import collect_due_raid_run_ids, dispatch_async_raid_refresh, process_due_raid_run_ids
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
    guest_ids, troop_loadout = _validate_and_normalize_raid_inputs(attacker, defender, guest_ids, troop_loadout)

    with transaction.atomic():
        attacker_locked, defender_locked = _lock_manor_pair(attacker.pk, defender.pk)
        now = timezone.now()

        can_attack, reason = _recheck_can_attack_target(attacker_locked, defender_locked, now=now)
        if not can_attack:
            raise ValueError(reason)

        active_count = get_active_raid_count(attacker_locked)
        if active_count >= combat_pkg.PVPConstants.RAID_MAX_CONCURRENT:
            raise ValueError(f"同时最多进行 {combat_pkg.PVPConstants.RAID_MAX_CONCURRENT} 次出征")

        guests = _load_and_validate_attacker_guests(attacker_locked, guest_ids)
        loadout = _normalize_and_validate_raid_loadout(guests, troop_loadout)
        _deduct_troops(attacker_locked, loadout)
        travel_time = calculate_raid_travel_time(attacker_locked, defender_locked, guests, loadout)
        run = _create_raid_run_record(attacker_locked, defender_locked, guests, loadout, travel_time)
        if attacker_locked.defeat_protection_until and attacker_locked.defeat_protection_until > now:
            attacker_locked.defeat_protection_until = None
            attacker_locked.save(update_fields=["defeat_protection_until"])
        _invalidate_recent_attacks_cache_on_commit(defender_locked.pk)

    try:
        _send_raid_incoming_message(run)
    except Exception as exc:
        logger.warning(
            "raid incoming message failed: run_id=%s attacker=%s defender=%s error=%s",
            getattr(run, "id", None),
            getattr(run, "attacker_id", getattr(getattr(run, "attacker", None), "id", None)),
            getattr(run, "defender_id", getattr(getattr(run, "defender", None), "id", None)),
            exc,
            exc_info=True,
        )
    _dispatch_raid_battle_task(run, travel_time)

    return run


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
    now = now or timezone.now()

    with transaction.atomic():
        locked_run = (
            RaidRun.objects.select_for_update()
            .select_related("attacker", "defender", "battle_report")
            .prefetch_related("guests")
            .filter(pk=run.pk)
            .first()
        )

        if not locked_run:
            return

        if locked_run.status == RaidRun.Status.COMPLETED:
            return

        guests = list(locked_run.guests.select_for_update())
        guests_to_update = []
        for guest in guests:
            if guest.status == GuestStatus.DEPLOYED:
                guest.status = GuestStatus.IDLE
                guests_to_update.append(guest)

        if guests_to_update:
            Guest.objects.bulk_update(guests_to_update, ["status"])

        _return_surviving_troops(locked_run)

        if locked_run.is_attacker_victory:
            from gameplay.models import Manor as ManorModel
            from gameplay.services.resources import grant_resources_locked

            attacker_locked = ManorModel.objects.select_for_update().get(pk=locked_run.attacker_id)
            loot_resources = _normalize_positive_int_mapping(locked_run.loot_resources)
            if loot_resources:
                grant_resources_locked(
                    attacker_locked,
                    loot_resources,
                    note="踢馆掠夺",
                    reason=ResourceEvent.Reason.BATTLE_REWARD,
                    sync_production=False,
                )
            loot_items = _normalize_positive_int_mapping(locked_run.loot_items)
            if loot_items:
                _grant_loot_items(attacker_locked, loot_items)

        locked_run.status = RaidRun.Status.COMPLETED
        locked_run.completed_at = now
        locked_run.save(update_fields=["status", "completed_at"])


def request_raid_retreat(run: RaidRun) -> None:
    """
    请求踢馆撤退（仅在行军阶段可用）。

    Args:
        run: 踢馆记录

    Raises:
        ValueError: 无法撤退时
    """
    if run.status != RaidRun.Status.MARCHING:
        raise ValueError("当前状态无法撤退")

    if run.is_retreating:
        raise ValueError("已在撤退中")

    now = timezone.now()
    elapsed = max(0, int((now - run.started_at).total_seconds()))

    with transaction.atomic():
        locked_run = RaidRun.objects.select_for_update().filter(pk=run.pk).first()
        if not locked_run or locked_run.status != RaidRun.Status.MARCHING:
            raise ValueError("当前状态无法撤退")

        locked_run.is_retreating = True
        locked_run.status = RaidRun.Status.RETREATED
        locked_run.return_at = now + timedelta(seconds=max(1, elapsed))
        locked_run.save(update_fields=["is_retreating", "status", "return_at"])

    try:
        from gameplay.tasks import complete_raid_task
    except Exception as exc:
        logger.warning(
            "complete_raid_task dispatch failed for retreat: run_id=%s error=%s",
            run.id,
            exc,
            exc_info=True,
        )
    else:
        countdown = max(1, elapsed)
        dispatched = safe_apply_async(
            complete_raid_task,
            args=[run.id],
            countdown=countdown,
            logger=logger,
            log_message="complete_raid_task dispatch failed for retreat",
        )
        if not dispatched:
            logger.error(
                "complete_raid_task dispatch returned False after retreat request; raid may remain retreated",
                extra={
                    "task_name": "complete_raid_task",
                    "run_id": run.id,
                    "attacker_id": getattr(run, "attacker_id", None),
                    "defender_id": getattr(run, "defender_id", None),
                },
            )


def _finalize_raid_retreat(run: RaidRun, now: Optional[datetime] = None) -> None:
    """完成撤退，归还所有护院和门客"""
    now = now or timezone.now()

    guests = list(run.guests.select_for_update())
    guests_to_update = []
    for guest in guests:
        if guest.status == GuestStatus.DEPLOYED:
            guest.status = GuestStatus.IDLE
            guests_to_update.append(guest)
    if guests_to_update:
        Guest.objects.bulk_update(guests_to_update, ["status"])

    loadout = _normalize_positive_int_mapping(getattr(run, "troop_loadout", {}))
    if loadout:
        _add_troops_batch(run.attacker, loadout)

    run.status = RaidRun.Status.COMPLETED
    run.completed_at = now
    run.save(update_fields=["status", "completed_at"])


def can_raid_retreat(run: RaidRun, now: Optional[datetime] = None) -> bool:
    """判断踢馆是否可以撤退"""
    if run.status != RaidRun.Status.MARCHING:
        return False
    if run.is_retreating:
        return False
    return True


def refresh_raid_runs(manor: Manor, *, prefer_async: bool = False) -> None:
    """刷新庄园的踢馆状态（支持异步优先结算）。"""
    from .battle import process_raid_battle

    now = timezone.now()
    marching_ids, returning_ids, retreated_ids = collect_due_raid_run_ids(manor, now, RaidRun)

    if not marching_ids and not returning_ids and not retreated_ids:
        return

    if prefer_async:
        marching_ids, returning_ids, retreated_ids, done_async = dispatch_async_raid_refresh(
            marching_ids,
            returning_ids,
            retreated_ids,
            logger=logger,
            import_tasks=_import_raid_refresh_tasks,
            dispatch_refresh_task=_try_dispatch_raid_refresh_task,
        )
        if done_async:
            return

    process_due_raid_run_ids(
        now,
        marching_ids,
        returning_ids,
        retreated_ids,
        raid_run_model=RaidRun,
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
