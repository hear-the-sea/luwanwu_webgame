"""
踢馆系统工具函数

提供距离计算、声望颜色、攻击检查等基础工具。
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Optional, Tuple

from django.db.models import F, Sum
from django.utils import timezone

from ...constants import PVPConstants
from ...models import InventoryItem, Manor, RaidRun


def calculate_distance(manor1: Manor, manor2: Manor) -> float:
    """
    计算两个庄园之间的距离。

    Args:
        manor1: 庄园1
        manor2: 庄园2

    Returns:
        欧几里得距离
    """
    dx = manor1.coordinate_x - manor2.coordinate_x
    dy = manor1.coordinate_y - manor2.coordinate_y
    return math.sqrt(dx * dx + dy * dy)


def is_same_region(manor1: Manor, manor2: Manor) -> bool:
    """判断两个庄园是否在同一地区"""
    return manor1.region == manor2.region


def get_prestige_color(my_prestige: int, target_prestige: int) -> str:
    """
    根据声望差值计算颜色标识。

    Args:
        my_prestige: 我方声望
        target_prestige: 目标声望

    Returns:
        颜色标识: 'green'（弱小）, 'white'（势均力敌）, 'red'（强大）
    """
    diff = target_prestige - my_prestige
    if diff < -PVPConstants.RAID_PRESTIGE_RANGE:
        return "green"  # 对方声望低于我方500以上
    elif diff > PVPConstants.RAID_PRESTIGE_RANGE:
        return "red"  # 对方声望高于我方500以上
    return "white"  # 势均力敌


def can_attack_target(
    attacker: Manor,
    defender: Manor,
    *,
    recent_attacks: Optional[int] = None,
    now: Optional[timezone.datetime] = None,
) -> Tuple[bool, str]:
    """
    检查是否可以攻击目标庄园。

    Args:
        attacker: 进攻方庄园
        defender: 防守方庄园
        recent_attacks: 可选的“目标24小时内被攻击次数”预计算值；提供时将跳过数据库 COUNT
        now: 可选的当前时间（用于批量计算时复用）

    Returns:
        (是否可攻击, 原因说明)
    """
    # 不能攻击自己
    if attacker.id == defender.id:
        return False, "不能攻击自己的庄园"

    # 检查进攻方保护状态
    if attacker.is_under_newbie_protection:
        return False, "新手保护期内无法发起攻击"
    if attacker.is_under_peace_shield:
        return False, "免战牌保护期内无法发起攻击"

    # 检查防守方保护状态
    if defender.is_under_newbie_protection:
        return False, "对方处于新手保护期"
    if defender.is_under_peace_shield:
        return False, "对方处于免战牌保护期"

    # 检查声望差值
    color = get_prestige_color(attacker.prestige, defender.prestige)
    if color == "green":
        return False, "对方声望过低，无法攻击"
    if color == "red":
        return False, "对方声望过高，无法攻击"

    # 检查目标24小时内被攻击次数（防止小号集群攻击）
    now = now or timezone.now()
    if recent_attacks is None:
        recent_attacks = RaidRun.objects.filter(defender=defender, started_at__gte=now - timedelta(hours=24)).count()
    if recent_attacks >= PVPConstants.RAID_MAX_DAILY_ATTACKS_RECEIVED:
        return False, "该目标今日已被多次攻击，暂时无法攻击"

    return True, ""


def get_asset_level(manor: Manor) -> Tuple[str, int]:
    """
    计算庄园的资产等级。

    Args:
        manor: 庄园对象

    Returns:
        (资产等级名称, 总资产值)
    """
    # 计算总资产 = 粮食 + 银两 + 仓库物品总价值
    total_assets = manor.grain + manor.silver

    # 使用聚合查询计算仓库物品总价值（优化：避免循环查询）
    item_value = (
        InventoryItem.objects.filter(manor=manor, storage_location=InventoryItem.StorageLocation.WAREHOUSE).aggregate(
            total=Sum(F("quantity") * F("template__price"))
        )["total"]
        or 0
    )

    total_assets += item_value

    # 判断资产等级
    if total_assets < PVPConstants.ASSET_LEVEL_POOR:
        return "匮乏", total_assets
    elif total_assets < PVPConstants.ASSET_LEVEL_NORMAL:
        return "一般", total_assets
    elif total_assets < PVPConstants.ASSET_LEVEL_RICH:
        return "充裕", total_assets
    else:
        return "富足", total_assets


def get_troop_description(total_count: int) -> str:
    """
    根据护院总数返回模糊描述。

    Args:
        total_count: 护院总数

    Returns:
        模糊描述文字
    """
    if total_count < 100:
        return "少量"
    elif total_count < 500:
        return "旗鼓相当"
    elif total_count < 2000:
        return "较多"
    else:
        return "庞大"
