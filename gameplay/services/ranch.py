"""
畜牧场服务模块

提供家畜养殖相关功能。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from django.db import transaction
from django.utils import timezone

from core.utils.time_scale import scale_duration

from ..constants import BuildingKeys
from ..models import LivestockProduction, Manor


# 家畜配置
# 养殖术等级需求：1级鸡，3级鸭，5级鹅，7级猪，9级牛
LIVESTOCK_CONFIG = {
    "ji": {
        "name": "鸡",
        "grain_cost": 50,
        "base_duration": 120,  # 2分钟
        "required_animal_husbandry": 1,
    },
    "ya": {
        "name": "鸭",
        "grain_cost": 100,
        "base_duration": 180,  # 3分钟
        "required_animal_husbandry": 3,
    },
    "e": {
        "name": "鹅",
        "grain_cost": 200,
        "base_duration": 240,  # 4分钟
        "required_animal_husbandry": 5,
    },
    "zhu": {
        "name": "猪",
        "grain_cost": 400,
        "base_duration": 300,  # 5分钟
        "required_animal_husbandry": 7,
    },
    "niu": {
        "name": "牛",
        "grain_cost": 750,
        "base_duration": 360,  # 6分钟
        "required_animal_husbandry": 9,
    },
}


def get_ranch_speed_bonus(manor: Manor) -> float:
    """
    获取畜牧场速度加成。

    10级满级提升50%，每级约5%。

    Args:
        manor: 庄园实例

    Returns:
        速度加成倍率（如0.5表示减少50%时间）
    """
    level = manor.get_building_level(BuildingKeys.RANCH)
    return level * 0.05


def get_max_livestock_quantity(manor: Manor) -> int:
    """
    获取单次养殖家畜的最大数量。

    养殖术每级增加50只上限，满级10级=500只。

    Args:
        manor: 庄园实例

    Returns:
        最大养殖数量
    """
    from .technology import get_player_technology_level

    animal_husbandry_level = get_player_technology_level(manor, "animal_husbandry")
    # 每级50只，最少1只（0级时也能养殖1只）
    return max(1, animal_husbandry_level * 50)


def calculate_livestock_duration(base_duration: int, manor: Manor) -> int:
    """
    计算实际养殖时间。

    Args:
        base_duration: 基础时间（秒）
        manor: 庄园实例

    Returns:
        实际养殖时间（秒）
    """
    bonus = get_ranch_speed_bonus(manor)
    # 加成越高，时间越短
    duration = max(1, int(base_duration * (1 - bonus)))
    return scale_duration(duration, minimum=1)


def has_active_livestock_production(manor: Manor) -> bool:
    """
    检查是否有正在进行的家畜养殖。

    Args:
        manor: 庄园实例

    Returns:
        是否有养殖中的家畜
    """
    return manor.livestock_productions.filter(
        status=LivestockProduction.Status.PRODUCING
    ).exists()


def get_livestock_options(manor: Manor) -> List[Dict[str, Any]]:
    """
    获取家畜养殖选项列表。

    Args:
        manor: 庄园实例

    Returns:
        家畜选项列表
    """
    from .technology import get_player_technology_level

    animal_husbandry_level = get_player_technology_level(manor, "animal_husbandry")
    max_quantity = get_max_livestock_quantity(manor)
    is_producing = has_active_livestock_production(manor)

    options = []
    for livestock_key, config in LIVESTOCK_CONFIG.items():
        actual_duration = calculate_livestock_duration(config["base_duration"], manor)
        required_level = config.get("required_animal_husbandry", 1)
        is_unlocked = animal_husbandry_level >= required_level
        options.append({
            "key": livestock_key,
            "name": config["name"],
            "grain_cost": config["grain_cost"],
            "base_duration": config["base_duration"],
            "actual_duration": actual_duration,
            "can_afford": manor.grain >= config["grain_cost"],
            "required_animal_husbandry": required_level,
            "is_unlocked": is_unlocked,
            "max_quantity": max_quantity,
            "is_producing": is_producing,
        })
    return options


def start_livestock_production(manor: Manor, livestock_key: str, quantity: int = 1) -> LivestockProduction:
    """
    开始养殖家畜。

    Args:
        manor: 庄园实例
        livestock_key: 家畜key
        quantity: 养殖数量

    Returns:
        LivestockProduction实例

    Raises:
        ValueError: 参数错误、资源不足、科技等级不足或已有养殖进行中
    """
    if livestock_key not in LIVESTOCK_CONFIG:
        raise ValueError("无效的家畜类型")

    # 检查是否已有养殖进行中
    if has_active_livestock_production(manor):
        raise ValueError("已有家畜正在养殖中，同时只能养殖一种家畜")

    config = LIVESTOCK_CONFIG[livestock_key]
    required_level = config.get("required_animal_husbandry", 1)

    # 检查养殖术等级
    from .technology import get_player_technology_level
    animal_husbandry_level = get_player_technology_level(manor, "animal_husbandry")
    if animal_husbandry_level < required_level:
        raise ValueError(f"需要养殖术{required_level}级才能养殖{config['name']}")

    # 验证养殖数量
    max_quantity = get_max_livestock_quantity(manor)
    if quantity < 1:
        raise ValueError("养殖数量至少为1")
    if quantity > max_quantity:
        raise ValueError(f"养殖术等级限制，单次最多养殖{max_quantity}只")

    # 计算总消耗
    total_grain_cost = config["grain_cost"] * quantity

    if manor.grain < total_grain_cost:
        raise ValueError(f"粮食不足，需要{total_grain_cost}点粮食")

    with transaction.atomic():
        from .resources import spend_resources
        from ..models import ResourceEvent

        # 扣除粮食
        spend_resources(
            manor,
            {"grain": total_grain_cost},
            note=f"养殖{config['name']}x{quantity}",
            reason=ResourceEvent.Reason.UPGRADE_COST,
        )

        # 计算实际养殖时间（时间不随数量增加）
        actual_duration = calculate_livestock_duration(config["base_duration"], manor)

        # 创建养殖记录
        production = LivestockProduction.objects.create(
            manor=manor,
            livestock_key=livestock_key,
            livestock_name=config["name"],
            quantity=quantity,
            grain_cost=total_grain_cost,
            base_duration=config["base_duration"],
            actual_duration=actual_duration,
            complete_at=timezone.now() + timedelta(seconds=actual_duration),
        )

        # 调度 Celery 任务
        _schedule_livestock_completion(production, actual_duration)

    return production


def _schedule_livestock_completion(production: LivestockProduction, eta_seconds: int) -> None:
    """
    调度养殖完成任务。

    Args:
        production: LivestockProduction实例
        eta_seconds: 预计完成时间（秒）
    """
    import logging
    from django.db import transaction as db_transaction

    logger = logging.getLogger(__name__)
    countdown = max(0, int(eta_seconds))

    try:
        from gameplay.tasks import complete_livestock_production
    except Exception:
        logger.warning("Unable to import complete_livestock_production task; skip scheduling", exc_info=True)
        return

    db_transaction.on_commit(
        lambda: complete_livestock_production.apply_async(args=[production.id], countdown=countdown)
    )


def finalize_livestock_production(production: LivestockProduction, send_notification: bool = False) -> bool:
    """
    完成家畜养殖，将家畜添加到玩家仓库。

    Args:
        production: LivestockProduction实例
        send_notification: 是否发送通知

    Returns:
        是否成功完成
    """
    import logging
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    from ..models import Message

    logger = logging.getLogger(__name__)

    if production.status != LivestockProduction.Status.PRODUCING:
        return False

    if production.complete_at > timezone.now():
        return False

    with transaction.atomic():
        # 添加家畜到仓库（按数量添加）
        from .inventory import add_item_to_inventory

        add_item_to_inventory(production.manor, production.livestock_key, production.quantity)

        # 更新养殖状态
        production.status = LivestockProduction.Status.COMPLETED
        production.finished_at = timezone.now()
        production.save(update_fields=["status", "finished_at"])

    if send_notification:
        from .messages import create_message

        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        create_message(
            manor=production.manor,
            kind=Message.Kind.SYSTEM,
            title=f"{production.livestock_name}{quantity_text}养殖完成",
            body=f"您的{production.livestock_name}{quantity_text}已养殖完成，请到仓库查收。",
        )

        channel_layer = get_channel_layer()
        if channel_layer:
            payload = {
                "kind": "system",
                "title": f"{production.livestock_name}{quantity_text}养殖完成",
                "livestock_key": production.livestock_key,
                "quantity": production.quantity,
            }
            try:
                async_to_sync(channel_layer.group_send)(
                    f"user_{production.manor.user_id}",
                    {"type": "notify.message", "payload": payload},
                )
            except Exception:
                logger.warning("Failed to send livestock production notification via channels", exc_info=True)

    return True


def refresh_livestock_productions(manor: Manor) -> int:
    """
    刷新家畜养殖状态，完成所有到期的养殖。

    Args:
        manor: 庄园实例

    Returns:
        完成的养殖数量
    """
    completed = 0
    producing = manor.livestock_productions.filter(
        status=LivestockProduction.Status.PRODUCING,
        complete_at__lte=timezone.now()
    )

    for production in producing:
        if finalize_livestock_production(production, send_notification=True):
            completed += 1

    return completed


def get_active_livestock_productions(manor: Manor) -> List[LivestockProduction]:
    """
    获取正在进行的养殖列表。

    Args:
        manor: 庄园实例

    Returns:
        养殖列表
    """
    return list(
        manor.livestock_productions.filter(
            status=LivestockProduction.Status.PRODUCING
        ).order_by("complete_at")
    )
