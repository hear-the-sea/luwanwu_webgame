"""Raid run lifecycle helpers (start/finalize/retreat/list) split from legacy combat.py."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from common.utils.celery import safe_apply_async, safe_apply_async_with_dedup
from gameplay.services.battle_snapshots import build_guest_battle_snapshots
from gameplay.services.raid import combat as combat_pkg
from guests.models import Guest, GuestStatus

from ....models import Manor, PlayerTroop, RaidRun, ResourceEvent
from ...utils.messages import create_message
from .loot import _grant_loot_items
from .travel import calculate_raid_travel_time, get_active_raid_count

logger = logging.getLogger(__name__)


_REFRESH_DISPATCH_DEDUP_SECONDS = 5


def _normalize_mapping(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def _coerce_positive_int(raw: Any, default: int = 0) -> int:
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else 0


def _normalize_positive_int_mapping(raw: Any) -> Dict[str, int]:
    data = _normalize_mapping(raw)
    normalized: Dict[str, int] = {}
    for key, value in data.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        normalized_value = _coerce_positive_int(value, 0)
        if normalized_value > 0:
            normalized[normalized_key] = normalized_value
    return normalized


def _try_dispatch_raid_refresh_task(task, run_id: int, stage: str) -> bool:
    return safe_apply_async_with_dedup(
        task,
        dedup_key=f"pvp:refresh_dispatch:raid:{stage}:{run_id}",
        dedup_timeout=_REFRESH_DISPATCH_DEDUP_SECONDS,
        args=[run_id],
        countdown=0,
        logger=logger,
        log_message=f"raid refresh dispatch failed: stage={stage} run_id={run_id}",
    )


def _lock_manor_pair(attacker_id: int, defender_id: int) -> tuple[Manor, Manor]:
    """Lock attacker/defender rows in a stable order to avoid deadlocks."""
    ids = [attacker_id] if attacker_id == defender_id else sorted([attacker_id, defender_id])
    locked = {m.pk: m for m in Manor.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    attacker = locked.get(attacker_id)
    defender = locked.get(defender_id)
    if attacker is None or defender is None:
        raise ValueError("目标庄园不存在")
    return attacker, defender


def _recheck_can_attack_target(attacker: Manor, defender: Manor, now) -> tuple[bool, str]:
    from ..utils import can_attack_target

    return can_attack_target(attacker, defender, now=now, use_cached_recent_attacks=False)


def _invalidate_recent_attacks_cache_on_commit(defender_id: int) -> None:
    from ..utils import invalidate_recent_attacks_cache

    transaction.on_commit(lambda: invalidate_recent_attacks_cache(defender_id))


def _validate_and_normalize_raid_inputs(
    attacker: Manor,
    defender: Manor,
    guest_ids: List[int],
    troop_loadout: Dict[str, int] | None,
) -> tuple[List[int], Dict[str, int]]:
    from ..utils import can_attack_target

    can_attack, reason = can_attack_target(attacker, defender, use_cached_recent_attacks=False)
    if not can_attack:
        raise ValueError(reason)

    active_count = get_active_raid_count(attacker)
    if active_count >= combat_pkg.PVPConstants.RAID_MAX_CONCURRENT:
        raise ValueError(f"同时最多进行 {combat_pkg.PVPConstants.RAID_MAX_CONCURRENT} 次出征")

    if not guest_ids:
        raise ValueError("请选择至少一名门客")
    if not isinstance(guest_ids, list):
        raise ValueError("门客参数无效")
    try:
        normalized_guest_ids = [int(gid) for gid in guest_ids]
    except (TypeError, ValueError):
        raise ValueError("门客参数无效")

    normalized_troop_loadout = troop_loadout or {}
    if not isinstance(normalized_troop_loadout, dict):
        raise ValueError("护院配置无效")
    return normalized_guest_ids, normalized_troop_loadout


def _load_and_validate_attacker_guests(attacker: Manor, guest_ids: List[int]) -> list[Guest]:
    guests = list(
        attacker.guests.select_for_update()
        .filter(id__in=guest_ids)
        .select_related("template")
        .prefetch_related("skills")
    )

    if len(guests) != len(set(guest_ids)):
        raise ValueError("部分门客不可用或已离开庄园")

    max_squad_size = getattr(attacker, "max_squad_size", None) or 0
    if max_squad_size and len(guests) > max_squad_size:
        raise ValueError(f"最多只能派出 {max_squad_size} 名门客出征")

    for guest in guests:
        if guest.status != GuestStatus.IDLE:
            raise ValueError(f"门客 {guest.display_name} 当前不可出征")
    return guests


def _normalize_and_validate_raid_loadout(guests: list[Guest], troop_loadout: Dict[str, int]) -> Dict[str, int]:
    from battle.combatants import normalize_troop_loadout
    from battle.services import validate_troop_capacity

    loadout = normalize_troop_loadout(troop_loadout, default_if_empty=False)
    loadout = {key: count for key, count in loadout.items() if count > 0}
    validate_troop_capacity(guests, loadout)
    return loadout


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
    try:
        from gameplay.tasks import process_raid_battle_task
    except Exception as exc:
        logger.warning(
            "process_raid_battle_task dispatch failed: run_id=%s error=%s",
            run.id,
            exc,
            exc_info=True,
        )
        return

    safe_apply_async(
        process_raid_battle_task,
        args=[run.id],
        countdown=travel_time,
        logger=logger,
        log_message="process_raid_battle_task dispatch failed",
    )


def _extract_raid_troops_lost(loadout: Dict[str, int], battle_report) -> Dict[str, int]:
    if not battle_report:
        return {}

    normalized_loadout = _normalize_positive_int_mapping(loadout)
    if not normalized_loadout:
        return {}

    losses = _normalize_mapping(getattr(battle_report, "losses", {}))
    attacker_losses = _normalize_mapping(losses.get("attacker"))
    casualties = attacker_losses.get("casualties")
    if not isinstance(casualties, list):
        return {}

    from battle.troops import load_troop_templates

    troop_definitions = load_troop_templates()
    troops_lost: Dict[str, int] = {}
    for entry in casualties:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if key not in normalized_loadout or key not in troop_definitions:
            continue
        lost = _coerce_positive_int(entry.get("lost", 0), 0)
        if lost > 0:
            troops_lost[key] = troops_lost.get(key, 0) + lost
    return troops_lost


def _calculate_surviving_raid_troops(loadout: Dict[str, int], troops_lost: Dict[str, int]) -> Dict[str, int]:
    surviving_troops: Dict[str, int] = {}
    for troop_key, original_count in loadout.items():
        surviving = max(0, original_count - troops_lost.get(troop_key, 0))
        if surviving > 0:
            surviving_troops[troop_key] = surviving
    return surviving_troops


def _normalize_troops_for_addition(troops_to_add: Dict[str, int]) -> Dict[str, int]:
    return _normalize_positive_int_mapping(troops_to_add)


def _collect_troop_upserts(
    manor: Manor,
    troops_to_add: Dict[str, int],
    templates: Dict[str, object],
    existing: Dict[str, PlayerTroop],
    now,
) -> tuple[list[PlayerTroop], list[PlayerTroop]]:
    to_update: list[PlayerTroop] = []
    to_create: list[PlayerTroop] = []
    for key, count in troops_to_add.items():
        template = templates.get(key)
        if not template:
            logger.warning("Unknown troop template: %s", key)
            continue
        if key in existing:
            existing[key].count += count
            existing[key].updated_at = now
            to_update.append(existing[key])
        else:
            to_create.append(PlayerTroop(manor=manor, troop_template=template, count=count))
    return to_update, to_create


def _bulk_create_troops_with_fallback(to_create: list[PlayerTroop], now) -> None:
    if not to_create:
        return
    # Use per-row upsert to avoid silent quantity loss:
    # bulk_create(ignore_conflicts=True) swallows conflicts without raising,
    # which may drop increments under concurrent create races.
    for pt in to_create:
        updated = PlayerTroop.objects.filter(manor=pt.manor, troop_template=pt.troop_template).update(
            count=F("count") + pt.count,
            updated_at=now,
        )
        if updated:
            continue
        try:
            PlayerTroop.objects.create(
                manor=pt.manor,
                troop_template=pt.troop_template,
                count=pt.count,
            )
        except IntegrityError:
            PlayerTroop.objects.filter(manor=pt.manor, troop_template=pt.troop_template).update(
                count=F("count") + pt.count,
                updated_at=now,
            )


def _collect_due_raid_run_ids(manor: Manor, now) -> tuple[list[int], list[int], list[int]]:
    marching_ids = list(
        RaidRun.objects.filter(attacker=manor, status=RaidRun.Status.MARCHING, battle_at__lte=now).values_list(
            "id", flat=True
        )
    )
    returning_ids = list(
        RaidRun.objects.filter(attacker=manor, status=RaidRun.Status.RETURNING, return_at__lte=now).values_list(
            "id", flat=True
        )
    )
    retreated_ids = list(
        RaidRun.objects.filter(attacker=manor, status=RaidRun.Status.RETREATED, return_at__lte=now).values_list(
            "id", flat=True
        )
    )
    return marching_ids, returning_ids, retreated_ids


def _dispatch_async_raid_refresh(
    marching_ids: list[int],
    returning_ids: list[int],
    retreated_ids: list[int],
) -> tuple[list[int], list[int], list[int], bool]:
    try:
        from gameplay.tasks import complete_raid_task, process_raid_battle_task
    except Exception:
        logger.warning("Failed to import raid tasks, falling back to sync refresh", exc_info=True)
        return marching_ids, returning_ids, retreated_ids, False

    sync_marching_ids: list[int] = []
    for run_id in marching_ids:
        if not _try_dispatch_raid_refresh_task(process_raid_battle_task, run_id, "battle"):
            sync_marching_ids.append(run_id)

    sync_finalizing_ids: list[int] = []
    for run_id in returning_ids + retreated_ids:
        if not _try_dispatch_raid_refresh_task(complete_raid_task, run_id, "return"):
            sync_finalizing_ids.append(run_id)

    if not sync_marching_ids and not sync_finalizing_ids:
        return [], [], [], True

    sync_finalizing_set = set(sync_finalizing_ids)
    return (
        sync_marching_ids,
        [run_id for run_id in returning_ids if run_id in sync_finalizing_set],
        [run_id for run_id in retreated_ids if run_id in sync_finalizing_set],
        False,
    )


def _process_due_raid_run_ids(now, marching_ids: list[int], returning_ids: list[int], retreated_ids: list[int]) -> None:
    from .battle import process_raid_battle

    if marching_ids:
        for run in RaidRun.objects.filter(id__in=marching_ids).order_by("battle_at"):
            process_raid_battle(run, now=now)
    if returning_ids:
        for run in RaidRun.objects.filter(id__in=returning_ids).order_by("return_at"):
            finalize_raid(run, now=now)
    if retreated_ids:
        for run in RaidRun.objects.filter(id__in=retreated_ids).order_by("return_at"):
            finalize_raid(run, now=now)


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
        # Lock both attacker and defender in a stable order, then re-check all start constraints.
        attacker_locked, defender_locked = _lock_manor_pair(attacker.pk, defender.pk)
        now = timezone.now()

        can_attack, reason = _recheck_can_attack_target(attacker_locked, defender_locked, now=now)
        if not can_attack:
            raise ValueError(reason)

        # Re-check concurrent limit inside lock
        active_count = get_active_raid_count(attacker_locked)
        if active_count >= combat_pkg.PVPConstants.RAID_MAX_CONCURRENT:
            raise ValueError(f"同时最多进行 {combat_pkg.PVPConstants.RAID_MAX_CONCURRENT} 次出征")

        guests = _load_and_validate_attacker_guests(attacker_locked, guest_ids)
        loadout = _normalize_and_validate_raid_loadout(guests, troop_loadout)
        _deduct_troops(attacker_locked, loadout)
        travel_time = calculate_raid_travel_time(attacker_locked, defender_locked, guests, loadout)
        run = _create_raid_run_record(attacker_locked, defender_locked, guests, loadout, travel_time)
        _invalidate_recent_attacks_cache_on_commit(defender_locked.pk)

    # 发送来袭警报给防守方
    _send_raid_incoming_message(run)
    _dispatch_raid_battle_task(run, travel_time)

    return run


def _deduct_troops(manor: Manor, loadout: Dict[str, int]) -> None:
    """从庄园批量扣除指定数量的护院"""
    # 过滤掉数量无效的配置
    loadout = _normalize_positive_int_mapping(loadout)
    if not loadout:
        return

    # 1次查询获取所有需要的护院记录
    troops = {
        t.troop_template.key: t
        for t in PlayerTroop.objects.select_for_update()
        .filter(manor=manor, troop_template__key__in=loadout.keys())
        .select_related("troop_template")
    }

    to_update = []
    for troop_key, count in loadout.items():
        troop = troops.get(troop_key)
        if not troop:
            raise ValueError("没有该类型的护院")
        if troop.count < count:
            raise ValueError(f"护院 {troop.troop_template.name} 数量不足")
        troop.count -= count
        to_update.append(troop)

    # 1次批量更新
    if to_update:
        PlayerTroop.objects.bulk_update(to_update, ["count", "updated_at"])


def _send_raid_incoming_message(run: RaidRun) -> None:
    """发送来袭警报消息"""
    # 格式化预计抵达时间
    arrive_time = run.battle_at.strftime("%Y-%m-%d %H:%M:%S")

    body = f"""来自 {run.attacker.location_display} 的 {run.attacker.display_name} 正在向你发起进攻！

预计抵达时间：{arrive_time}

请立即做好防守准备！"""

    create_message(
        manor=run.defender,
        kind="system",
        title="紧急警报 - 敌军来袭！",
        body=body,
    )


def finalize_raid(run: RaidRun, now=None) -> None:
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

        # 批量释放门客
        guests = list(locked_run.guests.select_for_update())
        guests_to_update = []
        for guest in guests:
            # 保留战斗造成的重伤状态，仅将仍处于 DEPLOYED 的门客恢复为空闲
            if guest.status == GuestStatus.DEPLOYED:
                guest.status = GuestStatus.IDLE
                guests_to_update.append(guest)

        if guests_to_update:
            Guest.objects.bulk_update(guests_to_update, ["status"])

        # 归还进攻方护院（存活的）
        _return_surviving_troops(locked_run)

        # 发放战利品给进攻方
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
                )
            loot_items = _normalize_positive_int_mapping(locked_run.loot_items)
            if loot_items:
                _grant_loot_items(attacker_locked, loot_items)

        locked_run.status = RaidRun.Status.COMPLETED
        locked_run.completed_at = now
        locked_run.save(update_fields=["status", "completed_at"])


def _return_surviving_troops(run: RaidRun) -> None:
    """批量归还存活的护院"""
    loadout = _normalize_positive_int_mapping(getattr(run, "troop_loadout", {}))
    if not loadout:
        return

    if not run.battle_report:
        # 没有战报（撤退等情况），全部归还
        _add_troops_batch(run.attacker, loadout)
        return

    troops_lost = _extract_raid_troops_lost(loadout, run.battle_report)
    surviving_troops = _calculate_surviving_raid_troops(loadout, troops_lost)

    # 批量归还
    if surviving_troops:
        _add_troops_batch(run.attacker, surviving_troops)


def _add_troops(manor: Manor, troop_key: str, count: int) -> None:
    """给庄园添加护院（单个兵种）"""
    if count <= 0:
        return
    _add_troops_batch(manor, {troop_key: count})


def _add_troops_batch(manor: Manor, troops_to_add: Dict[str, int]) -> None:
    """批量给庄园添加护院"""
    from battle.models import TroopTemplate

    if not troops_to_add:
        return

    troops_to_add = _normalize_troops_for_addition(troops_to_add)
    if not troops_to_add:
        return

    # 预加载模板
    from core.utils.template_loader import load_templates_by_key

    templates = load_templates_by_key(TroopTemplate, keys=troops_to_add.keys())

    if not templates:
        return

    # 预加载现有护院
    existing = {
        pt.troop_template.key: pt
        for pt in PlayerTroop.objects.select_for_update()
        .filter(manor=manor, troop_template__key__in=troops_to_add.keys())
        .select_related("troop_template")
    }

    now = timezone.now()
    to_update, to_create = _collect_troop_upserts(manor, troops_to_add, templates, existing, now)

    if to_update:
        PlayerTroop.objects.bulk_update(to_update, ["count", "updated_at"])
    _bulk_create_troops_with_fallback(to_create, now)


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

    # 调度撤退完成任务
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
        safe_apply_async(
            complete_raid_task,
            args=[run.id],
            countdown=countdown,
            logger=logger,
            log_message="complete_raid_task dispatch failed for retreat",
        )


def _finalize_raid_retreat(run: RaidRun, now=None) -> None:
    """完成撤退，归还所有护院和门客"""
    now = now or timezone.now()

    # 批量释放门客
    guests = list(run.guests.select_for_update())
    guests_to_update = []
    for guest in guests:
        # 仅将仍处于 DEPLOYED 的门客恢复为空闲，避免覆盖其他状态
        if guest.status == GuestStatus.DEPLOYED:
            guest.status = GuestStatus.IDLE
            guests_to_update.append(guest)
    if guests_to_update:
        Guest.objects.bulk_update(guests_to_update, ["status"])

    # 批量全额归还护院
    loadout = _normalize_positive_int_mapping(getattr(run, "troop_loadout", {}))
    if loadout:
        _add_troops_batch(run.attacker, loadout)

    run.status = RaidRun.Status.COMPLETED
    run.completed_at = now
    run.save(update_fields=["status", "completed_at"])


def can_raid_retreat(run: RaidRun, now=None) -> bool:
    """判断踢馆是否可以撤退"""
    if run.status != RaidRun.Status.MARCHING:
        return False
    if run.is_retreating:
        return False
    return True


def refresh_raid_runs(manor: Manor, *, prefer_async: bool = False) -> None:
    """刷新庄园的踢馆状态（支持异步优先结算）。"""
    now = timezone.now()
    marching_ids, returning_ids, retreated_ids = _collect_due_raid_run_ids(manor, now)

    if not marching_ids and not returning_ids and not retreated_ids:
        return

    if prefer_async:
        marching_ids, returning_ids, retreated_ids, done_async = _dispatch_async_raid_refresh(
            marching_ids,
            returning_ids,
            retreated_ids,
        )
        if done_async:
            return

    _process_due_raid_run_ids(now, marching_ids, returning_ids, retreated_ids)


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
