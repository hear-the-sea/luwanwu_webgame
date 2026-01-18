"""
庄园迁移服务

提供庄园迁移、坐标生成等功能。
"""

from __future__ import annotations

import random
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from ...constants import PVPConstants, REGION_DICT
from ...models import Manor
from .combat import get_active_raid_count, get_incoming_raids
from .utils import get_asset_level


def get_relocation_cost(manor: Manor) -> int:
    """
    获取庄园迁移所需的金条数量。

    Returns:
        金条数量
    """
    asset_level, _ = get_asset_level(manor)

    if asset_level == "匮乏":
        return PVPConstants.RELOCATION_COST_POOR
    elif asset_level == "一般":
        return PVPConstants.RELOCATION_COST_NORMAL
    elif asset_level == "充裕":
        return PVPConstants.RELOCATION_COST_RICH
    else:  # 富足
        return PVPConstants.RELOCATION_COST_WEALTHY


def relocate_manor(manor: Manor, new_region: str) -> Tuple[int, int]:
    """
    迁移庄园到新地区。

    Args:
        manor: 庄园
        new_region: 新地区编码

    Returns:
        (新X坐标, 新Y坐标)

    Raises:
        ValueError: 无法迁移时
    """
    # 验证地区
    if new_region not in REGION_DICT:
        raise ValueError("无效的地区")

    # 检查迁移条件
    if not manor.can_relocate:
        if manor.is_under_newbie_protection:
            raise ValueError("新手保护期内无法迁移")
        raise ValueError("迁移冷却中，请稍后再试")

    # 检查是否有出征中的队伍
    active_raids = get_active_raid_count(manor)
    if active_raids > 0:
        raise ValueError("有出征中的队伍，无法迁移")

    # 检查是否有敌军来袭
    incoming = get_incoming_raids(manor)
    if incoming:
        raise ValueError("有敌军来袭，无法迁移")

    # 检查金条（需要考虑拍卖冻结的金条）
    cost = get_relocation_cost(manor)
    from trade.services.auction_service import get_available_gold_bars
    from ..inventory import consume_inventory_item_for_manor_locked

    available_gold = get_available_gold_bars(manor)
    if available_gold < cost:
        raise ValueError(f"可用金条不足，需要 {cost} 个（当前可用 {available_gold} 个）")

    with transaction.atomic():
        # 扣除金条
        consume_inventory_item_for_manor_locked(manor, "gold_bar", cost)

        # 生成新坐标（确保唯一）
        new_x, new_y = _generate_unique_coordinate(new_region, exclude_manor_id=manor.id)

        # 更新庄园
        manor.region = new_region
        manor.coordinate_x = new_x
        manor.coordinate_y = new_y
        manor.last_relocation_at = timezone.now()
        manor.save(update_fields=["region", "coordinate_x", "coordinate_y", "last_relocation_at"])

    return new_x, new_y


def _generate_unique_coordinate(region: str, exclude_manor_id: Optional[int] = None) -> Tuple[int, int]:
    """在指定地区生成唯一坐标"""
    max_attempts = 100

    for _ in range(max_attempts):
        x = random.randint(PVPConstants.COORDINATE_MIN, PVPConstants.COORDINATE_MAX)
        y = random.randint(PVPConstants.COORDINATE_MIN, PVPConstants.COORDINATE_MAX)

        # 检查是否已被占用
        query = Manor.objects.filter(region=region, coordinate_x=x, coordinate_y=y)
        if exclude_manor_id:
            query = query.exclude(id=exclude_manor_id)

        if not query.exists():
            return x, y

    raise ValueError("无法生成唯一坐标，请稍后重试")
