"""
装备工具模块

提供装备套装加成计算等功能。
"""
from __future__ import annotations

from typing import Dict, TYPE_CHECKING
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


def compute_set_bonus(gear_items) -> Dict[str, int]:
    """
    计算装备列表提供的套装加成。
    
    Args:
        gear_items: 装备对象列表（需包含template属性）
        
    Returns:
        加成属性字典 {"attack": 10, "defense": 5}
    """
    sets: Dict[str, Dict[str, object]] = {}
    for gear in gear_items:
        tpl = getattr(gear, "template", None)
        if not tpl:
            continue
        set_key = getattr(tpl, "set_key", "") or ""
        if not set_key:
            continue
        bonus_def = getattr(tpl, "set_bonus", None) or {}
        if not isinstance(bonus_def, dict):
            # 兼容旧数据或错误格式，如果是列表等其他类型，尝试直接作为 bonus 列表处理
            if isinstance(bonus_def, (list, tuple)):
                bonus_def = {"bonus": bonus_def}
            else:
                continue

        pieces = bonus_def.get("pieces")
        bonuses = bonus_def.get("bonus") or bonus_def.get("bonuses") or bonus_def

        # 确保 bonuses 是字典或列表，避免后续处理出错
        if not isinstance(bonuses, (dict, list, tuple)):
             # 如果 bonuses 既不是字典也不是列表，可能是旧格式的直接嵌套，或者无效数据
             # 这里尝试尽力而为，如果它看起来像是一个单项加成（有 stat 和 value），包装成列表
             if hasattr(bonuses, "get"):
                 bonuses = [bonuses]
             else:
                 bonuses = {}

        info = sets.setdefault(set_key, {"count": 0, "pieces": pieces, "bonus": bonuses})
        info["count"] += 1
        if info.get("pieces") is None and pieces is not None:
            info["pieces"] = pieces
        if info.get("bonus") is None and bonuses:
            info["bonus"] = bonuses

    bonuses_out: Dict[str, int] = {}
    for _, info in sets.items():
        required = info.get("pieces") or info.get("count") or 0
        if info.get("count", 0) < required:
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
