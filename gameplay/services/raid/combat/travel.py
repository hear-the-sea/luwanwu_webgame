"""Raid travel and protection helpers (split from legacy combat.py)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Dict, List

from django.db import transaction
from django.utils import timezone

from core.utils.time_scale import scale_duration
from guests.models import Guest

from common.utils.celery import safe_apply_async

from gameplay.services.raid import combat as combat_pkg

from ....models import Manor, RaidRun
from ...messages import create_message
from ..utils import calculate_distance, is_same_region

logger = logging.getLogger(__name__)


def calculate_raid_travel_time(attacker: Manor, defender: Manor, guests: List[Guest], troop_loadout: Dict[str, int]) -> int:
    """
    计算踢馆行军时间（单程，秒）。

    公式：
    单程时间 = (基础时间 + 距离 × 速度系数) × 跨区系数 × 敏捷修正
    """
    distance = calculate_distance(attacker, defender)
    base_time = combat_pkg.PVPConstants.RAID_BASE_TRAVEL_TIME
    distance_time = distance * combat_pkg.PVPConstants.RAID_TRAVEL_TIME_PER_DISTANCE

    # 跨区惩罚
    cross_region_mult = 1.0
    if not is_same_region(attacker, defender):
        cross_region_mult = combat_pkg.PVPConstants.RAID_CROSS_REGION_MULTIPLIER

    total_time = (base_time + distance_time) * cross_region_mult

    # 敏捷加成：每10点平均敏捷减少1%时间
    if guests:
        avg_agility = sum(g.agility for g in guests) / len(guests)
        agility_reduction = min(0.5, avg_agility / 1000)  # 最多减少50%
        total_time *= (1 - agility_reduction)

    # 骑兵加成：检查是否有骑兵类兵种
    from ...recruitment import load_troop_templates

    templates_data = load_troop_templates()
    cavalry_keys = {"scout"}  # 探子算骑兵
    for tmpl in templates_data.get("troops", []):
        if tmpl.get("speed_bonus", 0) >= 5:
            cavalry_keys.add(tmpl["key"])

    has_cavalry = any(key in cavalry_keys and count > 0 for key, count in troop_loadout.items())
    if has_cavalry:
        total_time *= 0.8  # 骑兵减少20%时间

    return scale_duration(max(60, int(total_time)), minimum=1)  # 最少1分钟（游戏时间）


def get_active_raid_count(manor: Manor) -> int:
    """获取当前进行中的踢馆数量"""
    return RaidRun.objects.filter(
        attacker=manor,
        status__in=[
            RaidRun.Status.MARCHING,
            RaidRun.Status.BATTLING,
            RaidRun.Status.RETURNING,
            RaidRun.Status.RETREATED,
        ],
    ).count()


def get_incoming_raids(manor: Manor) -> List[RaidRun]:
    """获取来袭的敌军列表"""
    return list(
        RaidRun.objects.filter(defender=manor, status=RaidRun.Status.MARCHING)
        .select_related("attacker")
        .order_by("battle_at")
    )


def _dismiss_marching_raids_if_protected(defender: Manor) -> int:
    """
    检查防守方是否触发保护（24小时被攻击达到上限），如果是则遣返所有正在行军的进攻队伍。

    Args:
        defender: 防守方庄园

    Returns:
        遣返的队伍数量
    """
    now = timezone.now()

    # 检查24小时内被攻击次数（不含正在行军的）
    recent_attacks = (
        RaidRun.objects.filter(defender=defender, started_at__gte=now - timedelta(hours=24))
        .exclude(status=RaidRun.Status.MARCHING)
        .count()
    )

    if recent_attacks < combat_pkg.PVPConstants.RAID_MAX_DAILY_ATTACKS_RECEIVED:
        return 0

    # 查找所有正在行军中的、目标是该防守方的队伍
    marching_runs = list(
        RaidRun.objects.filter(defender=defender, status=RaidRun.Status.MARCHING)
        .select_related("attacker")
        .prefetch_related("guests")
    )

    if not marching_runs:
        return 0

    dismissed_count = 0
    for run in marching_runs:
        with transaction.atomic():
            # 重新锁定该记录
            locked_run = RaidRun.objects.select_for_update().filter(pk=run.pk, status=RaidRun.Status.MARCHING).first()
            if not locked_run:
                continue

            # 计算已行军时间，按原路返回
            elapsed = max(0, int((now - locked_run.started_at).total_seconds()))
            return_time = max(1, elapsed)

            # 设为撤退状态
            locked_run.status = RaidRun.Status.RETREATED
            locked_run.return_at = now + timedelta(seconds=return_time)
            locked_run.save(update_fields=["status", "return_at"])

            # 发送消息通知进攻方
            create_message(
                manor=locked_run.attacker,
                kind="system",
                title="部队已遣返",
                body=f"目标 {defender.display_name} 已触发攻击保护，您的部队已自动遣返。",
            )

        # 调度返程完成任务（事务外）
        try:
            from gameplay.tasks import complete_raid_task
        except Exception:
            logger.warning("complete_raid_task dispatch failed for dismissed raid", exc_info=True)
        else:
            safe_apply_async(
                complete_raid_task,
                args=[run.id],
                countdown=return_time,
                logger=logger,
                log_message="complete_raid_task dispatch failed for dismissed raid",
            )

        dismissed_count += 1

    if dismissed_count > 0:
        logger.info("Dismissed %s marching raids to %s due to protection trigger", dismissed_count, defender.display_name)

    return dismissed_count
