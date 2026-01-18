"""
护院/兵种共享服务模块

提供多个模块共用的护院操作函数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from ..models import Manor


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
