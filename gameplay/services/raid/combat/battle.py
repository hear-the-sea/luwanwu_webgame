"""Raid battle execution and messaging (split from legacy combat.py)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone

from common.utils.celery import safe_apply_async

from gameplay.services.raid import combat as combat_pkg

from guests.models import Guest, GuestStatus

from ....models import JailPrisoner, Manor, OathBond, PlayerTroop, RaidRun
from ...messages import create_message
from ...troops import apply_defender_troop_losses
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


def process_raid_battle(run: RaidRun, now=None) -> None:
    """
    处理踢馆战斗。

    Args:
        run: 踢馆记录
        now: 当前时间（可选）
    """
    now = now or timezone.now()

    with transaction.atomic():
        locked_run = (
            RaidRun.objects.select_for_update()
            .select_related("attacker", "defender")
            .prefetch_related("guests")
            .filter(pk=run.pk)
            .first()
        )

        if not locked_run:
            return

        # 检查状态
        if locked_run.status == RaidRun.Status.RETREATED:
            # 已撤退：仅在到达返程完成时间后才可完成（避免在 battle_at 被提前结算）
            if locked_run.return_at and locked_run.return_at > now:
                return
            _finalize_raid_retreat(locked_run, now)
            return

        if locked_run.status != RaidRun.Status.MARCHING:
            return

        locked_run.status = RaidRun.Status.BATTLING
        locked_run.save(update_fields=["status"])

        # 执行战斗
        report = _execute_raid_battle(locked_run)

        # 应用防守方护院损失（护院实际损耗）
        apply_defender_troop_losses(locked_run.defender, report)

        # 判定胜负
        is_attacker_victory = report.winner == "attacker"
        locked_run.is_attacker_victory = is_attacker_victory
        locked_run.battle_report = report

        # 计算战利品（仅进攻方胜利时）
        if is_attacker_victory:
            locked_defender = Manor.objects.select_for_update().get(pk=locked_run.defender_id)
            loot_resources, loot_items = _calculate_loot(locked_defender)
            # 扣除防守方资源和物品，记录实际扣除量
            applied_resources, applied_items = _apply_loot(
                locked_defender,
                loot_resources,
                loot_items,
                locked_manor=locked_defender,
            )
            locked_run.loot_resources = applied_resources
            locked_run.loot_items = applied_items

        # 计算声望变化
        _apply_prestige_changes(locked_run, is_attacker_victory)

        # 俘获门客（胜利方有概率俘获失败方出战门客，单场最多1名）
        try:
            capture_info = _try_capture_guest(locked_run, report, is_attacker_victory)
            if capture_info:
                locked_run.battle_rewards = {**(locked_run.battle_rewards or {}), "capture": capture_info}
        except Exception:
            logger.warning("raid capture failed", exc_info=True)

        # 计算并发放战斗通用奖励（经验果+装备回收）给胜利方
        from gameplay.services.battle_salvage import calculate_battle_salvage, grant_battle_salvage

        exp_fruit_count, equipment_recovery = calculate_battle_salvage(report)
        if exp_fruit_count > 0 or equipment_recovery:
            winner_manor = locked_run.attacker if is_attacker_victory else locked_run.defender
            grant_battle_salvage(winner_manor, exp_fruit_count, equipment_recovery)
            # 记录战斗奖励到 run 以便消息显示
            locked_run.battle_rewards = {
                **(locked_run.battle_rewards or {}),
                "exp_fruit": exp_fruit_count,
                "equipment": equipment_recovery,
            }

        # 更新状态为返程
        locked_run.status = RaidRun.Status.RETURNING
        locked_run.save()

    # 发送战报消息
    _send_raid_battle_messages(locked_run)

    # 检查防守方是否触发保护（达到24小时被攻击上限），遣返其他正在路上的进攻队伍
    _dismiss_marching_raids_if_protected(locked_run.defender)

    # 调度返程完成任务
    try:
        from gameplay.tasks import complete_raid_task
    except Exception:
        logger.warning("complete_raid_task dispatch failed", exc_info=True)
    else:
        remaining = locked_run.travel_time  # 返程时间等于单程时间
        safe_apply_async(
            complete_raid_task,
            args=[locked_run.id],
            countdown=remaining,
            logger=logger,
            log_message="complete_raid_task dispatch failed",
        )


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
    winner = run.attacker if is_attacker_victory else run.defender
    loser = run.defender if is_attacker_victory else run.attacker

    capacity = int(getattr(winner, "jail_capacity", 0) or 0)
    if capacity <= 0:
        return None

    held_count = JailPrisoner.objects.filter(captor=winner, status=JailPrisoner.Status.HELD).count()
    if held_count >= capacity:
        return None

    capture_rate = float(getattr(combat_pkg.PVPConstants, "RAID_CAPTURE_GUEST_RATE", 0.0) or 0.0)
    if capture_rate <= 0:
        return None
    if combat_pkg.random.random() >= capture_rate:
        return None

    losing_team = (report.defender_team or []) if is_attacker_victory else (report.attacker_team or [])
    losing_guest_ids: List[int] = []
    for entry in losing_team:
        guest_id = entry.get("guest_id") if isinstance(entry, dict) else None
        if guest_id:
            try:
                losing_guest_ids.append(int(guest_id))
            except (TypeError, ValueError):
                continue

    if not losing_guest_ids:
        return None

    oathed_ids = set(OathBond.objects.filter(guest_id__in=losing_guest_ids).values_list("guest_id", flat=True))
    candidates = [gid for gid in losing_guest_ids if gid not in oathed_ids]
    if not candidates:
        return None

    target_guest_id = combat_pkg.random.choice(candidates)
    target = (
        Guest.objects.select_for_update().select_related("template", "manor").filter(pk=target_guest_id, manor=loser).first()
    )
    if not target:
        return None

    # 兜底：并发下如果刚结义/状态变化，直接放弃俘获
    if OathBond.objects.filter(guest=target).exists():
        return None

    captured_name = target.display_name
    captured_rarity = getattr(getattr(target, "template", None), "rarity", "") or ""
    captured_template_key = getattr(getattr(target, "template", None), "key", "") or ""

    # 装备自动消失：删除该门客已装备的装备实例
    try:
        from guests.models import GearItem

        GearItem.objects.filter(guest=target).delete()
    except Exception:
        logger.warning("failed to delete captured guest gear", exc_info=True)

    JailPrisoner.objects.create(
        captor=winner,
        original_manor=loser,
        guest_template=target.template,
        original_guest_name=captured_name,
        original_level=target.level,
        loyalty=target.loyalty,  # 保留被俘前的忠诚度
        status=JailPrisoner.Status.HELD,
        raid_run=run,
    )

    # 从失败方门客列表移除（门客本体删除；装备已提前删除）
    target.delete()

    return {
        "guest_name": captured_name,
        "rarity": captured_rarity,
        "template_key": captured_template_key,
        "from": "defender" if is_attacker_victory else "attacker",
        "into": "jail",
    }


def _execute_raid_battle(run: RaidRun):
    """执行踢馆战斗"""
    from battle.services import simulate_report

    attacker = run.attacker
    defender = run.defender
    guests = list(run.guests.select_for_update().select_related("template").prefetch_related("skills"))
    loadout = run.troop_loadout or {}

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
        PlayerTroop.objects.select_for_update()
        .filter(manor=defender, count__gt=0)
        .select_related("troop_template")
    ):
        defender_troops[troop.troop_template.key] = troop.count

    defender_setup = {
        "troop_loadout": defender_troops,
        "technology": {},  # 可扩展防守方科技
    }

    report = simulate_report(
        manor=attacker,
        battle_type="raid",
        troop_loadout=loadout,
        fill_default_troops=False,
        attacker_guests=guests,
        defender_setup=defender_setup,
        defender_guests=defender_guests,
        defender_max_squad=getattr(defender, "max_squad_size", None),
        opponent_name=defender.display_name,
        travel_seconds=0,
        send_message=False,
        auto_reward=False,
        apply_damage=True,
        use_lock=False,
    )

    return report


def _apply_prestige_changes(run: RaidRun, is_attacker_victory: bool) -> None:
    """应用声望变化"""
    from ...prestige import PRESTIGE_SILVER_THRESHOLD
    from gameplay.models import Manor as ManorModel

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

    # 行级锁防并发（例如多场踢馆同时结算）
    attacker = ManorModel.objects.select_for_update().get(pk=run.attacker_id)
    defender = ManorModel.objects.select_for_update().get(pk=run.defender_id)

    run.attacker_prestige_change = _apply_pvp_delta(attacker, attacker_change)
    run.defender_prestige_change = _apply_pvp_delta(defender, defender_change)


def _send_raid_battle_messages(run: RaidRun) -> None:
    """发送踢馆战报消息"""
    is_victory = run.is_attacker_victory
    battle_rewards = run.battle_rewards or {}
    battle_rewards_desc = _format_battle_rewards_description(battle_rewards)
    capture_desc = _format_capture_description(battle_rewards.get("capture"))

    # 进攻方消息
    if is_victory:
        attacker_title = "踢馆战报 - 踢馆胜利"
        loot_desc = _format_loot_description(run.loot_resources, run.loot_items)
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
        loot_desc = _format_loot_description(run.loot_resources, run.loot_items)
        defender_body = f"""来自 {run.attacker.location_display} 的 {run.attacker.display_name} 踢馆成功！

损失：
{loot_desc}

声望变化：{run.defender_prestige_change}
已获得30分钟战败保护"""
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
