from __future__ import annotations

import logging
import random
from typing import Dict, List, Tuple

from guests.models import Guest

from ..constants import PVPConstants

logger = logging.getLogger(__name__)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def calculate_battle_salvage(
    report,
    attacker_guests: List[Guest] | None = None,
    defender_guests: List[Guest] | None = None,
) -> Tuple[int, Dict[str, int]]:
    """
    根据战报计算“胜利方战斗回收”奖励（经验果 + 护院装备回收）。

    规则参考《踢馆功能设定书》5.5（双方通用奖励）。
    """
    from gameplay.services.recruitment import get_troop_template

    if not report:
        return 0, {}

    attacker_guests = attacker_guests or []
    defender_guests = defender_guests or []

    # 使用战报seed作为随机源，确保同一战报回收结果可重放、可测试
    rng = random.Random(_safe_int(getattr(report, "seed", 0), 0))

    losses = getattr(report, "losses", None) or {}
    attacker_losses = losses.get("attacker", {}) or {}
    defender_losses = losses.get("defender", {}) or {}

    all_casualties = []
    all_casualties.extend(attacker_losses.get("casualties", []) or [])
    all_casualties.extend(defender_losses.get("casualties", []) or [])

    troop_exp_fruit = 0.0
    equipment_recovery: Dict[str, int] = {}

    for entry in all_casualties:
        key = entry.get("key", "")
        lost = _safe_int(entry.get("lost", 0), 0)
        if lost <= 0:
            continue

        troop_config = get_troop_template(key)
        if not troop_config:
            continue

        recruit = troop_config.get("recruit", {}) or {}
        base_duration = _safe_int(recruit.get("base_duration", 60), 60) or 60
        # base_duration 是秒，转换成小时后乘以系数（经验果效果是减少1小时升级时间）
        troop_exp_fruit += lost * (base_duration / 3600) * 0.1

        equipment_list = recruit.get("equipment", []) or []
        for equip_key in equipment_list:
            recovered = 0
            for _ in range(lost):
                if rng.random() < PVPConstants.EQUIPMENT_RECOVERY_CHANCE:
                    recovered += 1
            if recovered > 0:
                equipment_recovery[equip_key] = equipment_recovery.get(equip_key, 0) + recovered

    # 门客经验果：优先使用战报队伍信息（可包含 initial_hp / level / remaining_hp）
    guest_exp_fruit = 0.0
    attacker_team = getattr(report, "attacker_team", None) or []
    defender_team = getattr(report, "defender_team", None) or []
    for member in list(attacker_team) + list(defender_team):
        remaining_hp = _safe_int(member.get("remaining_hp", 0), 0)
        if remaining_hp > 0:
            continue

        level = _safe_int(member.get("level", 1), 1) or 1
        rarity = str(member.get("rarity") or "gray")
        rarity_mult = PVPConstants.RARITY_EXP_MULTIPLIER.get(rarity, 1.0)

        max_hp = _safe_int(member.get("max_hp") or member.get("hp") or 0, 0)
        initial_hp = _safe_int(member.get("initial_hp", max_hp), max_hp)
        hp_ratio = 1.0 if max_hp <= 0 else max(0.0, min(1.0, initial_hp / max_hp))

        guest_exp_fruit += level * rarity_mult * hp_ratio * 0.05

    total_exp_fruit = int(troop_exp_fruit + guest_exp_fruit)
    return total_exp_fruit, equipment_recovery


def grant_battle_salvage(manor, exp_fruit_count: int, equipment_recovery: Dict[str, int]) -> None:
    """
    发放“战斗回收”奖励到庄园仓库（经验果 + 装备回收）。
    """
    from .inventory import add_item_to_inventory

    if exp_fruit_count > 0:
        add_item_to_inventory(manor, "experience_fruit", exp_fruit_count)

    for equip_key, count in (equipment_recovery or {}).items():
        if count <= 0:
            continue
        try:
            add_item_to_inventory(manor, equip_key, count)
        except ValueError:
            logger.warning("Unknown equipment template for recovery: %s", equip_key)
