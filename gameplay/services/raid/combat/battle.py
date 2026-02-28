"""Raid battle execution and messaging (split from legacy combat.py)."""

from __future__ import annotations

import logging
import math
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from common.utils.celery import safe_apply_async
from gameplay.constants import get_raid_capture_guest_rate
from gameplay.services.battle_snapshots import build_guest_battle_snapshots, build_guest_snapshot_proxies
from gameplay.services.raid import combat as combat_pkg
from guests.models import Guest, GuestStatus

from ....models import JailPrisoner, Manor, OathBond, PlayerTroop, RaidRun
from ...recruitment.troops import apply_defender_troop_losses
from ...utils.messages import create_message
from .loot import (
    _apply_loot,
    _calculate_loot,
    _format_battle_rewards_description,
    _format_capture_description,
    _format_loot_description,
)
from .runs import _finalize_raid_retreat
from .travel import _dismiss_marching_raids_if_protected

logger = logging.getLogger(__name__)


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
    except Exception as exc:
        logger.warning(
            "raid capture failed: run_id=%s attacker=%s defender=%s error=%s",
            locked_run.id,
            locked_run.attacker_id,
            locked_run.defender_id,
            exc,
            exc_info=True,
        )


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


def _dispatch_complete_raid_task(run: RaidRun, *, now=None) -> None:
    try:
        from gameplay.tasks import complete_raid_task
    except Exception as exc:
        logger.warning(
            "complete_raid_task dispatch failed: run_id=%s error=%s",
            run.id,
            exc,
            exc_info=True,
        )
        return

    current_time = now or timezone.now()
    if run.return_at:
        remaining = max(0, math.ceil((run.return_at - current_time).total_seconds()))
    else:
        remaining = max(0, int(run.travel_time or 0))
    safe_apply_async(
        complete_raid_task,
        args=[run.id],
        countdown=remaining,
        logger=logger,
        log_message="complete_raid_task dispatch failed",
    )


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
                "raid battle skipped due to missing manor: run_id=%s attacker=%s defender=%s",
                locked_run.id,
                locked_run.attacker_id,
                locked_run.defender_id,
            )
            return
        # 保证后续计算使用同一事务里已加锁的攻守双方对象。
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

    # 事务外通知/附加处理均为最佳努力，避免战斗已结算却向上抛错。
    try:
        _send_raid_battle_messages(locked_run)
    except Exception as exc:
        logger.warning(
            "raid battle messages failed: run_id=%s attacker=%s defender=%s error=%s",
            locked_run.id,
            locked_run.attacker_id,
            locked_run.defender_id,
            exc,
            exc_info=True,
        )

    try:
        _dismiss_marching_raids_if_protected(locked_run.defender)
    except Exception as exc:
        logger.warning(
            "dismiss marching raids failed: run_id=%s defender=%s error=%s",
            locked_run.id,
            locked_run.defender_id,
            exc,
            exc_info=True,
        )
    _dispatch_complete_raid_task(locked_run, now=now)


def _resolve_capture_sides(run: RaidRun, is_attacker_victory: bool) -> tuple[Manor, Manor]:
    winner = run.attacker if is_attacker_victory else run.defender
    loser = run.defender if is_attacker_victory else run.attacker
    return winner, loser


def _can_attempt_capture(winner: Manor) -> bool:
    capacity = int(getattr(winner, "jail_capacity", 0) or 0)
    if capacity <= 0:
        return False

    held_count = JailPrisoner.objects.filter(captor=winner, status=JailPrisoner.Status.HELD).count()
    if held_count >= capacity:
        return False

    capture_rate = get_raid_capture_guest_rate()
    if capture_rate <= 0:
        return False
    if combat_pkg.random.random() >= capture_rate:
        return False

    return True


def _collect_losing_guest_ids(report, is_attacker_victory: bool) -> List[int]:
    losing_team = (report.defender_team or []) if is_attacker_victory else (report.attacker_team or [])
    losing_guest_ids: List[int] = []

    for entry in losing_team:
        guest_id = entry.get("guest_id") if isinstance(entry, dict) else None
        if not guest_id:
            continue
        try:
            losing_guest_ids.append(int(guest_id))
        except (TypeError, ValueError):
            continue

    return losing_guest_ids


def _filter_capture_candidates(losing_guest_ids: List[int]) -> List[int]:
    oathed_ids = set(OathBond.objects.filter(guest_id__in=losing_guest_ids).values_list("guest_id", flat=True))
    return [guest_id for guest_id in losing_guest_ids if guest_id not in oathed_ids]


def _select_capture_target(candidates: List[int], loser: Manor) -> Optional[Guest]:
    target_guest_id = combat_pkg.random.choice(candidates)
    target = (
        Guest.objects.select_for_update()
        .select_related("template", "manor")
        .filter(pk=target_guest_id, manor=loser)
        .first()
    )
    if not target:
        return None

    if OathBond.objects.filter(guest=target).exists():
        return None

    return target


def _delete_captured_guest_gear(run: RaidRun, target: Guest) -> None:
    try:
        from guests.models import GearItem

        GearItem.objects.filter(guest=target).delete()
    except Exception as exc:
        logger.warning(
            "failed to delete captured guest gear: run_id=%s guest_id=%s error=%s",
            run.id,
            target.pk,
            exc,
            exc_info=True,
        )


def _capture_guest_payload(
    captured_name: str, captured_rarity: str, captured_template_key: str, is_attacker_victory: bool
) -> Dict[str, Any]:
    return {
        "guest_name": captured_name,
        "rarity": captured_rarity,
        "template_key": captured_template_key,
        "from": "defender" if is_attacker_victory else "attacker",
        "into": "jail",
    }


def _try_capture_guest(run: RaidRun, report, is_attacker_victory: bool) -> Optional[Dict[str, Any]]:
    """
    尝试俘获失败方出战门客（单场最多1名）。

    规则：
    - 概率固定（不受监牢/结义林影响）
    - 失败方：仅从本场出战门客中抽取
    - 结义门客不可被俘获
    - 监牢满员时不进行俘获判定，不给任何补偿
    - 俘获成功：门客从失败方列表移除，装备自动消失，进入胜利方监牢
    """
    winner, loser = _resolve_capture_sides(run, is_attacker_victory)
    if not _can_attempt_capture(winner):
        return None

    losing_guest_ids = _collect_losing_guest_ids(report, is_attacker_victory)
    if not losing_guest_ids:
        return None

    candidates = _filter_capture_candidates(losing_guest_ids)
    if not candidates:
        return None

    target = _select_capture_target(candidates, loser)
    if not target:
        return None

    captured_name = target.display_name
    captured_rarity = getattr(getattr(target, "template", None), "rarity", "") or ""
    captured_template_key = getattr(getattr(target, "template", None), "key", "") or ""

    _delete_captured_guest_gear(run, target)

    JailPrisoner.objects.create(
        captor=winner,
        original_manor=loser,
        guest_template=target.template,
        original_guest_name=captured_name,
        original_level=target.level,
        loyalty=target.loyalty,
        status=JailPrisoner.Status.HELD,
        raid_run=run,
    )

    target.delete()

    return _capture_guest_payload(captured_name, captured_rarity, captured_template_key, is_attacker_victory)


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

    # 到达时刻快照：防守方为庄园中未出征的门客与护院（仅取空闲门客）
    defender_guests = list(
        defender.guests.select_for_update()
        .filter(status=GuestStatus.IDLE)
        .select_related("template")
        .prefetch_related("skills")
        .order_by("-template__rarity", "-level", "id")
    )

    defender_troops: Dict[str, int] = {}
    for troop in (
        PlayerTroop.objects.select_for_update().filter(manor=defender, count__gt=0).select_related("troop_template")
    ):
        defender_troops[troop.troop_template.key] = troop.count
    defender_guest_ids = {guest.id for guest in defender_guests}

    defender_setup = {
        "troop_loadout": defender_troops,
        "technology": {},  # 可扩展防守方科技
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
        """
        将踢馆声望变化作用于“PVP附加声望”部分，避免覆盖消费声望。

        Returns:
            实际总声望变化值（考虑下限后的结果）
        """
        before_total = manor.prestige
        spending_prestige = manor.prestige_silver_spent // PRESTIGE_SILVER_THRESHOLD
        before_pvp = max(0, before_total - spending_prestige)
        after_pvp = max(0, before_pvp + delta)
        after_total = spending_prestige + after_pvp
        manor.prestige = after_total
        manor.save(update_fields=["prestige"])
        return after_total - before_total

    # 行级锁防并发（例如多场踢馆同时结算），按固定顺序加锁避免互锁。
    ids = [run.attacker_id] if run.attacker_id == run.defender_id else sorted([run.attacker_id, run.defender_id])
    manor_map = {m.pk: m for m in ManorModel.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    attacker = manor_map.get(run.attacker_id)
    defender = manor_map.get(run.defender_id)
    if attacker is None or defender is None:
        return

    run.attacker_prestige_change = _apply_pvp_delta(attacker, attacker_change)
    run.defender_prestige_change = _apply_pvp_delta(defender, defender_change)


def _send_raid_battle_messages(run: RaidRun) -> None:
    """发送踢馆战报消息"""
    is_victory = run.is_attacker_victory
    battle_rewards = _normalize_mapping(run.battle_rewards)
    loot_resources = _normalize_positive_int_mapping(run.loot_resources)
    loot_items = _normalize_positive_int_mapping(run.loot_items)
    battle_rewards_desc = _format_battle_rewards_description(battle_rewards)
    capture_desc = _format_capture_description(battle_rewards.get("capture"))
    defeat_protection_seconds = int(getattr(combat_pkg.PVPConstants, "RAID_DEFEAT_PROTECTION_SECONDS", 1800) or 1800)
    defeat_protection_minutes = max(1, defeat_protection_seconds // 60)

    # 进攻方消息
    if is_victory:
        attacker_title = "踢馆战报 - 踢馆胜利"
        loot_desc = _format_loot_description(loot_resources, loot_items)
        attacker_body = f"""对 {run.defender.display_name} 的踢馆行动取得胜利！

战利品：
{loot_desc}

声望变化：+{run.attacker_prestige_change}"""
        # 胜利方获得战斗通用奖励
        if battle_rewards_desc:
            attacker_body += f"""

战斗回收：
{battle_rewards_desc}"""
        if capture_desc:
            attacker_body += f"""

俘获：
{capture_desc}"""
    else:
        attacker_title = "踢馆战报 - 踢馆失败"
        attacker_body = f"""对 {run.defender.display_name} 的踢馆行动失败了。

声望变化：{run.attacker_prestige_change}"""
        if capture_desc:
            attacker_body += f"""

损失：
{capture_desc}"""

    create_message(
        manor=run.attacker,
        kind="battle",
        title=attacker_title,
        body=attacker_body,
        battle_report=run.battle_report,
    )

    # 防守方消息
    if is_victory:
        defender_title = "踢馆战报 - 防守失败"
        loot_desc = _format_loot_description(loot_resources, loot_items)
        defender_body = f"""来自 {run.attacker.location_display} 的 {run.attacker.display_name} 踢馆成功！

损失：
{loot_desc}

声望变化：{run.defender_prestige_change}
已获得{defeat_protection_minutes}分钟战败保护"""
        if capture_desc:
            defender_body += f"""

损失：
{capture_desc}"""
    else:
        defender_title = "踢馆战报 - 防守成功"
        defender_body = f"""成功抵御了来自 {run.attacker.location_display} 的 {run.attacker.display_name} 的踢馆！

声望变化：+{run.defender_prestige_change}"""
        # 防守方胜利时获得战斗通用奖励
        if battle_rewards_desc:
            defender_body += f"""

战斗回收：
{battle_rewards_desc}"""
        if capture_desc:
            defender_body += f"""

俘获：
{capture_desc}"""

    create_message(
        manor=run.defender,
        kind="battle",
        title=defender_title,
        body=defender_body,
        battle_report=run.battle_report,
    )
