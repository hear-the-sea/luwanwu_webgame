"""Raid battle execution (split from legacy combat.py)."""

from __future__ import annotations

import logging
import math
from datetime import timedelta
from typing import Dict, Optional

from django.db import DatabaseError, transaction
from django.utils import timezone

from common.utils.celery import safe_apply_async
from gameplay.services.battle_snapshots import build_guest_battle_snapshots, build_guest_snapshot_proxies
from gameplay.services.raid import combat as combat_pkg
from guests.models import Guest, GuestStatus
from guests.query_utils import guest_template_rarity_rank_case

from ....models import Manor, PlayerTroop, RaidRun
from ...recruitment.troops import apply_defender_troop_losses

# Re-export capture helpers so existing imports from battle keep working.
from .capture import (  # noqa: F401
    _can_attempt_capture,
    _capture_guest_payload,
    _collect_losing_guest_ids,
    _delete_captured_guest_gear,
    _filter_capture_candidates,
    _resolve_capture_sides,
    _select_capture_target,
    _try_capture_guest,
)
from .loot import _apply_loot, _calculate_loot

# Re-export messaging helpers.
from .messaging import _send_raid_battle_messages  # noqa: F401
from .runs import _add_troops_batch, _finalize_raid_retreat
from .travel import _dismiss_marching_raids_if_protected
from .troops import _coerce_positive_int, _normalize_mapping, _normalize_positive_int_mapping

logger = logging.getLogger(__name__)


RAID_BATTLE_INFRASTRUCTURE_EXCEPTIONS = (DatabaseError, ConnectionError, OSError, TimeoutError)
RAID_CAPTURE_DEGRADED_EXCEPTIONS = (ConnectionError, OSError, TimeoutError)


def _load_locked_raid_run(run_pk: int) -> Optional[RaidRun]:
    return (
        RaidRun.objects.select_for_update()
        .select_related("attacker", "defender")
        .prefetch_related("guests")
        .filter(pk=run_pk)
        .first()
    )


def _prepare_run_for_battle(run_pk: int, now) -> Optional[RaidRun]:
    locked_run = _load_locked_raid_run(run_pk)
    if not locked_run:
        return None

    if locked_run.status == RaidRun.Status.RETREATED:
        if locked_run.return_at and locked_run.return_at > now:
            return None
        _finalize_raid_retreat(locked_run, now)
        return None

    if locked_run.status != RaidRun.Status.MARCHING:
        return None

    locked_run.status = RaidRun.Status.BATTLING
    locked_run.save(update_fields=["status"])
    return locked_run


def _lock_battle_manors(attacker_id: int, defender_id: int) -> tuple[Manor, Manor]:
    ids = [attacker_id] if attacker_id == defender_id else sorted([attacker_id, defender_id])
    locked = {m.pk: m for m in Manor.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    attacker = locked.get(attacker_id)
    defender = locked.get(defender_id)
    if attacker is None or defender is None:
        raise ValueError("目标庄园不存在")
    return attacker, defender


def _apply_raid_loot_if_needed(locked_run: RaidRun, is_attacker_victory: bool) -> None:
    if not is_attacker_victory:
        return

    locked_defender = Manor.objects.select_for_update().get(pk=locked_run.defender_id)
    loot_resources, loot_items = _calculate_loot(locked_defender)
    applied_resources, applied_items = _apply_loot(
        locked_defender,
        loot_resources,
        loot_items,
        locked_manor=locked_defender,
    )
    locked_run.loot_resources = applied_resources
    locked_run.loot_items = applied_items


def _apply_defeat_protection(run: RaidRun, is_attacker_victory: bool, *, now=None) -> None:
    if not is_attacker_victory:
        return
    now = now or timezone.now()
    duration_seconds = int(getattr(combat_pkg.PVPConstants, "RAID_DEFEAT_PROTECTION_SECONDS", 1800) or 0)
    if duration_seconds <= 0:
        return

    defender = Manor.objects.select_for_update().get(pk=run.defender_id)
    new_until = now + timedelta(seconds=duration_seconds)
    current_until = defender.defeat_protection_until
    if current_until and current_until > new_until:
        new_until = current_until
    defender.defeat_protection_until = new_until
    defender.save(update_fields=["defeat_protection_until"])
    run.defender = defender


def _apply_capture_reward(locked_run: RaidRun, report, is_attacker_victory: bool) -> None:
    try:
        capture_info = _try_capture_guest(locked_run, report, is_attacker_victory)
        if capture_info:
            battle_rewards = _normalize_mapping(locked_run.battle_rewards)
            locked_run.battle_rewards = {**battle_rewards, "capture": capture_info}
    except RAID_CAPTURE_DEGRADED_EXCEPTIONS as exc:
        logger.warning(
            "raid capture failed: run_id=%s attacker=%s defender=%s error=%s",
            locked_run.id,
            locked_run.attacker_id,
            locked_run.defender_id,
            exc,
            exc_info=True,
            extra={
                "degraded": True,
                "component": "raid_capture_reward",
                "run_id": locked_run.id,
            },
        )
    except Exception:
        logger.error(
            "Unexpected raid capture failure: run_id=%s attacker=%s defender=%s",
            locked_run.id,
            locked_run.attacker_id,
            locked_run.defender_id,
            exc_info=True,
            extra={
                "degraded": True,
                "component": "raid_capture_reward",
                "run_id": locked_run.id,
            },
        )
        raise


def _apply_salvage_reward(locked_run: RaidRun, report, is_attacker_victory: bool) -> None:
    from gameplay.services.battle_salvage import calculate_battle_salvage, grant_battle_salvage

    exp_fruit_count, equipment_recovery = calculate_battle_salvage(report)
    normalized_exp_fruit_count = _coerce_positive_int(exp_fruit_count, 0)
    normalized_equipment_recovery = _normalize_positive_int_mapping(equipment_recovery)
    if normalized_exp_fruit_count <= 0 and not normalized_equipment_recovery:
        return

    winner_manor = locked_run.attacker if is_attacker_victory else locked_run.defender
    grant_battle_salvage(winner_manor, normalized_exp_fruit_count, normalized_equipment_recovery)
    battle_rewards = _normalize_mapping(locked_run.battle_rewards)
    locked_run.battle_rewards = {
        **battle_rewards,
        "exp_fruit": normalized_exp_fruit_count,
        "equipment": normalized_equipment_recovery,
    }


def _fail_raid_run_due_missing_manor(locked_run: RaidRun, *, now=None) -> None:
    now = now or timezone.now()

    guests = list(locked_run.guests.select_for_update())
    guests_to_update = []
    for guest in guests:
        if guest.status == GuestStatus.DEPLOYED:
            guest.status = GuestStatus.IDLE
            guests_to_update.append(guest)
    if guests_to_update:
        Guest.objects.bulk_update(guests_to_update, ["status"])

    attacker_locked = Manor.objects.select_for_update().filter(pk=locked_run.attacker_id).first()
    if attacker_locked is not None:
        loadout = _normalize_positive_int_mapping(getattr(locked_run, "troop_loadout", {}))
        if loadout:
            _add_troops_batch(attacker_locked, loadout)
        locked_run.attacker = attacker_locked

    locked_run.status = RaidRun.Status.COMPLETED
    locked_run.is_attacker_victory = False
    locked_run.return_at = now
    locked_run.completed_at = now
    locked_run.save(update_fields=["status", "is_attacker_victory", "return_at", "completed_at"])


def _dispatch_complete_raid_task(run: RaidRun, *, now=None) -> None:
    def _fallback_sync_when_due(remaining_seconds: int) -> None:
        if remaining_seconds > 0:
            return
        logger.warning("complete_raid_task dispatch failed for due raid; finalizing synchronously: run_id=%s", run.id)
        from .runs import finalize_raid

        finalize_raid(run, now=current_time)

    try:
        from gameplay.tasks import complete_raid_task
    except ImportError as exc:
        logger.warning(
            "complete_raid_task import failed: run_id=%s error=%s",
            run.id,
            exc,
            exc_info=True,
            extra={"degraded": True, "component": "raid_task_import", "run_id": run.id},
        )
        current_time = now or timezone.now()
        remaining = 0 if not run.return_at else max(0, math.ceil((run.return_at - current_time).total_seconds()))
        _fallback_sync_when_due(remaining)
        return
    except Exception:
        logger.error(
            "Unexpected complete_raid_task import failure: run_id=%s",
            run.id,
            exc_info=True,
            extra={"degraded": True, "component": "raid_task_import", "run_id": run.id},
        )
        raise

    current_time = now or timezone.now()
    if run.return_at:
        remaining = max(0, math.ceil((run.return_at - current_time).total_seconds()))
    else:
        remaining = max(0, int(run.travel_time or 0))
    dispatched = safe_apply_async(
        complete_raid_task,
        args=[run.id],
        countdown=remaining,
        logger=logger,
        log_message="complete_raid_task dispatch failed",
    )
    if not dispatched:
        _fallback_sync_when_due(remaining)


def process_raid_battle(run: RaidRun, now=None) -> None:
    """
    处理踢馆战斗。

    Args:
        run: 踢馆记录
        now: 当前时间（可选）
    """
    now = now or timezone.now()

    with transaction.atomic():
        locked_run = _prepare_run_for_battle(run.pk, now)
        if locked_run is None:
            return

        try:
            attacker_locked, defender_locked = _lock_battle_manors(locked_run.attacker_id, locked_run.defender_id)
        except ValueError:
            logger.warning(
                "raid battle aborted due to missing manor: run_id=%s attacker=%s defender=%s",
                locked_run.id,
                locked_run.attacker_id,
                locked_run.defender_id,
            )
            _fail_raid_run_due_missing_manor(locked_run, now=now)
            return
        locked_run.attacker = attacker_locked
        locked_run.defender = defender_locked

        report = _execute_raid_battle(locked_run)
        apply_defender_troop_losses(locked_run.defender, report)

        is_attacker_victory = report.winner == "attacker"
        locked_run.is_attacker_victory = is_attacker_victory
        locked_run.battle_report = report

        _apply_raid_loot_if_needed(locked_run, is_attacker_victory)
        _apply_prestige_changes(locked_run, is_attacker_victory)
        _apply_defeat_protection(locked_run, is_attacker_victory, now=now)
        _apply_capture_reward(locked_run, report, is_attacker_victory)
        _apply_salvage_reward(locked_run, report, is_attacker_victory)

        locked_run.status = RaidRun.Status.RETURNING
        locked_run.save()

    try:
        _send_raid_battle_messages(locked_run)
    except RAID_BATTLE_INFRASTRUCTURE_EXCEPTIONS as exc:
        logger.warning(
            "raid battle messages failed: run_id=%s attacker=%s defender=%s error=%s",
            locked_run.id,
            locked_run.attacker_id,
            locked_run.defender_id,
            exc,
            exc_info=True,
            extra={
                "degraded": True,
                "component": "raid_battle_message",
                "run_id": locked_run.id,
            },
        )
    except Exception:
        # 消息通知属于边缘副作用，任何异常都不应回滚已提交的战斗结果
        logger.error(
            "Unexpected raid battle message failure: run_id=%s attacker=%s defender=%s",
            locked_run.id,
            locked_run.attacker_id,
            locked_run.defender_id,
            exc_info=True,
            extra={
                "degraded": True,
                "component": "raid_battle_message",
                "run_id": locked_run.id,
            },
        )

    try:
        _dismiss_marching_raids_if_protected(locked_run.defender)
    except RAID_BATTLE_INFRASTRUCTURE_EXCEPTIONS as exc:
        logger.warning(
            "dismiss marching raids failed: run_id=%s defender=%s error=%s",
            locked_run.id,
            locked_run.defender_id,
            exc,
            exc_info=True,
            extra={
                "degraded": True,
                "component": "raid_protection_cleanup",
                "run_id": locked_run.id,
            },
        )
    except Exception:
        # 战斗保护清理是边缘副作用，失败不回滚已提交的战斗结果
        logger.error(
            "Unexpected dismiss marching raids failure: run_id=%s defender=%s",
            locked_run.id,
            locked_run.defender_id,
            exc_info=True,
            extra={
                "degraded": True,
                "component": "raid_protection_cleanup",
                "run_id": locked_run.id,
            },
        )
    _dispatch_complete_raid_task(locked_run, now=now)


# ============ Battle execution and guest damage ============


def _extract_side_guest_state(report, side: str) -> tuple[Dict[int, int], set[int]]:
    hp_updates: Dict[int, int] = {}
    defeated_guest_ids: set[int] = set()

    if not report:
        return hp_updates, defeated_guest_ids

    team_entries = report.attacker_team if side == "attacker" else report.defender_team
    for entry in team_entries or []:
        if not isinstance(entry, dict):
            continue
        guest_id_raw = entry.get("guest_id")
        remaining_hp_raw = entry.get("remaining_hp")
        try:
            guest_id = int(guest_id_raw)
            remaining_hp = int(remaining_hp_raw)
        except (TypeError, ValueError):
            continue
        hp_updates[guest_id] = remaining_hp
        if remaining_hp <= 0:
            defeated_guest_ids.add(guest_id)

    raw_hp_updates = ((report.losses or {}).get(side) or {}).get("hp_updates") or {}
    for guest_id_raw, hp_raw in raw_hp_updates.items():
        try:
            guest_id = int(guest_id_raw)
            hp = int(hp_raw)
        except (TypeError, ValueError):
            continue
        hp_updates.setdefault(guest_id, hp)

    return hp_updates, defeated_guest_ids


def _apply_guest_damage_from_report(
    report,
    *,
    attacker_guest_ids: set[int],
    defender_guest_ids: set[int],
) -> None:
    attacker_hp_updates, attacker_defeated_ids = _extract_side_guest_state(report, "attacker")
    defender_hp_updates, defender_defeated_ids = _extract_side_guest_state(report, "defender")

    target_ids = (attacker_guest_ids | defender_guest_ids) & (
        set(attacker_hp_updates.keys()) | set(defender_hp_updates.keys())
    )
    if not target_ids:
        return

    guests = list(Guest.objects.select_for_update().filter(id__in=target_ids))
    if not guests:
        return

    now = timezone.now()
    dirty_guests: list[Guest] = []
    for guest in guests:
        if guest.id in attacker_guest_ids:
            hp = attacker_hp_updates.get(guest.id)
            is_defeated = guest.id in attacker_defeated_ids
        else:
            hp = defender_hp_updates.get(guest.id)
            is_defeated = guest.id in defender_defeated_ids
        if hp is None:
            continue

        guest.current_hp = max(1, min(guest.max_hp, int(hp)))
        guest.last_hp_recovery_at = now
        if is_defeated:
            guest.status = GuestStatus.INJURED
        dirty_guests.append(guest)

    if dirty_guests:
        Guest.objects.bulk_update(dirty_guests, ["current_hp", "last_hp_recovery_at", "status"])


def _execute_raid_battle(run: RaidRun):
    """执行踢馆战斗"""
    from battle.services import simulate_report

    attacker = run.attacker
    defender = run.defender
    attacker_guests = list(run.guests.select_for_update().select_related("template").prefetch_related("skills"))
    loadout = _normalize_positive_int_mapping(run.troop_loadout)
    attacker_guest_ids = {guest.id for guest in attacker_guests}

    attacker_snapshots = list(run.guest_snapshots or [])
    if not attacker_snapshots and attacker_guests:
        attacker_snapshots = build_guest_battle_snapshots(attacker_guests, include_identity=True)
    attacker_combat_guests = build_guest_snapshot_proxies(attacker_snapshots, include_guest_identity=True)
    if not attacker_combat_guests:
        attacker_combat_guests = attacker_guests

    defender_guests = list(
        defender.guests.select_for_update()
        .filter(status=GuestStatus.IDLE)
        .select_related("template")
        .prefetch_related("skills")
        .annotate(_template_rarity_rank=guest_template_rarity_rank_case("template__rarity"))
        .order_by("-_template_rarity_rank", "-level", "id")
    )

    defender_troops: Dict[str, int] = {}
    for troop in (
        PlayerTroop.objects.select_for_update().filter(manor=defender, count__gt=0).select_related("troop_template")
    ):
        defender_troops[troop.troop_template.key] = troop.count
    defender_guest_ids = {guest.id for guest in defender_guests}

    defender_setup = {
        "troop_loadout": defender_troops,
        "technology": {},
    }

    report = simulate_report(
        manor=attacker,
        battle_type="raid",
        troop_loadout=loadout,
        fill_default_troops=False,
        attacker_guests=attacker_combat_guests,
        defender_setup=defender_setup,
        defender_guests=defender_guests,
        defender_max_squad=getattr(defender, "max_squad_size", None),
        opponent_name=defender.display_name,
        travel_seconds=0,
        send_message=False,
        auto_reward=False,
        apply_damage=False,
        use_lock=False,
    )
    _apply_guest_damage_from_report(
        report,
        attacker_guest_ids=attacker_guest_ids,
        defender_guest_ids=defender_guest_ids,
    )

    return report


def _apply_prestige_changes(run: RaidRun, is_attacker_victory: bool) -> None:
    """应用声望变化"""
    from gameplay.models import Manor as ManorModel

    from ...manor.prestige import PRESTIGE_SILVER_THRESHOLD

    if is_attacker_victory:
        attacker_change = combat_pkg.PVPConstants.RAID_ATTACKER_WIN_PRESTIGE
        defender_change = combat_pkg.PVPConstants.RAID_DEFENDER_LOSE_PRESTIGE
    else:
        attacker_change = combat_pkg.PVPConstants.RAID_ATTACKER_LOSE_PRESTIGE
        defender_change = combat_pkg.PVPConstants.RAID_DEFENDER_WIN_PRESTIGE

    def _apply_pvp_delta(manor: Manor, delta: int) -> int:
        before_total = manor.prestige
        spending_prestige = manor.prestige_silver_spent // PRESTIGE_SILVER_THRESHOLD
        before_pvp = max(0, before_total - spending_prestige)
        after_pvp = max(0, before_pvp + delta)
        after_total = spending_prestige + after_pvp
        manor.prestige = after_total
        manor.save(update_fields=["prestige"])
        return after_total - before_total

    ids = [run.attacker_id] if run.attacker_id == run.defender_id else sorted([run.attacker_id, run.defender_id])
    manor_map = {m.pk: m for m in ManorModel.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    attacker = manor_map.get(run.attacker_id)
    defender = manor_map.get(run.defender_id)
    if attacker is None or defender is None:
        return

    run.attacker_prestige_change = _apply_pvp_delta(attacker, attacker_change)
    run.defender_prestige_change = _apply_pvp_delta(defender, defender_change)
