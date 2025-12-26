"""
模板加载工具函数

提供统一的模板批量查询接口，减少代码重复并优化查询性能。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, Iterable, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import ItemTemplate
    from guests.models import GuestTemplate, Skill
    from battle.models import TroopTemplate


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

    key_list = list(keys)
    if not key_list:
        return {}
    return {tpl.key: tpl for tpl in ItemTemplate.objects.filter(key__in=key_list)}


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

    key_list = list(keys)
    if not key_list:
        return {}
    return {
        tpl.key: tpl.name
        for tpl in ItemTemplate.objects.filter(key__in=key_list).only("key", "name")
    }


def get_guest_templates_by_keys(keys: Iterable[str]) -> Dict[str, "GuestTemplate"]:
    """
    根据 key 列表批量获取门客模板。

    Args:
        keys: 门客模板 key 的可迭代对象

    Returns:
        {key: GuestTemplate} 字典
    """
    from guests.models import GuestTemplate

    key_list = list(keys)
    if not key_list:
        return {}
    return {tpl.key: tpl for tpl in GuestTemplate.objects.filter(key__in=key_list)}


def get_skills_by_keys(keys: Iterable[str]) -> Dict[str, "Skill"]:
    """
    根据 key 列表批量获取技能。

    Args:
        keys: 技能 key 的可迭代对象

    Returns:
        {key: Skill} 字典
    """
    from guests.models import Skill

    key_list = list(keys)
    if not key_list:
        return {}
    return {skill.key: skill for skill in Skill.objects.filter(key__in=key_list)}


def get_troop_templates_by_keys(keys: Iterable[str]) -> Dict[str, "TroopTemplate"]:
    """
    根据 key 列表批量获取兵种模板。

    Args:
        keys: 兵种 key 的可迭代对象

    Returns:
        {key: TroopTemplate} 字典
    """
    from battle.models import TroopTemplate

    key_list = list(keys)
    if not key_list:
        return {}
    return {tpl.key: tpl for tpl in TroopTemplate.objects.filter(key__in=key_list)}


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
