"""
模板加载工具函数

提供统一的模板批量查询接口，减少代码重复并优化查询性能。
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Dict, Iterable, List

from core.utils.template_loader import load_templates_by_key

if TYPE_CHECKING:
    from battle.models import TroopTemplate
    from guests.models import GuestTemplate, Skill

    from ..models import ItemTemplate


def _normalize_keys(keys: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_key in keys:
        key = str(raw_key).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return tuple(normalized)


def get_item_templates_by_keys(keys: Iterable[str]) -> Dict[str, "ItemTemplate"]:
    """
    根据 key 列表批量获取物品模板。

    Args:
        keys: 物品 key 的可迭代对象

    Returns:
        {key: ItemTemplate} 字典

    Example:
        templates = get_item_templates_by_keys(["sword", "shield"])
        sword = templates.get("sword")
    """
    from ..models import ItemTemplate

    normalized_keys = _normalize_keys(keys)
    if not normalized_keys:
        return {}
    return load_templates_by_key(ItemTemplate, keys=normalized_keys)


def get_item_template_names_by_keys(keys: Iterable[str]) -> Dict[str, str]:
    """
    根据 key 列表批量获取物品模板名称。

    Args:
        keys: 物品 key 的可迭代对象

    Returns:
        {key: name} 字典

    Example:
        names = get_item_template_names_by_keys(["sword", "shield"])
        sword_name = names.get("sword", "未知物品")
    """
    from ..models import ItemTemplate

    normalized_keys = _normalize_keys(keys)
    if not normalized_keys:
        return {}
    templates = load_templates_by_key(ItemTemplate, keys=normalized_keys, only_fields=["key", "name"])
    return {key: template.name for key, template in templates.items()}


def get_guest_templates_by_keys(keys: Iterable[str]) -> Dict[str, "GuestTemplate"]:
    """
    根据 key 列表批量获取门客模板。

    Args:
        keys: 门客模板 key 的可迭代对象

    Returns:
        {key: GuestTemplate} 字典
    """
    from guests.models import GuestTemplate

    normalized_keys = _normalize_keys(keys)
    if not normalized_keys:
        return {}
    return load_templates_by_key(GuestTemplate, keys=normalized_keys)


def get_skills_by_keys(keys: Iterable[str]) -> Dict[str, "Skill"]:
    """
    根据 key 列表批量获取技能。

    Args:
        keys: 技能 key 的可迭代对象

    Returns:
        {key: Skill} 字典
    """
    from guests.models import Skill

    normalized_keys = _normalize_keys(keys)
    if not normalized_keys:
        return {}
    return load_templates_by_key(Skill, keys=normalized_keys)


def get_troop_templates_by_keys(keys: Iterable[str]) -> Dict[str, "TroopTemplate"]:
    """
    根据 key 列表批量获取兵种模板。

    Args:
        keys: 兵种 key 的可迭代对象

    Returns:
        {key: TroopTemplate} 字典
    """
    from battle.models import TroopTemplate

    normalized_keys = _normalize_keys(keys)
    if not normalized_keys:
        return {}
    return load_templates_by_key(TroopTemplate, keys=normalized_keys)


@lru_cache(maxsize=1)
def get_all_building_types() -> List:
    """
    获取所有建筑类型（带缓存）。

    Returns:
        BuildingType 列表

    Note:
        使用 lru_cache 缓存结果，避免重复查询。
        如果建筑类型数据有更新，需要调用 get_all_building_types.cache_clear()
    """
    from ..models import BuildingType

    return list(BuildingType.objects.all())


def clear_building_types_cache() -> None:
    """清除建筑类型缓存"""
    get_all_building_types.cache_clear()
