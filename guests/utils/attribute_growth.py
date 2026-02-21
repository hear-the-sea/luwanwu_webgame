"""
门客属性成长工具模块

提供升级时的属性随机分配功能。
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from ..models import Guest

from ..models import GuestArchetype

# 每个稀有度每升1级可获得的基础成长点区间（最小值, 最大值）
# 基础成长点数会在区间内随机生成，然后按职业权重分配到各个属性
# 稀有度越高，每级成长点数的区间越大，成长潜力越高
RARITY_ATTRIBUTE_GROWTH_RANGE = {
    "black": (1, 3),  # 黑色：1-3点基础成长
    "gray": (2, 5),  # 灰色：2-5点基础成长
    "green": (3, 7),  # 绿色：3-7点基础成长
    "red": (4, 7),  # 红色：4-7点基础成长（调整：避免与绿色下限重叠，期望5.5）
    "blue": (5, 9),  # 蓝色：5-9点基础成长
    "purple": (6, 11),  # 紫色：6-11点基础成长
    "orange": (6, 14),  # 橙色：6-14点基础成长
}

# 武门客属性分配权重
MILITARY_ATTRIBUTE_WEIGHTS = {
    "force": 40,
    "intellect": 15,
    "defense": 23,
    "agility": 22,
}

# 文门客属性分配权重
CIVIL_ATTRIBUTE_WEIGHTS = {
    "force": 20,
    "intellect": 40,
    "defense": 20,
    "agility": 20,
}


def _resolve_growth_range(rarity: str, growth_range: list | None) -> tuple[int, int]:
    if growth_range and len(growth_range) == 2:
        return int(growth_range[0]), int(growth_range[1])
    default_min, default_max = RARITY_ATTRIBUTE_GROWTH_RANGE.get(rarity, (1, 3))
    return int(default_min), int(default_max)


def _resolve_weights(archetype: str, attribute_weights: dict | None) -> dict[str, int]:
    if attribute_weights:
        weights = {
            "force": int(attribute_weights.get("force", 0) or 0),
            "intellect": int(attribute_weights.get("intellect", 0) or 0),
            "defense": int(attribute_weights.get("defense", 0) or 0),
            "agility": int(attribute_weights.get("agility", 0) or 0),
        }
        if sum(weights.values()) > 0:
            return weights
    if archetype == GuestArchetype.MILITARY:
        return MILITARY_ATTRIBUTE_WEIGHTS
    return CIVIL_ATTRIBUTE_WEIGHTS


def _build_weighted_choices(weights: dict[str, int]) -> list[str]:
    choices: list[str] = []
    for attr, weight in weights.items():
        if weight > 0:
            choices.extend([attr] * int(weight))
    return choices


def allocate_level_up_attributes(
    guest: "Guest",
    levels: int = 1,
    rng: random.Random | None = None,
) -> Dict[str, int]:
    """
    计算门客升级时获得的属性增长。

    基于稀有度和职业的成长机制：
    - 每一级独立随机生成基础成长点数（根据稀有度区间）
    - 基础成长点数按职业权重分配到各个属性
    - 武将倾向防御（33%）和武力（30%），文官倾向智力（30%）和防御（30%）
    - 武将敏捷（25%）> 文官敏捷（22%），体现先手优势

    Args:
        guest: 门客实例
        levels: 升级的等级数（默认1级）
        rng: 随机数生成器（可选，用于测试）

    Returns:
        属性增长字典 {"force": X, "intellect": Y, "defense": Z, "agility": W}

    Examples:
        >>> guest = Guest(rarity="orange", archetype="military")
        >>> result = allocate_level_up_attributes(guest, levels=1)
        >>> # 橙色武将升1级，6-12点基础成长随机分配
        >>> # 预期：defense约33%，force约30%，agility约25%，intellect约12%
    """
    if rng is None:
        rng = random.Random()

    template = guest.template

    min_growth, max_growth = _resolve_growth_range(guest.rarity, template.growth_range)
    weights = _resolve_weights(guest.archetype, template.attribute_weights)
    choices = _build_weighted_choices(weights)

    # 初始化分配结果
    allocation = {
        "force": 0,
        "intellect": 0,
        "defense": 0,
        "agility": 0,
    }

    # 逐级计算：每一级独立随机生成成长点数，然后分配
    for _ in range(levels):
        points_this_level = rng.randint(min_growth, max_growth)
        for _ in range(points_this_level):
            attr = rng.choice(choices)
            allocation[attr] += 1

    return allocation


def apply_attribute_growth(guest: "Guest", allocation: Dict[str, int]) -> None:
    """
    应用属性成长到门客实例。

    Args:
        guest: 门客实例
        allocation: 属性分配字典
    """
    guest.force += allocation.get("force", 0)
    guest.intellect += allocation.get("intellect", 0)
    guest.defense_stat += allocation.get("defense", 0)
    guest.agility += allocation.get("agility", 0)


def get_expected_growth(
    rarity: str,
    archetype: str,
    levels: int = 1,
    growth_range: list | None = None,
    attribute_weights: dict | None = None,
) -> Dict[str, float]:
    """
    计算期望的属性成长（用于UI显示）。

    使用成长点数区间的均值计算期望值。

    Args:
        rarity: 稀有度
        archetype: 职业类型
        levels: 等级数
        growth_range: 自定义成长点数区间 [min, max]（可选）
        attribute_weights: 自定义属性分配权重（可选）

    Returns:
        期望属性增长字典

    Examples:
        >>> get_expected_growth("orange", "military", 1)
        {'force': 2.7, 'intellect': 1.08, 'defense': 2.97, 'agility': 2.25}
    """
    min_growth, max_growth = _resolve_growth_range(rarity, growth_range)

    mean_growth = (min_growth + max_growth) / 2
    total_points = mean_growth * levels

    weights = _resolve_weights(archetype, attribute_weights)

    # 计算权重总和
    total_weight = sum(weights.values())

    # 计算期望值
    expected = {}
    for attr, weight in weights.items():
        expected[attr] = (total_points * weight) / total_weight

    return expected
