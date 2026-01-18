"""
资源计算工具模块

提供资源检查、产量计算等工具函数。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Manor

from ..models import ResourceType
from ..constants import BuildingKeys


# 资源字段列表
RESOURCE_FIELDS = [
    ResourceType.GRAIN,
    ResourceType.SILVER,
]


def has_resources(manor: "Manor", cost: Dict[str, int]) -> bool:
    """
    检查庄园是否有足够的资源。

    Args:
        manor: 庄园实例
        cost: 资源成本字典 {"grain": 50, "silver": 100, ...}

    Returns:
        如果所有资源都足够返回 True，否则返回 False

    Examples:
        >>> # 假设庄园有 grain=200, silver=100
        >>> has_resources(manor, {"grain": 150, "silver": 50})
        True
        >>> has_resources(manor, {"silver": 250})
        False
    """
    return all(getattr(manor, resource) >= amount for resource, amount in cost.items())


def get_hourly_rates(manor: "Manor") -> Dict[str, float]:
    """
    计算庄园每小时的资源产量。

    遍历所有建筑，累加各资源类型的产量。
    技术加成按建筑级别应用（如农耕术只增加农田产量）。
    茅厕除了产粮食外，还额外产出等量银两。

    Args:
        manor: 庄园实例

    Returns:
        资源产量字典 {"grain": 120.0, "silver": 95.0, ...}
    """
    from ..services.technology import (
        get_player_technologies,
        get_resource_production_bonus_from_levels,
    )

    rates = defaultdict(float)
    tech_levels = get_player_technologies(manor)
    for building in manor.buildings.select_related("building_type"):
        base_rate = building.hourly_rate()
        resource_type = building.building_type.resource_type
        bonus = get_resource_production_bonus_from_levels(
            tech_levels,
            resource_type,
            building_key=building.building_type.key,
        )
        rate = base_rate * (1.0 + bonus)
        rates[resource_type] += rate

        # 茅厕特殊效果：额外产出等量银两
        if building.building_type.key == BuildingKeys.LATRINE:
            rates[ResourceType.SILVER] += rate
    return rates


def normalize_mission_loadout(raw: Dict[str, int] | None, troop_templates: Dict) -> Dict[str, int]:
    """
    标准化兵力配置，过滤无效数据并填充默认值。

    Args:
        raw: 原始兵力配置
        troop_templates: 兵种模板字典

    Returns:
        标准化后的兵力配置

    Raises:
        ValueError: 如果 raw 包含不存在的护院类型（安全检查）

    Examples:
        >>> normalize_mission_loadout({"infantry": "100", "invalid": -5}, templates)
        {"infantry": 100, "cavalry": 0, "archer": 0}
    """
    if not troop_templates:
        return {}

    if raw is None:
        raw = {}

    # 安全检查：检测并拒绝不存在的护院类型
    invalid_keys = set(raw.keys()) - set(troop_templates.keys())
    if invalid_keys:
        # 过滤掉数量为0的key（可能是前端传递的空值）
        invalid_nonzero = {k: v for k, v in raw.items() if k in invalid_keys and int(v or 0) > 0}
        if invalid_nonzero:
            raise ValueError(f"护院配置包含不存在的类型: {', '.join(invalid_nonzero.keys())}")

    loadout = {}
    for key in troop_templates.keys():
        value = raw.get(key, 0)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 0
        loadout[key] = max(0, parsed)

    return loadout


def calculate_travel_time(base_time: int, guests, troop_loadout: Dict[str, int], troop_templates: Dict) -> int:
    """
    计算任务旅行时间，考虑门客敏捷和兵种速度加成。

    计算规则：
    - 门客敏捷提供速度加成（每点0.5秒减免）
    - 兵种speed_bonus取加权平均，提供额外减免
    - 最少旅行时间为10秒

    Args:
        base_time: 基础旅行时间（秒）
        guests: 门客列表
        troop_loadout: 兵力配置
        troop_templates: 兵种模板

    Returns:
        实际旅行时间（秒）
    """
    # 门客敏捷加成
    guest_speed = sum(getattr(guest, "agility", 0) for guest in guests)

    # 兵种速度加成（加权平均）
    total_troops = sum(count for count in troop_loadout.values() if count > 0)
    if total_troops > 0:
        weighted_speed = sum(
            count * troop_templates.get(key, {}).get("speed_bonus", 60)
            for key, count in troop_loadout.items()
            if count > 0
        )
        avg_speed = weighted_speed / total_troops
        troop_speed = avg_speed * 0.5
    else:
        troop_speed = 0

    # 总减免时间
    reduction = int((guest_speed * 0.5) + troop_speed)

    return max(10, max(0, base_time - reduction))
