"""
冶炼坊服务模块

提供金属冶炼与药品制作相关功能。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List

from django.db import transaction
from django.utils import timezone

from common.utils.celery import safe_apply_async
from core.utils.time_scale import scale_duration

from ...constants import BuildingKeys
from ...models import Manor, SmeltingProduction
from ..utils.notifications import notify_user

logger = logging.getLogger(__name__)

# 制作配置（向后兼容沿用 METAL_CONFIG 名称）
# 金属：
# - 冶炼技等级需求：1级铜，2级锡，3级铁
# - 消耗材料：1白银→1铜，5铜→1锡，3锡→1铁
# - 时间：1、3、5分钟
# 药品（冶炼坊等级）：
# - Lv1 止血散（50银两，5分钟）
# - Lv3 金创药（100银两，7分钟）
# - Lv5 白芨丸（150银两，10分钟）
# - Lv7 白草丹（200银两，12分钟）
# - Lv8 补血丹（300银两，12分钟）
# - Lv9 丁香丹（600银两，15分钟）
# - Lv10 天香玉露丸（1000银两，20分钟）
METAL_CONFIG: Dict[str, Dict[str, Any]] = {
    "tong": {
        "cost_type": "silver",  # 消耗类型
        "cost_amount": 1,  # 单个消耗数量
        "base_duration": 60,  # 1分钟
        "required_smelting": 1,
        "category": "metal",
    },
    "xi": {
        "cost_type": "tong",  # 消耗铜
        "cost_amount": 5,  # 5铜→1锡
        "base_duration": 180,  # 3分钟
        "required_smelting": 2,
        "category": "metal",
    },
    "tie": {
        "cost_type": "xi",  # 消耗锡
        "cost_amount": 3,  # 3锡→1铁
        "base_duration": 300,  # 5分钟
        "required_smelting": 3,
        "category": "metal",
    },
    "zhixuesan": {
        "cost_type": "silver",
        "cost_amount": 50,
        "base_duration": 300,  # 5分钟
        "required_smithy": 1,
        "category": "medicine",
    },
    "jinchuangyao": {
        "cost_type": "silver",
        "cost_amount": 100,
        "base_duration": 420,  # 7分钟
        "required_smithy": 3,
        "category": "medicine",
    },
    "baijiwan": {
        "cost_type": "silver",
        "cost_amount": 150,
        "base_duration": 600,  # 10分钟
        "required_smithy": 5,
        "category": "medicine",
    },
    "baicaodan": {
        "cost_type": "silver",
        "cost_amount": 200,
        "base_duration": 720,  # 12分钟
        "required_smithy": 7,
        "category": "medicine",
    },
    "buxuedan": {
        "cost_type": "silver",
        "cost_amount": 300,
        "base_duration": 720,  # 12分钟
        "required_smithy": 8,
        "category": "medicine",
    },
    "dingxiangdan": {
        "cost_type": "silver",
        "cost_amount": 600,
        "base_duration": 900,  # 15分钟
        "required_smithy": 9,
        "category": "medicine",
    },
    "tianxiangyuluwan": {
        "cost_type": "silver",
        "cost_amount": 1000,
        "base_duration": 1200,  # 20分钟
        "required_smithy": 10,
        "category": "medicine",
    },
}


def _get_item_name_map(keys: set[str]) -> Dict[str, str]:
    if not keys:
        return {}
    from ...models import ItemTemplate

    return {tpl.key: tpl.name for tpl in ItemTemplate.objects.filter(key__in=keys).only("key", "name")}


def _get_unlock_requirement(config: Dict[str, Any], smelting_level: int, smithy_level: int) -> tuple[bool, int, str]:
    """返回解锁状态、需求等级、需求类型标签。"""
    required_smithy = int(config.get("required_smithy") or 0)
    if required_smithy > 0:
        return smithy_level >= required_smithy, required_smithy, "冶炼坊"

    required_smelting = int(config.get("required_smelting") or 0)
    if required_smelting > 0:
        return smelting_level >= required_smelting, required_smelting, "冶炼技"

    return True, 0, ""


def get_smithy_speed_bonus(manor: Manor) -> float:
    """
    获取冶炼坊速度加成。

    10级满级提升50%，每级约5%。

    Args:
        manor: 庄园实例

    Returns:
        速度加成倍率（如0.5表示减少50%时间）
    """
    level = manor.get_building_level(BuildingKeys.SMITHY)
    return level * 0.05


def get_max_smelting_quantity(manor: Manor) -> int:
    """
    获取单次冶炼金属的最大数量。

    冶炼技每级增加100个上限，满级5级=500个。

    Args:
        manor: 庄园实例

    Returns:
        最大冶炼数量
    """
    from ..technology import get_player_technology_level

    smelting_level = get_player_technology_level(manor, "smelting")
    # 每级100个，最少1个（0级时也能冶炼1个）
    return max(1, smelting_level * 100)


def calculate_smelting_duration(base_duration: int, manor: Manor) -> int:
    """
    计算实际冶炼时间。

    Args:
        base_duration: 基础时间（秒）
        manor: 庄园实例

    Returns:
        实际冶炼时间（秒）
    """
    bonus = get_smithy_speed_bonus(manor)
    # 加成越高，时间越短
    duration = max(1, int(base_duration * (1 - bonus)))
    return scale_duration(duration, minimum=1)


def has_active_smelting_production(manor: Manor) -> bool:
    """
    检查是否有正在进行的冶炼坊制作。

    Args:
        manor: 庄园实例

    Returns:
        是否有制作中的物品
    """
    return manor.smelting_productions.filter(status=SmeltingProduction.Status.PRODUCING).exists()


def get_metal_options(manor: Manor) -> List[Dict[str, Any]]:
    """
    获取冶炼坊制作选项列表。

    Args:
        manor: 庄园实例

    Returns:
        物品选项列表
    """
    from ..inventory import get_item_quantity
    from ..technology import get_player_technology_level

    smelting_level = get_player_technology_level(manor, "smelting")
    smithy_level = manor.get_building_level(BuildingKeys.SMITHY)
    max_quantity = get_max_smelting_quantity(manor)
    is_producing = has_active_smelting_production(manor)

    cost_types = {str(cfg.get("cost_type") or "") for cfg in METAL_CONFIG.values()}
    name_keys = set(METAL_CONFIG.keys()) | {key for key in cost_types if key and key != "silver"}
    item_name_map = _get_item_name_map(name_keys)

    options = []
    for metal_key, config in METAL_CONFIG.items():
        actual_duration = calculate_smelting_duration(config["base_duration"], manor)
        is_unlocked, required_level, required_type_label = _get_unlock_requirement(config, smelting_level, smithy_level)
        cost_type = config["cost_type"]
        cost_amount = config["cost_amount"]
        category = str(config.get("category") or "metal")
        metal_name = item_name_map.get(metal_key, metal_key)
        cost_type_name = "银两" if cost_type == "silver" else item_name_map.get(cost_type, cost_type)

        # 检查是否有足够的材料
        if cost_type == "silver":
            current_amount = manor.silver
        else:
            current_amount = get_item_quantity(manor, cost_type)

        options.append(
            {
                "key": metal_key,
                "name": metal_name,
                "cost_type": cost_type,
                "cost_type_name": cost_type_name,
                "cost_amount": cost_amount,
                "category": category,
                "category_label": "药品" if category == "medicine" else "金属",
                "base_duration": config["base_duration"],
                "actual_duration": actual_duration,
                "can_afford": current_amount >= cost_amount,
                "current_amount": current_amount,
                "required_level": required_level,
                "required_type_label": required_type_label,
                "is_unlocked": is_unlocked,
                "max_quantity": max_quantity,
                "is_producing": is_producing,
            }
        )
    return options


def start_smelting_production(manor: Manor, metal_key: str, quantity: int = 1) -> SmeltingProduction:
    """
    开始冶炼坊制作。

    Args:
        manor: 庄园实例
        metal_key: 物品key
        quantity: 制作数量

    Returns:
        SmeltingProduction实例

    Raises:
        ValueError: 参数错误、资源不足、等级不足或已有制作进行中
    """
    if metal_key not in METAL_CONFIG:
        raise ValueError("无效的制作类型")

    config = METAL_CONFIG[metal_key]

    # 检查解锁条件（冶炼技或冶炼坊等级）
    from ..technology import get_player_technology_level

    smelting_level = get_player_technology_level(manor, "smelting")
    smithy_level = manor.get_building_level(BuildingKeys.SMITHY)
    is_unlocked, required_level, required_type_label = _get_unlock_requirement(config, smelting_level, smithy_level)
    if not is_unlocked:
        item_name_map_for_level = _get_item_name_map({metal_key})
        metal_name_for_level = item_name_map_for_level.get(metal_key, metal_key)
        raise ValueError(f"需要{required_type_label}{required_level}级才能制作{metal_name_for_level}")

    # 验证制作数量
    max_quantity = get_max_smelting_quantity(manor)
    if quantity < 1:
        raise ValueError("制作数量至少为1")
    if quantity > max_quantity:
        raise ValueError(f"冶炼技等级限制，单次最多制作{max_quantity}个")

    # 获取消耗配置
    cost_type = config["cost_type"]
    cost_amount = config["cost_amount"]
    total_cost = cost_amount * quantity

    item_name_map = _get_item_name_map({metal_key, cost_type} - {"silver"})
    metal_name = item_name_map.get(metal_key, metal_key)
    cost_name = "银两" if cost_type == "silver" else item_name_map.get(cost_type, cost_type)

    with transaction.atomic():
        from gameplay.models import Manor as ManorModel

        from ...models import InventoryItem, ResourceEvent
        from ..inventory import consume_inventory_item_locked
        from ..resources import spend_resources_locked

        locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)

        # 锁内再次检查，避免并发下绕过限制
        if has_active_smelting_production(locked_manor):
            raise ValueError("已有物品正在制作中，同时只能制作一种物品")

        # 扣除材料
        if cost_type == "silver":
            if locked_manor.silver < total_cost:
                raise ValueError(f"{cost_name}不足，需要{total_cost}{cost_name}")
            spend_resources_locked(
                locked_manor,
                {"silver": total_cost},
                note=f"制作{metal_name}x{quantity}",
                reason=ResourceEvent.Reason.UPGRADE_COST,
            )
        else:
            # 扣除物品（铜、锡等）
            item = (
                InventoryItem.objects.select_for_update()
                .select_related("template", "manor")
                .filter(
                    manor=locked_manor,
                    template__key=cost_type,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                )
                .first()
            )
            if not item or item.quantity < total_cost:
                raise ValueError(f"{cost_name}不足")
            consume_inventory_item_locked(item, total_cost)

        # 计算实际制作时间（时间不随数量增加）
        actual_duration = calculate_smelting_duration(config["base_duration"], manor)

        # 创建制作记录
        production = SmeltingProduction.objects.create(
            manor=locked_manor,
            metal_key=metal_key,
            metal_name=metal_name,
            quantity=quantity,
            cost_type=cost_type,
            cost_amount=total_cost,
            base_duration=config["base_duration"],
            actual_duration=actual_duration,
            complete_at=timezone.now() + timedelta(seconds=actual_duration),
        )

        # 调度 Celery 任务
        _schedule_smelting_completion(production, actual_duration)

    return production


def _schedule_smelting_completion(production: SmeltingProduction, eta_seconds: int) -> None:
    """
    调度制作完成任务。

    Args:
        production: SmeltingProduction实例
        eta_seconds: 预计完成时间（秒）
    """
    from django.db import transaction as db_transaction

    countdown = max(0, int(eta_seconds))

    try:
        from gameplay.tasks import complete_smelting_production
    except Exception:
        logger.warning("Unable to import complete_smelting_production task; skip scheduling", exc_info=True)
        return

    db_transaction.on_commit(
        lambda: safe_apply_async(
            complete_smelting_production,
            args=[production.id],
            countdown=countdown,
            logger=logger,
            log_message="complete_smelting_production dispatch failed",
        )
    )


def finalize_smelting_production(production: SmeltingProduction, send_notification: bool = False) -> bool:
    """
    完成冶炼坊制作，将物品添加到玩家仓库。

    Args:
        production: SmeltingProduction实例
        send_notification: 是否发送通知

    Returns:
        是否成功完成
    """
    from ...models import Message

    if production.status != SmeltingProduction.Status.PRODUCING:
        return False

    if production.complete_at > timezone.now():
        return False

    with transaction.atomic():
        # 添加物品到仓库（按数量添加）
        from ..inventory import add_item_to_inventory_locked

        add_item_to_inventory_locked(production.manor, production.metal_key, production.quantity)

        # 更新制作状态
        production.status = SmeltingProduction.Status.COMPLETED
        production.finished_at = timezone.now()
        production.save(update_fields=["status", "finished_at"])

    if send_notification:
        from ..utils.messages import create_message

        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        try:
            create_message(
                manor=production.manor,
                kind=Message.Kind.SYSTEM,
                title=f"{production.metal_name}{quantity_text}制作完成",
                body=f"您的{production.metal_name}{quantity_text}已制作完成，请到仓库查收。",
            )

            notify_user(
                production.manor.user_id,
                {
                    "kind": "system",
                    "title": f"{production.metal_name}{quantity_text}制作完成",
                    "metal_key": production.metal_key,
                    "quantity": production.quantity,
                },
                log_context="smelting production notification",
            )
        except Exception as exc:
            logger.warning(
                "smelting production notification failed: production_id=%s manor_id=%s error=%s",
                production.id,
                production.manor_id,
                exc,
                exc_info=True,
            )

    return True


def refresh_smelting_productions(manor: Manor) -> int:
    """
    刷新冶炼坊制作状态，完成所有到期制作。

    Args:
        manor: 庄园实例

    Returns:
        完成的制作数量
    """
    completed = 0
    producing = manor.smelting_productions.filter(
        status=SmeltingProduction.Status.PRODUCING, complete_at__lte=timezone.now()
    )

    for production in producing:
        if finalize_smelting_production(production, send_notification=True):
            completed += 1

    return completed


def get_active_smelting_productions(manor: Manor) -> List[SmeltingProduction]:
    """
    获取正在进行的制作列表。

    Args:
        manor: 庄园实例

    Returns:
        制作列表
    """
    return list(manor.smelting_productions.filter(status=SmeltingProduction.Status.PRODUCING).order_by("complete_at"))
