"""
护院/兵种共享服务模块

提供多个模块共用的护院操作函数。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Optional

from django.db.models import F
from django.utils import timezone

if TYPE_CHECKING:
    from ..models import Manor

logger = logging.getLogger(__name__)


def apply_defender_troop_losses(defender: "Manor", report) -> None:
    """
    批量应用防守方护院损失到 PlayerTroop。

    用于战斗结算时扣除防守方的护院阵亡数量。
    - 进攻方护院：在出征时已扣除，返程时仅归还存活的
    - 防守方护院：未预扣，因此需要在战斗结算时扣除阵亡数量

    Args:
        defender: 防守方庄园
        report: 战报对象（需包含 defender_troops 和 losses 属性）
    """
    from battle.troops import load_troop_templates
    from ..models import PlayerTroop

    defender_loadout = getattr(report, "defender_troops", None) or {}
    defender_losses = (getattr(report, "losses", None) or {}).get("defender", {}) or {}
    casualties = defender_losses.get("casualties", []) or []

    troop_definitions = load_troop_templates()

    troops_lost: Dict[str, int] = {}
    for entry in casualties:
        key = entry.get("key")
        if key not in defender_loadout:
            continue
        if key not in troop_definitions:
            continue
        try:
            lost = int(entry.get("lost", 0) or 0)
        except (TypeError, ValueError):
            continue
        if lost > 0:
            troops_lost[key] = troops_lost.get(key, 0) + lost

    if not troops_lost:
        return

    # 1次查询获取所有需要更新的护院记录
    troops = {
        t.troop_template.key: t
        for t in PlayerTroop.objects.select_for_update()
        .filter(manor=defender, troop_template__key__in=troops_lost.keys())
        .select_related("troop_template")
    }

    to_update = []
    for troop_key, lost in troops_lost.items():
        troop = troops.get(troop_key)
        if not troop:
            continue
        troop.count = max(0, troop.count - lost)
        to_update.append(troop)

    # 1次批量更新
    if to_update:
        PlayerTroop.objects.bulk_update(to_update, ["count", "updated_at"])


def _deduct_troops_batch(manor: "Manor", loadout: Dict[str, int]) -> None:
    """
    批量从庄园扣除指定数量的护院（通用函数）。

    Args:
        manor: 庄园对象
        loadout: 要扣除的护院配置 {troop_key: count}

    Raises:
        ValueError: 护院数量不足时抛出异常
    """
    if not loadout:
        return

    # 过滤掉数量为0的
    loadout = {k: v for k, v in loadout.items() if v > 0}
    if not loadout:
        return

    from ..models import PlayerTroop

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
            # 护院类型不存在 - 必须抛出异常，否则会造成护院复制漏洞
            # 场景：出征时扣除A但跳过B → 战斗结束归还会创建B → 凭空生成护院
            raise ValueError(f"护院配置包含不存在的类型: {troop_key}")
        if troop.count < count:
            raise ValueError(f"护院 {troop.troop_template.name} 数量不足")
        troop.count -= count
        to_update.append(troop)

    # 1次批量更新
    if to_update:
        now = timezone.now()
        for troop in to_update:
            troop.updated_at = now
        PlayerTroop.objects.bulk_update(to_update, ["count", "updated_at"])


def _return_surviving_troops_batch(
    manor: "Manor",
    loadout: Dict[str, int],
    report: Optional[object] = None,
) -> None:
    """
    批量归还存活的护院（通用函数）。

    Args:
        manor: 庄园对象
        loadout: 原始出征护院配置 {troop_key: count}
        report: 战报对象（可选，用于计算伤亡）
    """
    if not loadout:
        return

    from battle.troops import load_troop_templates

    if not report:
        # 没有战报（撤退等情况），全部归还
        _add_troops_batch(manor, loadout)
        return

    # 根据战报计算存活护院
    attacker_losses = (report.losses or {}).get("attacker", {}) or {}
    casualties = attacker_losses.get("casualties", []) or []

    troop_definitions = load_troop_templates()

    troops_lost: Dict[str, int] = {}
    for entry in casualties:
        key = entry.get("key")
        if key not in loadout:
            continue
        if key not in troop_definitions:
            continue
        try:
            lost = int(entry.get("lost", 0) or 0)
        except (TypeError, ValueError):
            continue
        if lost > 0:
            troops_lost[key] = troops_lost.get(key, 0) + lost

    # 计算存活数量（添加上限保护）
    surviving_troops = {}
    for troop_key, original_count in loadout.items():
        lost = troops_lost.get(troop_key, 0)
        # 上限保护：损失不能超过原始数量（防止重复条目导致超额累加）
        if lost > original_count:
            logger.warning(
                f"护院损失异常：{troop_key} 原始={original_count}, 战报损失={lost}, 已上限修正",
                extra={"manor_id": manor.id, "troop_key": troop_key, "original": original_count, "reported_lost": lost}
            )
            lost = original_count
        surviving = max(0, original_count - lost)
        if surviving > 0:
            surviving_troops[troop_key] = surviving

    # 批量归还
    if surviving_troops:
        logger.info(
            f"归还护院: manor_id={manor.id}, surviving_troops={surviving_troops}",
            extra={"manor_id": manor.id, "surviving_troops": surviving_troops}
        )
        _add_troops_batch(manor, surviving_troops)
    else:
        logger.warning(
            f"没有存活护院需要归还: manor_id={manor.id}, loadout={loadout}, troops_lost={troops_lost}",
            extra={"manor_id": manor.id, "loadout": loadout, "troops_lost": troops_lost}
        )


def _add_troops_batch(manor: "Manor", troops_to_add: Dict[str, int]) -> None:
    """
    批量给庄园添加护院（通用函数）。

    Args:
        manor: 庄园对象
        troops_to_add: 要添加的护院配置 {troop_key: count}

    注意：此函数假设调用者已经持有适当的事务锁

    安全修复：使用 update_or_create 确保原子性，避免并发创建导致的护院复制漏洞
    """
    from django.db import IntegrityError
    from battle.models import TroopTemplate
    from ..models import PlayerTroop

    if not troops_to_add:
        return

    # 过滤掉数量为0的
    troops_to_add = {k: v for k, v in troops_to_add.items() if v > 0}
    if not troops_to_add:
        return

    # 预加载模板
    templates = {t.key: t for t in TroopTemplate.objects.filter(key__in=troops_to_add.keys())}

    if not templates:
        return

    now = timezone.now()

    for key, count in troops_to_add.items():
        template = templates.get(key)
        if not template:
            continue

        # 安全修复：使用原子性的 update_or_create 操作
        # 先尝试使用 F() 表达式更新（最高效）
        updated = PlayerTroop.objects.filter(
            manor=manor,
            troop_template=template
        ).update(
            count=F("count") + count,
            updated_at=now
        )

        # 如果没有更新到任何行，说明记录不存在，需要创建
        if not updated:
            try:
                PlayerTroop.objects.create(
                    manor=manor,
                    troop_template=template,
                    count=count,
                )
            except IntegrityError:
                # 并发创建冲突，改用更新
                PlayerTroop.objects.filter(
                    manor=manor,
                    troop_template=template
                ).update(
                    count=F("count") + count,
                    updated_at=now
                )
