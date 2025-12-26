"""
马房服务模块

提供马匹生产相关功能。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Any

from django.db import transaction
from django.utils import timezone

from core.utils.time_scale import scale_duration

from ..constants import BuildingKeys
from ..models import HorseProduction, Manor


# 马匹配置
HORSE_CONFIG = {
    "equip_zaohongma": {
        "name": "枣红马",
        "grain_cost": 500,
        "base_duration": 120,  # 2分钟
        "required_horsemanship": 1,  # 需要驯马术1级
    },
    "equip_huangbiaoma": {
        "name": "黄骠马",
        "grain_cost": 800,
        "base_duration": 180,  # 3分钟
        "required_horsemanship": 3,  # 需要驯马术3级
    },
    "equip_dawanma": {
        "name": "大宛马",
        "grain_cost": 1200,
        "base_duration": 240,  # 4分钟
        "required_horsemanship": 5,  # 需要驯马术5级
    },
}


def get_stable_speed_bonus(manor: Manor) -> float:
    """
    获取马房速度加成。

    10级满级提升50%，每级约5%。

    Args:
        manor: 庄园实例

    Returns:
        速度加成倍率（如0.5表示减少50%时间）
    """
    level = manor.get_building_level(BuildingKeys.STABLE)
    # 10级满级提升50%
    return level * 0.05


def get_max_production_quantity(manor: Manor) -> int:
    """
    获取单次生产马匹的最大数量。

    驯马术每级增加100匹上限，满级5级=500匹。

    Args:
        manor: 庄园实例

    Returns:
        最大生产数量
    """
    from .technology import get_player_technology_level

    horsemanship_level = get_player_technology_level(manor, "horsemanship")
    # 每级100匹，最少1匹（0级时也能生产1匹）
    return max(1, horsemanship_level * 100)


def calculate_production_duration(base_duration: int, manor: Manor) -> int:
    """
    计算实际生产时间。

    Args:
        base_duration: 基础时间（秒）
        manor: 庄园实例

    Returns:
        实际生产时间（秒）
    """
    bonus = get_stable_speed_bonus(manor)
    # 加成越高，时间越短
    duration = max(1, int(base_duration * (1 - bonus)))
    return scale_duration(duration, minimum=1)


def has_active_production(manor: Manor) -> bool:
    """
    检查是否有正在进行的马匹生产。

    Args:
        manor: 庄园实例

    Returns:
        是否有生产中的马匹
    """
    return manor.horse_productions.filter(
        status=HorseProduction.Status.PRODUCING
    ).exists()


def get_horse_options(manor: Manor) -> List[Dict[str, Any]]:
    """
    获取马匹生产选项列表。

    Args:
        manor: 庄园实例

    Returns:
        马匹选项列表
    """
    from .technology import get_player_technology_level

    horsemanship_level = get_player_technology_level(manor, "horsemanship")
    max_quantity = get_max_production_quantity(manor)
    is_producing = has_active_production(manor)

    options = []
    for horse_key, config in HORSE_CONFIG.items():
        actual_duration = calculate_production_duration(config["base_duration"], manor)
        required_level = config.get("required_horsemanship", 1)
        is_unlocked = horsemanship_level >= required_level
        options.append({
            "key": horse_key,
            "name": config["name"],
            "grain_cost": config["grain_cost"],
            "base_duration": config["base_duration"],
            "actual_duration": actual_duration,
            "can_afford": manor.grain >= config["grain_cost"],
            "required_horsemanship": required_level,
            "is_unlocked": is_unlocked,
            "max_quantity": max_quantity,
            "is_producing": is_producing,
        })
    return options


def start_horse_production(manor: Manor, horse_key: str, quantity: int = 1) -> HorseProduction:
    """
    开始生产马匹。

    Args:
        manor: 庄园实例
        horse_key: 马匹key
        quantity: 生产数量

    Returns:
        HorseProduction实例

    Raises:
        ValueError: 参数错误、资源不足、科技等级不足或已有生产进行中
    """
    if horse_key not in HORSE_CONFIG:
        raise ValueError("无效的马匹类型")

    # 检查是否已有生产进行中
    if has_active_production(manor):
        raise ValueError("已有马匹正在生产中，同时只能生产一种马匹")

    config = HORSE_CONFIG[horse_key]
    required_level = config.get("required_horsemanship", 1)

    # 检查驯马术等级
    from .technology import get_player_technology_level
    horsemanship_level = get_player_technology_level(manor, "horsemanship")
    if horsemanship_level < required_level:
        raise ValueError(f"需要驯马术{required_level}级才能生产{config['name']}")

    # 验证生产数量
    max_quantity = get_max_production_quantity(manor)
    if quantity < 1:
        raise ValueError("生产数量至少为1")
    if quantity > max_quantity:
        raise ValueError(f"驯马术等级限制，单次最多生产{max_quantity}匹")

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
            note=f"生产{config['name']}x{quantity}",
            reason=ResourceEvent.Reason.UPGRADE_COST,
        )

        # 计算实际生产时间（时间不随数量增加）
        actual_duration = calculate_production_duration(config["base_duration"], manor)

        # 创建生产记录
        production = HorseProduction.objects.create(
            manor=manor,
            horse_key=horse_key,
            horse_name=config["name"],
            quantity=quantity,
            grain_cost=total_grain_cost,
            base_duration=config["base_duration"],
            actual_duration=actual_duration,
            complete_at=timezone.now() + timedelta(seconds=actual_duration),
        )

        # 调度 Celery 任务
        _schedule_production_completion(production, actual_duration)

    return production


def _schedule_production_completion(production: HorseProduction, eta_seconds: int) -> None:
    """
    调度生产完成任务。

    Args:
        production: HorseProduction实例
        eta_seconds: 预计完成时间（秒）
    """
    import logging
    from django.db import transaction as db_transaction

    logger = logging.getLogger(__name__)
    countdown = max(0, int(eta_seconds))

    try:
        from gameplay.tasks import complete_horse_production
    except Exception:
        logger.warning("Unable to import complete_horse_production task; skip scheduling", exc_info=True)
        return

    db_transaction.on_commit(
        lambda: complete_horse_production.apply_async(args=[production.id], countdown=countdown)
    )


def finalize_horse_production(production: HorseProduction, send_notification: bool = False) -> bool:
    """
    完成马匹生产，将马匹添加到玩家仓库。

    Args:
        production: HorseProduction实例
        send_notification: 是否发送通知

    Returns:
        是否成功完成
    """
    import logging
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    from ..models import Message

    logger = logging.getLogger(__name__)

    if production.status != HorseProduction.Status.PRODUCING:
        return False

    if production.complete_at > timezone.now():
        return False

    with transaction.atomic():
        # 添加马匹到仓库（按数量添加）
        from .inventory import add_item_to_inventory

        add_item_to_inventory(production.manor, production.horse_key, production.quantity)

        # 更新生产状态
        production.status = HorseProduction.Status.COMPLETED
        production.finished_at = timezone.now()
        production.save(update_fields=["status", "finished_at"])

    if send_notification:
        from .messages import create_message

        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        create_message(
            manor=production.manor,
            kind=Message.Kind.SYSTEM,
            title=f"{production.horse_name}{quantity_text}生产完成",
            body=f"您的{production.horse_name}{quantity_text}已生产完成，请到仓库查收。",
        )

        channel_layer = get_channel_layer()
        if channel_layer:
            payload = {
                "kind": "system",
                "title": f"{production.horse_name}{quantity_text}生产完成",
                "horse_key": production.horse_key,
                "quantity": production.quantity,
            }
            try:
                async_to_sync(channel_layer.group_send)(
                    f"user_{production.manor.user_id}",
                    {"type": "notify.message", "payload": payload},
                )
            except Exception:
                logger.warning("Failed to send horse production notification via channels", exc_info=True)

    return True


def refresh_horse_productions(manor: Manor) -> int:
    """
    刷新马匹生产状态，完成所有到期的生产。

    Args:
        manor: 庄园实例

    Returns:
        完成的生产数量
    """
    completed = 0
    producing = manor.horse_productions.filter(
        status=HorseProduction.Status.PRODUCING,
        complete_at__lte=timezone.now()
    )

    for production in producing:
        if finalize_horse_production(production, send_notification=True):
            completed += 1

    return completed


def get_active_productions(manor: Manor) -> List[HorseProduction]:
    """
    获取正在进行的生产列表。

    Args:
        manor: 庄园实例

    Returns:
        生产列表
    """
    return list(
        manor.horse_productions.filter(
            status=HorseProduction.Status.PRODUCING
        ).order_by("complete_at")
    )
