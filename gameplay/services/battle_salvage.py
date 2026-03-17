from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Literal, Tuple

from guests.models import Guest

from ..constants import PVPConstants

logger = logging.getLogger(__name__)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_side(side: str | None) -> Literal["attacker", "defender"] | None:
    normalized = str(side or "").strip().lower()
    if normalized == "attacker":
        return "attacker"
    if normalized == "defender":
        return "defender"
    return None


def _collect_casualties(report, side: str | None = None) -> List[Dict[str, Any]]:
    losses = getattr(report, "losses", None) or {}
    normalized_side = _normalize_side(side)
    if normalized_side:
        side_losses = losses.get(normalized_side, {}) or {}
        return list(side_losses.get("casualties", []) or [])

    attacker_losses = losses.get("attacker", {}) or {}
    defender_losses = losses.get("defender", {}) or {}
    casualties: List[Dict[str, Any]] = []
    casualties.extend(attacker_losses.get("casualties", []) or [])
    casualties.extend(defender_losses.get("casualties", []) or [])
    return casualties


def _calculate_troop_exp_fruit(casualties: List[Dict[str, Any]]) -> float:
    from gameplay.services.recruitment.recruitment import get_troop_template

    troop_exp_fruit = 0.0
    for entry in casualties:
        key = entry.get("key", "")
        lost = _safe_int(entry.get("lost", 0), 0)
        if lost <= 0:
            continue

        troop_config = get_troop_template(key)
        if not troop_config:
            continue

        recruit = troop_config.get("recruit", {}) or {}
        base_duration = _safe_int(recruit.get("base_duration", 60), 60) or 60
        troop_exp_fruit += lost * (base_duration / 3600) * 0.1
    return troop_exp_fruit


def _calculate_equipment_recovery(casualties: List[Dict[str, Any]], rng: random.Random) -> Dict[str, int]:
    from gameplay.services.recruitment.recruitment import get_troop_template

    equipment_recovery: Dict[str, int] = {}
    for entry in casualties:
        key = entry.get("key", "")
        lost = _safe_int(entry.get("lost", 0), 0)
        if lost <= 0:
            continue

        troop_config = get_troop_template(key)
        if not troop_config:
            continue

        recruit = troop_config.get("recruit", {}) or {}
        equipment_list = recruit.get("equipment", []) or []
        for equip_key in equipment_list:
            recovered = 0
            for _ in range(lost):
                if rng.random() < PVPConstants.EQUIPMENT_RECOVERY_CHANCE:
                    recovered += 1
            if recovered > 0:
                equipment_recovery[equip_key] = equipment_recovery.get(equip_key, 0) + recovered

    return equipment_recovery


def _member_exp_fruit(member: Dict[str, Any]) -> float:
    remaining_hp = _safe_int(member.get("remaining_hp", 0), 0)
    if remaining_hp > 0:
        return 0.0

    level = _safe_int(member.get("level", 1), 1) or 1
    rarity = str(member.get("rarity") or "gray")
    rarity_mult = PVPConstants.RARITY_EXP_MULTIPLIER.get(rarity, 1.0)

    max_hp = _safe_int(member.get("max_hp") or member.get("hp") or 0, 0)
    initial_hp = _safe_int(member.get("initial_hp", max_hp), max_hp)
    hp_ratio = 1.0 if max_hp <= 0 else max(0.0, min(1.0, initial_hp / max_hp))

    return level * rarity_mult * hp_ratio * 0.05


def _calculate_guest_recovery(report) -> float:
    attacker_team = getattr(report, "attacker_team", None) or []
    defender_team = getattr(report, "defender_team", None) or []
    all_members = list(attacker_team) + list(defender_team)
    return sum(_member_exp_fruit(member) for member in all_members)


def calculate_battle_salvage(
    report,
    attacker_guests: List[Guest] | None = None,
    defender_guests: List[Guest] | None = None,
    *,
    equipment_casualty_side: str | None = None,
) -> Tuple[int, Dict[str, int]]:
    """
    根据战报计算“胜利方战斗回收”奖励（经验果 + 护院装备回收）。

    规则参考《踢馆功能设定书》5.5（双方通用奖励）。
    `equipment_casualty_side` 仅用于限定“装备回收”所依据的阵亡方，不影响经验果计算。
    """
    if not report:
        return 0, {}

    # 历史兼容参数，当前不参与计算。
    _ = attacker_guests, defender_guests

    rng = random.Random(_safe_int(getattr(report, "seed", 0), 0))

    all_casualties = _collect_casualties(report)
    troop_exp_fruit = _calculate_troop_exp_fruit(all_casualties)
    normalized_equipment_side = _normalize_side(equipment_casualty_side)
    if not normalized_equipment_side:
        equipment_casualties = all_casualties
    else:
        equipment_casualties = _collect_casualties(report, side=normalized_equipment_side)
    equipment_recovery = _calculate_equipment_recovery(equipment_casualties, rng)
    guest_exp_fruit = _calculate_guest_recovery(report)

    total_exp_fruit = int(troop_exp_fruit + guest_exp_fruit)
    return total_exp_fruit, equipment_recovery


def grant_battle_salvage(manor, exp_fruit_count: int, equipment_recovery: Dict[str, int]) -> None:
    """
    发放“战斗回收”奖励到庄园仓库（经验果 + 装备回收）。
    """
    from .inventory.core import add_item_to_inventory

    if exp_fruit_count > 0:
        add_item_to_inventory(manor, "experience_fruit", exp_fruit_count)

    for equip_key, count in (equipment_recovery or {}).items():
        if count <= 0:
            continue
        try:
            add_item_to_inventory(manor, equip_key, count)
        except ValueError:
            logger.warning("Unknown equipment template for recovery: %s", equip_key)
