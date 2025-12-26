"""
门客属性成长工具模块

提供升级时的属性随机分配功能。
"""
from __future__ import annotations

import random
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Guest

from ..models import (
    GuestArchetype,
)


# 每个稀有度每升1级可获得的基础成长点区间（最小值, 最大值）
# 基础成长点数会在区间内随机生成，然后按职业权重分配到各个属性
# 稀有度越高，每级成长点数的区间越大，成长潜力越高
RARITY_ATTRIBUTE_GROWTH_RANGE = {
    "black": (1, 3),    # 黑色：1-3点基础成长
    "gray": (2, 5),     # 灰色：2-5点基础成长
    "green": (3, 7),    # 绿色：3-7点基础成长
    "red": (4, 7),      # 红色：4-7点基础成长（调整：避免与绿色下限重叠，期望5.5）
    "blue": (5, 9),     # 蓝色：5-9点基础成长
    "purple": (6, 10),  # 紫色：6-10点基础成长
    "orange": (6, 12),  # 橙色：6-12点基础成长
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

    # 成长点数区间：模板配置 > 稀有度默认
    if template.growth_range and len(template.growth_range) == 2:
        min_growth, max_growth = template.growth_range
    else:
        min_growth, max_growth = RARITY_ATTRIBUTE_GROWTH_RANGE.get(guest.rarity, (1, 3))

    # 属性权重：模板配置 > 职业默认
    if template.attribute_weights:
        # 确保所有属性都有权重，缺失的属性使用默认值 0
        weights = {
            "force": template.attribute_weights.get("force", 0),
            "intellect": template.attribute_weights.get("intellect", 0),
            "defense": template.attribute_weights.get("defense", 0),
            "agility": template.attribute_weights.get("agility", 0),
        }
        # 如果所有权重都是0，回退到职业默认
        if sum(weights.values()) == 0:
            if guest.archetype == GuestArchetype.MILITARY:
                weights = MILITARY_ATTRIBUTE_WEIGHTS
            else:
                weights = CIVIL_ATTRIBUTE_WEIGHTS
    elif guest.archetype == GuestArchetype.MILITARY:
        weights = MILITARY_ATTRIBUTE_WEIGHTS
    else:  # CIVIL
        weights = CIVIL_ATTRIBUTE_WEIGHTS

    # 创建加权选择池（只添加权重>0的属性）
    choices = []
    for attr, weight in weights.items():
        if weight > 0:
            choices.extend([attr] * int(weight))

    # 初始化分配结果
    allocation = {
        "force": 0,
        "intellect": 0,
        "defense": 0,
        "agility": 0,
    }

    # 逐级计算：每一级独立随机生成成长点数，然后分配
    for _ in range(levels):
        points_this_level = rng.randint(int(min_growth), int(max_growth))
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
    # 成长点数区间：自定义 > 稀有度默认
    if growth_range and len(growth_range) == 2:
        min_growth, max_growth = growth_range
    else:
        min_growth, max_growth = RARITY_ATTRIBUTE_GROWTH_RANGE.get(rarity, (1, 3))

    mean_growth = (min_growth + max_growth) / 2
    total_points = mean_growth * levels

    # 属性权重：自定义 > 职业默认
    if attribute_weights:
        # 确保所有属性都有权重，缺失的属性使用默认值 0
        weights = {
            "force": attribute_weights.get("force", 0),
            "intellect": attribute_weights.get("intellect", 0),
            "defense": attribute_weights.get("defense", 0),
            "agility": attribute_weights.get("agility", 0),
        }
        # 如果所有权重都是0，回退到职业默认
        if sum(weights.values()) == 0:
            if archetype == GuestArchetype.MILITARY:
                weights = MILITARY_ATTRIBUTE_WEIGHTS
            else:
                weights = CIVIL_ATTRIBUTE_WEIGHTS
    elif archetype == GuestArchetype.MILITARY:
        weights = MILITARY_ATTRIBUTE_WEIGHTS
    else:
        weights = CIVIL_ATTRIBUTE_WEIGHTS

    # 计算权重总和
    total_weight = sum(weights.values())

    # 计算期望值
    expected = {}
    for attr, weight in weights.items():
        expected[attr] = (total_points * weight) / total_weight

    return expected
