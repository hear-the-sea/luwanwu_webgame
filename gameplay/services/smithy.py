"""
冶炼坊服务模块

提供金属冶炼相关功能。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from django.db import transaction
from django.utils import timezone

from core.utils.time_scale import scale_duration

from ..constants import BuildingKeys
from ..models import SmeltingProduction, Manor
from .notifications import notify_user


# 金属配置
# 冶炼技等级需求：1级铜，2级锡，3级铁
# 消耗材料：1白银→1铜，5铜→1锡，3锡→1铁
# 时间：1、3、5分钟
METAL_CONFIG = {
    "tong": {
        "name": "铜",
        "cost_type": "silver",  # 消耗类型
        "cost_amount": 1,       # 单个消耗数量
        "base_duration": 60,    # 1分钟
        "required_smelting": 1,
    },
    "xi": {
        "name": "锡",
        "cost_type": "tong",    # 消耗铜
        "cost_amount": 5,       # 5铜→1锡
        "base_duration": 180,   # 3分钟
        "required_smelting": 2,
    },
    "tie": {
        "name": "铁",
        "cost_type": "xi",      # 消耗锡
        "cost_amount": 3,       # 3锡→1铁
        "base_duration": 300,   # 5分钟
        "required_smelting": 3,
    },
}


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
    from .technology import get_player_technology_level

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
    检查是否有正在进行的金属冶炼。

    Args:
        manor: 庄园实例

    Returns:
        是否有冶炼中的金属
    """
    return manor.smelting_productions.filter(
        status=SmeltingProduction.Status.PRODUCING
    ).exists()


def get_metal_options(manor: Manor) -> List[Dict[str, Any]]:
    """
    获取金属冶炼选项列表。

    Args:
        manor: 庄园实例

    Returns:
        金属选项列表
    """
    from .technology import get_player_technology_level
    from .inventory import get_item_quantity

    smelting_level = get_player_technology_level(manor, "smelting")
    max_quantity = get_max_smelting_quantity(manor)
    is_producing = has_active_smelting_production(manor)

    # 消耗类型的中文名称
    cost_type_names = {
        "silver": "银两",
        "tong": "铜",
        "xi": "锡",
        "tie": "铁",
    }

    options = []
    for metal_key, config in METAL_CONFIG.items():
        actual_duration = calculate_smelting_duration(config["base_duration"], manor)
        required_level = config.get("required_smelting", 1)
        is_unlocked = smelting_level >= required_level
        cost_type = config["cost_type"]
        cost_amount = config["cost_amount"]
        cost_type_name = cost_type_names.get(cost_type, cost_type)

        # 检查是否有足够的材料
        if cost_type == "silver":
            current_amount = manor.silver
        else:
            current_amount = get_item_quantity(manor, cost_type)

        options.append({
            "key": metal_key,
            "name": config["name"],
            "cost_type": cost_type,
            "cost_type_name": cost_type_name,
            "cost_amount": cost_amount,
            "base_duration": config["base_duration"],
            "actual_duration": actual_duration,
            "can_afford": current_amount >= cost_amount,
            "current_amount": current_amount,
            "required_smelting": required_level,
            "is_unlocked": is_unlocked,
            "max_quantity": max_quantity,
            "is_producing": is_producing,
        })
    return options


def start_smelting_production(manor: Manor, metal_key: str, quantity: int = 1) -> SmeltingProduction:
    """
    开始冶炼金属。

    Args:
        manor: 庄园实例
        metal_key: 金属key
        quantity: 冶炼数量

    Returns:
        SmeltingProduction实例

    Raises:
        ValueError: 参数错误、资源不足、科技等级不足或已有冶炼进行中
    """
    if metal_key not in METAL_CONFIG:
        raise ValueError("无效的金属类型")

    config = METAL_CONFIG[metal_key]
    required_level = config.get("required_smelting", 1)

    # 检查冶炼技等级
    from .technology import get_player_technology_level
    smelting_level = get_player_technology_level(manor, "smelting")
    if smelting_level < required_level:
        raise ValueError(f"需要冶炼技{required_level}级才能冶炼{config['name']}")

    # 验证冶炼数量
    max_quantity = get_max_smelting_quantity(manor)
    if quantity < 1:
        raise ValueError("冶炼数量至少为1")
    if quantity > max_quantity:
        raise ValueError(f"冶炼技等级限制，单次最多冶炼{max_quantity}个")

    # 获取消耗配置
    cost_type = config["cost_type"]
    cost_amount = config["cost_amount"]
    total_cost = cost_amount * quantity

    # 消耗类型的中文名称
    cost_type_names = {
        "silver": "银两",
        "tong": "铜",
        "xi": "锡",
        "tie": "铁",
    }
    cost_name = cost_type_names.get(cost_type, cost_type)

    with transaction.atomic():
        from gameplay.models import Manor as ManorModel
        from .resources import spend_resources_locked
        from .inventory import consume_inventory_item_locked
        from ..models import ResourceEvent, InventoryItem

        locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)

        # 锁内再次检查，避免并发下绕过限制
        if has_active_smelting_production(locked_manor):
            raise ValueError("已有金属正在冶炼中，同时只能冶炼一种金属")

        # 扣除材料
        if cost_type == "silver":
            if locked_manor.silver < total_cost:
                raise ValueError(f"{cost_name}不足，需要{total_cost}{cost_name}")
            spend_resources_locked(
                locked_manor,
                {"silver": total_cost},
                note=f"冶炼{config['name']}x{quantity}",
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

        # 计算实际冶炼时间（时间不随数量增加）
        actual_duration = calculate_smelting_duration(config["base_duration"], manor)

        # 创建冶炼记录
        production = SmeltingProduction.objects.create(
            manor=locked_manor,
            metal_key=metal_key,
            metal_name=config["name"],
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
    调度冶炼完成任务。

    Args:
        production: SmeltingProduction实例
        eta_seconds: 预计完成时间（秒）
    """
    import logging
    from django.db import transaction as db_transaction

    logger = logging.getLogger(__name__)
    countdown = max(0, int(eta_seconds))

    try:
        from gameplay.tasks import complete_smelting_production
    except Exception:
        logger.warning("Unable to import complete_smelting_production task; skip scheduling", exc_info=True)
        return

    db_transaction.on_commit(
        lambda: complete_smelting_production.apply_async(args=[production.id], countdown=countdown)
    )


def finalize_smelting_production(production: SmeltingProduction, send_notification: bool = False) -> bool:
    """
    完成金属冶炼，将金属添加到玩家仓库。

    Args:
        production: SmeltingProduction实例
        send_notification: 是否发送通知

    Returns:
        是否成功完成
    """
    from ..models import Message

    if production.status != SmeltingProduction.Status.PRODUCING:
        return False

    if production.complete_at > timezone.now():
        return False

    with transaction.atomic():
        # 添加金属到仓库（按数量添加）
        from .inventory import add_item_to_inventory_locked

        add_item_to_inventory_locked(production.manor, production.metal_key, production.quantity)

        # 更新冶炼状态
        production.status = SmeltingProduction.Status.COMPLETED
        production.finished_at = timezone.now()
        production.save(update_fields=["status", "finished_at"])

    if send_notification:
        from .messages import create_message

        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        create_message(
            manor=production.manor,
            kind=Message.Kind.SYSTEM,
            title=f"{production.metal_name}{quantity_text}冶炼完成",
            body=f"您的{production.metal_name}{quantity_text}已冶炼完成，请到仓库查收。",
        )

        notify_user(
            production.manor.user_id,
            {
                "kind": "system",
                "title": f"{production.metal_name}{quantity_text}冶炼完成",
                "metal_key": production.metal_key,
                "quantity": production.quantity,
            },
            log_context="smelting production notification",
        )

    return True


def refresh_smelting_productions(manor: Manor) -> int:
    """
    刷新金属冶炼状态，完成所有到期的冶炼。

    Args:
        manor: 庄园实例

    Returns:
        完成的冶炼数量
    """
    completed = 0
    producing = manor.smelting_productions.filter(
        status=SmeltingProduction.Status.PRODUCING,
        complete_at__lte=timezone.now()
    )

    for production in producing:
        if finalize_smelting_production(production, send_notification=True):
            completed += 1

    return completed


def get_active_smelting_productions(manor: Manor) -> List[SmeltingProduction]:
    """
    获取正在进行的冶炼列表。

    Args:
        manor: 庄园实例

    Returns:
        冶炼列表
    """
    return list(
        manor.smelting_productions.filter(
            status=SmeltingProduction.Status.PRODUCING
        ).order_by("complete_at")
    )
