"""
铁匠铺装备锻造服务模块

提供装备锻造相关功能。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from django.db import transaction
from django.utils import timezone

from core.utils.time_scale import scale_duration

from ...constants import BuildingKeys
from ...models import EquipmentProduction, Manor

# 装备配置
# 锻造技等级需求：1,3,5,7,9级分别解锁不同等级装备
# 材料：铜、锡、铁
EQUIPMENT_CONFIG: Dict[str, Dict[str, Any]] = {
    # ==================== 头盔 ====================
    "equip_bumao": {
        "name": "布帽",
        "category": "helmet",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_niupimao": {
        "name": "牛皮帽",
        "category": "helmet",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_tieyekui": {
        "name": "铁叶盔",
        "category": "helmet",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    # ==================== 护甲 ====================
    "equip_bupao": {
        "name": "布袍",
        "category": "armor",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_shengpijia": {
        "name": "生皮甲",
        "category": "armor",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_housipao": {
        "name": "厚丝袍",
        "category": "armor",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_shapijia": {
        "name": "鲨皮甲",
        "category": "armor",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 鞋子 ====================
    "equip_buxie": {
        "name": "布鞋",
        "category": "shoes",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_yangpixue": {
        "name": "羊皮靴",
        "category": "shoes",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_gangpianxue": {
        "name": "钢片靴",
        "category": "shoes",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_yanyuxue": {
        "name": "燕羽靴",
        "category": "shoes",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 剑 ====================
    "equip_duanjian": {
        "name": "短剑",
        "category": "sword",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_changjian": {
        "name": "长剑",
        "category": "sword",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_qingmangjian": {
        "name": "青芒剑",
        "category": "sword",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_duanmajian": {
        "name": "断马剑",
        "category": "sword",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 刀 ====================
    "equip_duandao": {
        "name": "短刀",
        "category": "dao",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_dakandao": {
        "name": "大砍刀",
        "category": "dao",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_tongchangdao": {
        "name": "铜长刀",
        "category": "dao",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_jingtiedao": {
        "name": "精铁刀",
        "category": "dao",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 枪 ====================
    "equip_changqiang": {
        "name": "长枪",
        "category": "spear",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_baoweiqiang": {
        "name": "豹尾枪",
        "category": "spear",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_hutoumao": {
        "name": "虎头矛",
        "category": "spear",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_pansheqiang": {
        "name": "盘蛇枪",
        "category": "spear",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 弓 ====================
    "equip_changgong": {
        "name": "长弓",
        "category": "bow",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_fanqugong": {
        "name": "反曲弓",
        "category": "bow",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_tietaigong": {
        "name": "铁胎弓",
        "category": "bow",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_shenbigong": {
        "name": "神臂弓",
        "category": "bow",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    # ==================== 鞭 ====================
    "equip_changbian": {
        "name": "长鞭",
        "category": "whip",
        "materials": {"tong": 5},
        "base_duration": 120,
        "required_forging": 1,
    },
    "equip_niupibian": {
        "name": "牛皮鞭",
        "category": "whip",
        "materials": {"tong": 10, "xi": 5},
        "base_duration": 180,
        "required_forging": 3,
    },
    "equip_jicibian": {
        "name": "棘刺鞭",
        "category": "whip",
        "materials": {"tie": 10},
        "base_duration": 240,
        "required_forging": 5,
    },
    "equip_jiulonggangbian": {
        "name": "九龙钢鞭",
        "category": "whip",
        "materials": {"tie": 20},
        "base_duration": 300,
        "required_forging": 7,
    },
    "equip_mingshejiebian": {
        "name": "冥蛇节鞭",
        "category": "whip",
        "materials": {"tie": 30},
        "base_duration": 360,
        "required_forging": 9,
    },
}

# 装备类别
EQUIPMENT_CATEGORIES = {
    "helmet": "头盔",
    "armor": "衣服",
    "shoes": "鞋子",
    "sword": "剑",
    "dao": "刀",
    "spear": "枪",
    "bow": "弓",
    "whip": "鞭",
}

# 材料中文名称
MATERIAL_NAMES = {
    "tong": "铜",
    "xi": "锡",
    "tie": "铁",
}


def get_forge_speed_bonus(manor: Manor) -> float:
    """
    获取铁匠铺速度加成。

    10级满级提升50%，每级约5%。

    Args:
        manor: 庄园实例

    Returns:
        速度加成倍率（如0.5表示减少50%时间）
    """
    level = manor.get_building_level(BuildingKeys.FORGE)
    return level * 0.05


def get_max_forging_quantity(manor: Manor) -> int:
    """
    获取单次锻造装备的最大数量。

    锻造技每级增加50件上限，满级9级=450件。

    Args:
        manor: 庄园实例

    Returns:
        最大锻造数量
    """
    from ..technology import get_player_technology_level

    forging_level = get_player_technology_level(manor, "forging")
    # 每级50件，最少1件（0级时也能锻造1件）
    return max(1, forging_level * 50)


def calculate_forging_duration(base_duration: int, manor: Manor) -> int:
    """
    计算实际锻造时间。

    Args:
        base_duration: 基础时间（秒）
        manor: 庄园实例

    Returns:
        实际锻造时间（秒）
    """
    bonus = get_forge_speed_bonus(manor)
    # 加成越高，时间越短
    duration = max(1, int(base_duration * (1 - bonus)))
    return scale_duration(duration, minimum=1)


def has_active_forging(manor: Manor) -> bool:
    """
    检查是否有正在进行的装备锻造。

    Args:
        manor: 庄园实例

    Returns:
        是否有锻造中的装备
    """
    return manor.equipment_productions.filter(status=EquipmentProduction.Status.FORGING).exists()


def get_equipment_options(manor: Manor, category: str = None) -> List[Dict[str, Any]]:
    """
    获取装备锻造选项列表。

    Args:
        manor: 庄园实例
        category: 可选的装备类别过滤

    Returns:
        装备选项列表
    """
    from ..inventory import get_item_quantity
    from ..technology import get_player_technology_level

    forging_level = get_player_technology_level(manor, "forging")
    max_quantity = get_max_forging_quantity(manor)
    is_forging = has_active_forging(manor)

    options = []
    for equip_key, config in EQUIPMENT_CONFIG.items():
        # 类别过滤
        if category and config["category"] != category:
            continue

        actual_duration = calculate_forging_duration(config["base_duration"], manor)
        required_level = config.get("required_forging", 1)
        is_unlocked = forging_level >= required_level

        # 检查材料是否足够
        materials = config.get("materials", {})
        material_info = []
        can_afford = True
        for mat_key, mat_amount in materials.items():
            current_amount = get_item_quantity(manor, mat_key)
            mat_name = MATERIAL_NAMES.get(mat_key, mat_key)
            material_info.append(
                {
                    "key": mat_key,
                    "name": mat_name,
                    "required": mat_amount,
                    "current": current_amount,
                }
            )
            if current_amount < mat_amount:
                can_afford = False

        options.append(
            {
                "key": equip_key,
                "name": config["name"],
                "category": config["category"],
                "category_name": EQUIPMENT_CATEGORIES.get(config["category"], config["category"]),
                "materials": material_info,
                "base_duration": config["base_duration"],
                "actual_duration": actual_duration,
                "can_afford": can_afford,
                "required_forging": required_level,
                "is_unlocked": is_unlocked,
                "max_quantity": max_quantity,
                "is_forging": is_forging,
            }
        )
    return options


def get_equipment_by_category(manor: Manor) -> Dict[str, Dict[str, Any]]:
    """
    按类别分组获取装备选项。

    Args:
        manor: 庄园实例

    Returns:
        按类别分组的装备选项
    """
    all_options = get_equipment_options(manor)
    grouped = {}
    for category_key, category_name in EQUIPMENT_CATEGORIES.items():
        grouped[category_key] = {
            "name": category_name,
            "items": [opt for opt in all_options if opt["category"] == category_key],
        }
    return grouped


def start_equipment_forging(manor: Manor, equipment_key: str, quantity: int = 1) -> EquipmentProduction:
    """
    开始锻造装备。

    Args:
        manor: 庄园实例
        equipment_key: 装备key
        quantity: 锻造数量

    Returns:
        EquipmentProduction实例

    Raises:
        ValueError: 参数错误、材料不足、科技等级不足或已有锻造进行中
    """
    if equipment_key not in EQUIPMENT_CONFIG:
        raise ValueError("无效的装备类型")

    config = EQUIPMENT_CONFIG[equipment_key]
    required_level = config.get("required_forging", 1)

    # 检查锻造技等级
    from ..technology import get_player_technology_level

    forging_level = get_player_technology_level(manor, "forging")
    if forging_level < required_level:
        raise ValueError(f"需要锻造技{required_level}级才能锻造{config['name']}")

    # 验证锻造数量
    max_quantity = get_max_forging_quantity(manor)
    if quantity < 1:
        raise ValueError("锻造数量至少为1")
    if quantity > max_quantity:
        raise ValueError(f"锻造技等级限制，单次最多锻造{max_quantity}件")

    # 计算总材料消耗
    materials = config.get("materials", {})
    total_costs = {mat_key: mat_amount * quantity for mat_key, mat_amount in materials.items()}

    with transaction.atomic():
        from gameplay.models import Manor as ManorModel

        from ...models import InventoryItem
        from ..inventory import consume_inventory_item_locked

        locked_manor = ManorModel.objects.select_for_update().get(pk=manor.pk)

        if has_active_forging(locked_manor):
            raise ValueError("已有装备正在锻造中，同时只能锻造一种装备")

        # 扣除材料
        for mat_key, total_amount in total_costs.items():
            item = (
                InventoryItem.objects.select_for_update()
                .select_related("template", "manor")
                .filter(
                    manor=locked_manor,
                    template__key=mat_key,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                )
                .first()
            )
            mat_name = MATERIAL_NAMES.get(mat_key, mat_key)
            if not item or item.quantity < total_amount:
                raise ValueError(f"{mat_name}不足")
            consume_inventory_item_locked(item, total_amount)

        # 计算实际锻造时间（时间不随数量增加）
        actual_duration = calculate_forging_duration(config["base_duration"], locked_manor)

        # 创建锻造记录
        production = EquipmentProduction.objects.create(
            manor=locked_manor,
            equipment_key=equipment_key,
            equipment_name=config["name"],
            quantity=quantity,
            material_costs=total_costs,
            base_duration=config["base_duration"],
            actual_duration=actual_duration,
            complete_at=timezone.now() + timedelta(seconds=actual_duration),
        )

        # 调度 Celery 任务
        _schedule_forging_completion(production, actual_duration)

    return production


def _schedule_forging_completion(production: EquipmentProduction, eta_seconds: int) -> None:
    """
    调度锻造完成任务。

    Args:
        production: EquipmentProduction实例
        eta_seconds: 预计完成时间（秒）
    """
    import logging

    from django.db import transaction as db_transaction

    logger = logging.getLogger(__name__)
    countdown = max(0, int(eta_seconds))

    try:
        from gameplay.tasks import complete_equipment_forging
    except Exception:
        logger.warning("Unable to import complete_equipment_forging task; skip scheduling", exc_info=True)
        return

    db_transaction.on_commit(lambda: complete_equipment_forging.apply_async(args=[production.id], countdown=countdown))


def finalize_equipment_forging(production: EquipmentProduction, send_notification: bool = False) -> bool:
    """
    完成装备锻造，将装备添加到玩家仓库。

    Args:
        production: EquipmentProduction实例
        send_notification: 是否发送通知

    Returns:
        是否成功完成
    """
    from ...models import Message
    from ..utils.notifications import notify_user

    with transaction.atomic():
        # 修复：锁定生产记录，防止并发重复领取
        locked_production = EquipmentProduction.objects.select_for_update().get(pk=production.pk)

        if locked_production.status != EquipmentProduction.Status.FORGING:
            return False
        if locked_production.complete_at > timezone.now():
            return False

        # 添加装备到仓库（按数量添加）
        from ..inventory import add_item_to_inventory_locked

        add_item_to_inventory_locked(
            locked_production.manor, locked_production.equipment_key, locked_production.quantity
        )

        # 更新锻造状态
        locked_production.status = EquipmentProduction.Status.COMPLETED
        locked_production.finished_at = timezone.now()
        locked_production.save(update_fields=["status", "finished_at"])

        # 更新传入对象状态，以便后续通知使用正确信息
        production.status = locked_production.status

    if send_notification:
        from ..utils.messages import create_message

        quantity_text = f"x{production.quantity}" if production.quantity > 1 else ""
        create_message(
            manor=production.manor,
            kind=Message.Kind.SYSTEM,
            title=f"{production.equipment_name}{quantity_text}锻造完成",
            body=f"您的{production.equipment_name}{quantity_text}已锻造完成，请到仓库查收。",
        )

        notify_user(
            production.manor.user_id,
            {
                "kind": "system",
                "title": f"{production.equipment_name}{quantity_text}锻造完成",
                "equipment_key": production.equipment_key,
                "quantity": production.quantity,
            },
            log_context="equipment forging notification",
        )

    return True


def refresh_equipment_forgings(manor: Manor) -> int:
    """
    刷新装备锻造状态，完成所有到期的锻造。

    Args:
        manor: 庄园实例

    Returns:
        完成的锻造数量
    """
    completed = 0
    forging = manor.equipment_productions.filter(
        status=EquipmentProduction.Status.FORGING, complete_at__lte=timezone.now()
    )

    for production in forging:
        if finalize_equipment_forging(production, send_notification=True):
            completed += 1

    return completed


def get_active_forgings(manor: Manor) -> List[EquipmentProduction]:
    """
    获取正在进行的锻造列表。

    Args:
        manor: 庄园实例

    Returns:
        锻造列表
    """
    return list(manor.equipment_productions.filter(status=EquipmentProduction.Status.FORGING).order_by("complete_at"))
