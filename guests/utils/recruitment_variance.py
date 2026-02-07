"""
门客招募随机波动工具模块

在模板属性基础上应用随机波动，为每个招募的门客创造独特性。
"""
from __future__ import annotations

import random
from typing import Dict, Optional, TYPE_CHECKING
from collections.abc import Mapping

if TYPE_CHECKING:
    pass


# 波动参数配置
ATTRIBUTE_VARIANCE_CONFIG: Dict[str, object] = {
    "min_ratio": 0.88,      # 单项最低不低于模板的88%
    "max_ratio": 1.12,      # 单项最高不超过模板的112%
    "max_deviation": 3,     # 单次偏移最多±3点
    "luck_deviation": 5,    # 运势偏移范围±5点
}


MIN_RATIO = float(ATTRIBUTE_VARIANCE_CONFIG.get("min_ratio", 0.88))  # type: ignore[arg-type]
MAX_RATIO = float(ATTRIBUTE_VARIANCE_CONFIG.get("max_ratio", 1.12))  # type: ignore[arg-type]


def _int_config(config: Mapping[str, object], key: str, default: int) -> int:
    value = config.get(key, default)
    try:
        if isinstance(value, bool):
            return default
        return int(value)  # type: ignore[arg-type, call-overload]
    except (TypeError, ValueError):
        return default


# 硬约束
MAX_GROWABLE_ATTRIBUTE = 99  # 可成长属性硬上限


def apply_recruitment_variance(
    template_attrs: Dict[str, int],
    rarity: str,
    archetype: str,
    rng: Optional[random.Random] = None
) -> Dict[str, int]:
    """
    为招募的门客应用属性随机波动。

    核心机制：
    - 四维总点（武力+智力+防御+敏捷）保持与模板一致（固定总点），仅做再分配
    - 每个属性在模板基础上小幅波动（88%-112%）并通过微调回到固定总点
    - 运势独立波动±5点
    - 保证所有可成长属性 < 100

    Args:
        template_attrs: 模板属性字典 {"force": 52, "intellect": 21, ...}
        rarity: 稀有度（用于日志和验证）
        archetype: 职业类型（用于日志和验证）
        rng: 随机数生成器（可选，用于测试）

    Returns:
        波动后的属性字典

    Examples:
        >>> template = {"force": 52, "intellect": 21, "defense": 59, "agility": 43, "luck": 45}
        >>> result = apply_recruitment_variance(template, "green", "military")
        >>> # 四维总点保持不变（仅再分配）
        >>> sum(result[k] for k in ["force", "intellect", "defense", "agility"]) == 175
        True
    """
    if rng is None:
        rng = random.Random()

    growable = ["force", "intellect", "defense", "agility"]
    base_total = sum(template_attrs[attr] for attr in growable)

    # 步骤1：固定四维总点（与模板一致）
    target_total = base_total

    # 步骤2：生成平衡的随机偏移（总和为0，用于分配属性）
    deviations = _generate_balanced_deviations(template_attrs, growable, rng)

    # 步骤3：应用偏移并做约束检查
    result = {}
    for attr in growable:
        base_value = template_attrs[attr]
        deviation = deviations[attr]

        # 计算波动后的值
        new_value = base_value + deviation

        # 约束1：不低于88%，不超过112%
        min_value = max(1, int(base_value * MIN_RATIO))
        max_value = int(base_value * MAX_RATIO)
        new_value = max(min_value, min(max_value, new_value))

        # 约束2：可成长属性 < 100
        new_value = min(new_value, MAX_GROWABLE_ATTRIBUTE)

        result[attr] = new_value

    # 步骤4：修正总点数到目标值（固定总点）
    current_total = sum(result.values())
    if current_total != target_total:
        result = _adjust_to_target_total(result, target_total, template_attrs, growable)

    # 步骤5：运势波动±5点
    base_luck = template_attrs["luck"]
    luck_dev = _int_config(ATTRIBUTE_VARIANCE_CONFIG, "luck_deviation", 5)
    luck_deviation = rng.randint(
        -luck_dev,
        luck_dev,
    )
    result["luck"] = max(1, base_luck + luck_deviation)  # 确保运势至少为1

    return result


def _generate_balanced_deviations(
    template_attrs: Dict[str, int],
    growable: list,
    rng: random.Random
) -> Dict[str, int]:
    """
    生成平衡的偏移量（总和为0）。

    策略：
    - 所有属性先生成在限制范围内的随机偏移
    - 如果总和不为0，通过成对调整来平衡（增减相抵）
    - 确保每个���性的最终偏移都在 ±max_deviation 范围内

    Args:
        template_attrs: 模板属性字典
        growable: 可成长属性列表
        rng: 随机数生成器

    Returns:
        偏移量字典
    """
    max_dev = _int_config(ATTRIBUTE_VARIANCE_CONFIG, "max_deviation", 3)

    # 计算每个属性的实际最大偏移（受模板值12%限制）
    attr_max_devs = {}
    for attr in growable:
        base_value = template_attrs[attr]
        attr_max_devs[attr] = min(max_dev, int(base_value * 0.12))

    # 步骤1：所有属性生成随机偏移（都在各自限制范围内）
    deviations = {}
    for attr in growable:
        deviation = rng.randint(-attr_max_devs[attr], attr_max_devs[attr])
        deviations[attr] = deviation

    # 步骤2：平衡总和到0
    total = sum(deviations.values())

    # 迭代调整，每次调整1点，确保不超限
    max_iterations = 20
    iteration = 0
    while total != 0 and iteration < max_iterations:
        if total > 0:
            # 总和为正，需要减少某个属性
            # 找一个还有减少空间的属性
            candidates = [
                attr for attr in growable
                if deviations[attr] > -attr_max_devs[attr]
            ]
            if not candidates:
                break
            attr_to_adjust = rng.choice(candidates)
            deviations[attr_to_adjust] -= 1
            total -= 1
        else:
            # 总和为负，需要增加某个属性
            candidates = [
                attr for attr in growable
                if deviations[attr] < attr_max_devs[attr]
            ]
            if not candidates:
                break
            attr_to_adjust = rng.choice(candidates)
            deviations[attr_to_adjust] += 1
            total += 1
        iteration += 1

    return deviations


def _adjust_to_target_total(
    attrs: Dict[str, int],
    target_total: int,
    template_attrs: Dict[str, int],
    growable: list
) -> Dict[str, int]:
    """
    微调属性使总和等于目标值。

    策略：
    - 总点不足：从最低的属性增加（优先增加有余量的）
    - 总点过多：从最高的属性减少（优先减少有余量的）

    Args:
        attrs: 当前属性字典
        target_total: 目标总点数
        template_attrs: 模板属性字典（用于计算余量）
        growable: 可成长属性列表

    Returns:
        调整后的属性字典
    """
    adjusted = attrs.copy()
    iterations = 0
    max_iterations = 20  # 防止无限循环

    while sum(adjusted[attr] for attr in growable) != target_total and iterations < max_iterations:
        current_total = sum(adjusted[attr] for attr in growable)
        diff = target_total - current_total

        if diff > 0:
            # 需要增加：选择最低的且还有余量的属性
            candidates = [
                attr for attr in growable
                if adjusted[attr] < MAX_GROWABLE_ATTRIBUTE
                and adjusted[attr] < int(template_attrs[attr] * MAX_RATIO)
            ]
            if candidates:
                attr_to_adjust = min(candidates, key=lambda k: adjusted[k])
                adjusted[attr_to_adjust] = min(
                    adjusted[attr_to_adjust] + min(diff, 1),
                    MAX_GROWABLE_ATTRIBUTE,
                    int(template_attrs[attr_to_adjust] * MAX_RATIO)
                )
            else:
                break  # 无法继续增加
        else:
            # 需要减少：选择最高的且还有余量的属性
            candidates = [
                attr for attr in growable
                if adjusted[attr] > max(1, int(template_attrs[attr] * MIN_RATIO))
            ]
            if candidates:
                attr_to_adjust = max(candidates, key=lambda k: adjusted[k])
                min_value = max(1, int(template_attrs[attr_to_adjust] * MIN_RATIO))
                adjusted[attr_to_adjust] = max(
                    adjusted[attr_to_adjust] + max(diff, -1),
                    min_value
                )
            else:
                break  # 无法继续减少

        iterations += 1

    return adjusted


def calculate_talent_grade(
    guest_attrs: Dict[str, int],
    base_total: int
) -> str:
    """
    计算门客的资质评级。

    基于四维总点在同稀有度同职业中的相对位置。
    注意：由于我们使用固定总点，所有门客总点相同，
    此函数保留以便未来扩展其他评级标准。

    Args:
        guest_attrs: 门客属性字典
        base_total: 该稀有度职业的基准总点

    Returns:
        资质评级：exceptional/superior/normal/inferior
    """
    growable = ["force", "intellect", "defense", "agility"]
    total = sum(guest_attrs[attr] for attr in growable)

    # 由于固定总点，这里总是返回normal
    # 未来可以基于属性分布的"均衡度"或其他指标评级
    if total == base_total:
        return "normal"

    # 理论上不会到达这里（固定总点）
    diff = total - base_total
    if abs(diff) <= 2:
        return "normal"
    elif diff > 2:
        return "superior"
    else:
        return "inferior"


# 资质评级显示配置
TALENT_GRADE_DISPLAY = {
    "exceptional": {"name": "绝佳", "color": "gold"},
    "superior": {"name": "优秀", "color": "purple"},
    "normal": {"name": "普通", "color": "blue"},
    "inferior": {"name": "平庸", "color": "gray"},
}
