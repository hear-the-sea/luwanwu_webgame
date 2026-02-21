"""
装备工具模块

提供装备套装加成计算等功能。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from ..models import GearSlot

if TYPE_CHECKING:
    pass

# 装备槽位映射
EQUIP_SLOT_MAP = {
    "equip_helmet": GearSlot.HELMET.value,
    "equip_armor": GearSlot.ARMOR.value,
    "equip_weapon": GearSlot.WEAPON.value,
    "equip_shoes": GearSlot.SHOES.value,
    "equip_mount": GearSlot.MOUNT.value,
    "equip_jewelry": GearSlot.ORNAMENT.value,
    "equip_ornament": GearSlot.ORNAMENT.value,
    "equip_special": GearSlot.DEVICE.value,
    "equip_device": GearSlot.DEVICE.value,
}

# 套装属性映射
SET_STAT_FIELD_MAP = {
    "attack": "attack_bonus",
    "defense": "defense_bonus",
    "hp": "hp_bonus",
    "force": "force",
    "intellect": "intellect",
    "agility": "agility",
    "luck": "luck",
}


def _normalize_set_bonus_definition(raw_bonus) -> tuple[int | None, dict]:
    bonus_def = raw_bonus or {}
    if not isinstance(bonus_def, dict):
        if isinstance(bonus_def, (list, tuple)):
            bonus_def = {"bonus": bonus_def}
        else:
            return None, {}

    pieces = bonus_def.get("pieces")
    bonuses = bonus_def.get("bonus") or bonus_def.get("bonuses") or bonus_def
    if not isinstance(bonuses, (dict, list, tuple)):
        if hasattr(bonuses, "get"):
            bonuses = [bonuses]
        else:
            bonuses = {}
    if not isinstance(bonuses, dict):
        return pieces, {}
    return pieces, bonuses


def _collect_set_info(gear_items) -> Dict[str, Dict[str, object]]:
    sets: Dict[str, Dict[str, object]] = {}
    for gear in gear_items:
        tpl = getattr(gear, "template", None)
        if not tpl:
            continue
        set_key = getattr(tpl, "set_key", "") or ""
        if not set_key:
            continue
        pieces, bonuses = _normalize_set_bonus_definition(getattr(tpl, "set_bonus", None))
        if not bonuses:
            continue

        info = sets.setdefault(set_key, {"count": 0, "pieces": pieces, "bonus": bonuses})
        info["count"] = int(info.get("count") or 0) + 1  # type: ignore[arg-type, call-overload]
        if info.get("pieces") is None and pieces is not None:
            info["pieces"] = pieces
        if info.get("bonus") is None:
            info["bonus"] = bonuses
    return sets


def _accumulate_active_set_bonuses(sets: Dict[str, Dict[str, object]]) -> Dict[str, int]:
    bonuses_out: Dict[str, int] = {}
    for info in sets.values():
        required = int(info.get("pieces") or info.get("count") or 0)  # type: ignore[arg-type, call-overload]
        if int(info.get("count") or 0) < required:  # type: ignore[arg-type, call-overload]
            continue
        bonus_map = info.get("bonus") or {}
        if not isinstance(bonus_map, dict):
            continue
        for stat, value in bonus_map.items():
            try:
                bonuses_out[stat] = bonuses_out.get(stat, 0) + int(value)
            except (TypeError, ValueError):
                continue
    return bonuses_out


def compute_set_bonus(gear_items) -> Dict[str, int]:
    """
    计算装备列表提供的套装加成。

    Args:
        gear_items: 装备对象列表（需包含template属性）

    Returns:
        加成属性字典 {"attack": 10, "defense": 5}
    """
    sets = _collect_set_info(gear_items)
    return _accumulate_active_set_bonuses(sets)
