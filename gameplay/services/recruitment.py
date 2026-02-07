"""
护院募兵服务模块

提供护院招募相关功能：
- 加载兵种募兵配置
- 检查募兵条件（科技等级、装备、家丁）
- 开始募兵（消耗装备和家丁）
- 完成募兵（生成护院）
"""
from __future__ import annotations

import os
from datetime import timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional

import yaml
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.utils.time_scale import scale_duration

from ..constants import BuildingKeys
from ..models import Manor, PlayerTroop, TroopRecruitment
from .inventory import get_item_quantity
from .technology import get_player_technology_level


@lru_cache(maxsize=1)
def load_troop_templates() -> Dict[str, Any]:
    """
    加载兵种配置文件。

    Returns:
        包含 troops 列表的字典
    """
    path = os.path.join(settings.BASE_DIR, "data", "troop_templates.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def _build_troop_index() -> Dict[str, Dict[str, Any]]:
    """
    构建兵种索引字典。

    Returns:
        {troop_key: troop_config} 索引字典
    """
    data = load_troop_templates()
    return {troop["key"]: troop for troop in data.get("troops", [])}


def clear_troop_cache() -> None:
    """清理兵种配置缓存。"""
    load_troop_templates.cache_clear()
    _build_troop_index.cache_clear()


def get_troop_template(troop_key: str) -> Optional[Dict[str, Any]]:
    """
    获取单个兵种的配置模板。

    Args:
        troop_key: 兵种标识

    Returns:
        兵种配置字典，不存在则返回 None
    """
    return _build_troop_index().get(troop_key)


def get_recruit_config(troop_key: str) -> Optional[Dict[str, Any]]:
    """
    获取兵种的募兵配置。

    Args:
        troop_key: 兵种标识

    Returns:
        募兵配置字典，不存在则返回 None
    """
    troop = get_troop_template(troop_key)
    if not troop:
        return None
    return troop.get("recruit")


def calculate_recruitment_duration(base_duration: int, manor: Manor) -> int:
    """
    计算实际募兵时间。

    应用两种加成：
    1. 练功场加成：速度倍率（10级满级提升30%，每级约3.33%）
    2. 祠堂加成：速度倍率（5级满级提升120%，每级30%）

    计算公式：实际时间 = 基础时间 / (练功场倍率 × 祠堂倍率)

    Args:
        base_duration: 基础时间（秒）
        manor: 庄园实例

    Returns:
        实际募兵时间（秒）
    """
    # 练功场加成（速度倍率）
    training_multiplier = manor.guard_training_speed_multiplier

    # 祠堂加成（速度倍率）
    citang_multiplier = manor.citang_recruitment_speed_multiplier

    # 综合速度倍率
    total_multiplier = training_multiplier * citang_multiplier

    duration = max(1, int(base_duration / total_multiplier))
    return scale_duration(duration, minimum=1)


def has_active_recruitment(manor: Manor) -> bool:
    """
    检查是否有正在进行的募兵。

    Args:
        manor: 庄园实例

    Returns:
        是否有募兵中的任务
    """
    return manor.troop_recruitments.filter(
        status=TroopRecruitment.Status.RECRUITING
    ).exists()


def check_recruitment_requirements(
    manor: Manor,
    troop_key: str,
    quantity: int = 1,
) -> Dict[str, Any]:
    """
    检查募兵条件是否满足。

    Args:
        manor: 庄园实例
        troop_key: 兵种标识
        quantity: 募兵数量

    Returns:
        {
            "can_recruit": bool,
            "errors": list[str],
            "tech_satisfied": bool,
            "equipment_satisfied": bool,
            "retainer_satisfied": bool,
            "equipment_status": dict,  # {item_key: {"required": int, "have": int, "satisfied": bool}}
        }
    """
    result = {
        "can_recruit": False,
        "errors": [],
        "tech_satisfied": False,
        "equipment_satisfied": False,
        "retainer_satisfied": False,
        "equipment_status": {},
    }

    troop = get_troop_template(troop_key)
    if not troop:
        result["errors"].append("无效的兵种类型")
        return result

    recruit_config = troop.get("recruit")
    if not recruit_config:
        result["errors"].append("该兵种不可募兵")
        return result

    # 检查科技等级
    tech_key = recruit_config.get("tech_key")
    tech_level_required = recruit_config.get("tech_level", 0)

    if tech_key:
        player_tech_level = get_player_technology_level(manor, tech_key)
        if player_tech_level >= tech_level_required:
            result["tech_satisfied"] = True
        else:
            result["errors"].append(f"需要{_get_tech_name(tech_key)}{tech_level_required}级")
    else:
        result["tech_satisfied"] = True

    # 检查装备
    equipment_list = recruit_config.get("equipment", [])
    all_equipment_satisfied = True

    for item_key in equipment_list:
        required = quantity
        have = get_item_quantity(manor, item_key)
        satisfied = have >= required

        result["equipment_status"][item_key] = {
            "required": required,
            "have": have,
            "satisfied": satisfied,
        }

        if not satisfied:
            all_equipment_satisfied = False
            from ..models import ItemTemplate
            try:
                item = ItemTemplate.objects.get(key=item_key)
                result["errors"].append(f"{item.name}不足（需要{required}，拥有{have}）")
            except ItemTemplate.DoesNotExist:
                result["errors"].append(f"装备{item_key}不足")

    result["equipment_satisfied"] = all_equipment_satisfied

    # 检查家丁
    retainer_cost = recruit_config.get("retainer_cost", 1) * quantity
    if manor.retainer_count >= retainer_cost:
        result["retainer_satisfied"] = True
    else:
        result["errors"].append(f"家丁不足（需要{retainer_cost}，拥有{manor.retainer_count}）")

    # 综合判断
    result["can_recruit"] = (
        result["tech_satisfied"]
        and result["equipment_satisfied"]
        and result["retainer_satisfied"]
    )

    return result


def _get_tech_name(tech_key: str) -> str:
    """获取科技名称。"""
    from .technology import get_technology_template
    template = get_technology_template(tech_key)
    return template["name"] if template else tech_key


def get_recruitment_options(manor: Manor) -> List[Dict[str, Any]]:
    """
    获取募兵选项列表。

    Args:
        manor: 庄园实例

    Returns:
        募兵选项列表
    """
    data = load_troop_templates()
    troops = data.get("troops", [])
    is_recruiting = has_active_recruitment(manor)

    options = []
    for troop in troops:
        recruit_config = troop.get("recruit")
        if not recruit_config:
            continue

        troop_key = troop["key"]
        tech_key = recruit_config.get("tech_key")
        tech_level_required = recruit_config.get("tech_level", 0)

        # 获取科技等级
        if tech_key:
            player_tech_level = get_player_technology_level(manor, tech_key)
            is_unlocked = player_tech_level >= tech_level_required
        else:
            player_tech_level = 0
            is_unlocked = True

        # 计算时间
        base_duration = recruit_config.get("base_duration", 120)
        actual_duration = calculate_recruitment_duration(base_duration, manor)

        # 检查装备状态
        equipment_list = recruit_config.get("equipment", [])
        equipment_status = []
        can_afford = True

        for item_key in equipment_list:
            have = get_item_quantity(manor, item_key)
            from ..models import ItemTemplate
            try:
                item = ItemTemplate.objects.get(key=item_key)
                item_name = item.name
            except ItemTemplate.DoesNotExist:
                item_name = item_key

            equipment_status.append({
                "key": item_key,
                "name": item_name,
                "required": 1,
                "have": have,
                "satisfied": have >= 1,
            })
            if have < 1:
                can_afford = False

        # 检查家丁
        retainer_cost = recruit_config.get("retainer_cost", 1)
        retainer_satisfied = manor.retainer_count >= retainer_cost

        options.append({
            "key": troop_key,
            "name": troop["name"],
            "description": troop.get("description", ""),
            "base_attack": troop.get("base_attack", 0),
            "base_defense": troop.get("base_defense", 0),
            "base_hp": troop.get("base_hp", 0),
            "speed_bonus": troop.get("speed_bonus", 0),
            "avatar": troop.get("avatar", ""),
            "tech_key": tech_key,
            "tech_name": _get_tech_name(tech_key) if tech_key else None,
            "tech_level_required": tech_level_required,
            "player_tech_level": player_tech_level,
            "is_unlocked": is_unlocked,
            "equipment": equipment_status,
            "retainer_cost": retainer_cost,
            "retainer_satisfied": retainer_satisfied,
            "base_duration": base_duration,
            "actual_duration": actual_duration,
            "can_afford": can_afford and retainer_satisfied,
            "is_recruiting": is_recruiting,
        })

    return options


def start_troop_recruitment(
    manor: Manor,
    troop_key: str,
    quantity: int = 1,
) -> TroopRecruitment:
    """
    开始募兵。

    Args:
        manor: 庄园实例
        troop_key: 兵种标识
        quantity: 募兵数量

    Returns:
        TroopRecruitment 实例

    Raises:
        ValueError: 参数错误、条件不满足或已有募兵进行中
    """
    if quantity < 1:
        raise ValueError("募兵数量至少为1")

    # 检查是否已有募兵进行中
    if has_active_recruitment(manor):
        raise ValueError("已有募兵正在进行中，同时只能进行一种募兵")

    # 检查练功场等级
    training_level = manor.get_building_level(BuildingKeys.LIANGGONG_CHANG)
    if training_level < 1:
        raise ValueError("练功场等级不足，需要1级以上")

    troop = get_troop_template(troop_key)
    if not troop:
        raise ValueError("无效的兵种类型")

    recruit_config = troop.get("recruit")
    if not recruit_config:
        raise ValueError("该兵种不可募兵")

    # 检查所有条件
    check_result = check_recruitment_requirements(manor, troop_key, quantity)
    if not check_result["can_recruit"]:
        raise ValueError("、".join(check_result["errors"]))

    # 获取配置
    equipment_list = recruit_config.get("equipment", [])
    retainer_cost = recruit_config.get("retainer_cost", 1) * quantity
    base_duration = recruit_config.get("base_duration", 120)

    with transaction.atomic():
        # 扣除装备
        from ..models import InventoryItem

        equipment_costs = {}
        for item_key in equipment_list:
            item = InventoryItem.objects.select_for_update().filter(
                manor=manor,
                template__key=item_key,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            ).first()

            if not item or item.quantity < quantity:
                raise ValueError(f"装备不足: {item_key}")

            item.quantity -= quantity
            if item.quantity <= 0:
                item.delete()
            else:
                item.save(update_fields=["quantity"])

            equipment_costs[item_key] = quantity

        # 扣除家丁
        if manor.retainer_count < retainer_cost:
            raise ValueError(f"家丁不足，需要{retainer_cost}")

        Manor.objects.filter(pk=manor.pk).update(
            retainer_count=manor.retainer_count - retainer_cost
        )
        manor.retainer_count -= retainer_cost

        # 计算实际募兵时间
        actual_duration = calculate_recruitment_duration(base_duration, manor)

        # 创建募兵记录
        recruitment = TroopRecruitment.objects.create(
            manor=manor,
            troop_key=troop_key,
            troop_name=troop["name"],
            quantity=quantity,
            equipment_costs=equipment_costs,
            retainer_cost=retainer_cost,
            base_duration=base_duration,
            actual_duration=actual_duration,
            complete_at=timezone.now() + timedelta(seconds=actual_duration),
        )

        # 调度 Celery 任务
        _schedule_recruitment_completion(recruitment, actual_duration)

    return recruitment


def _schedule_recruitment_completion(recruitment: TroopRecruitment, eta_seconds: int) -> None:
    """
    调度募兵完成任务。

    Args:
        recruitment: TroopRecruitment 实例
        eta_seconds: 预计完成时间（秒）
    """
    import logging
    from django.db import transaction as db_transaction

    logger = logging.getLogger(__name__)
    countdown = max(0, int(eta_seconds))

    try:
        from gameplay.tasks import complete_troop_recruitment
    except Exception:
        logger.warning("Unable to import complete_troop_recruitment task; skip scheduling", exc_info=True)
        return

    db_transaction.on_commit(
        lambda: complete_troop_recruitment.apply_async(args=[recruitment.id], countdown=countdown)
    )


def finalize_troop_recruitment(recruitment: TroopRecruitment, send_notification: bool = False) -> bool:
    """
    完成募兵，将护院添加到玩家存储。

    Args:
        recruitment: TroopRecruitment 实例
        send_notification: 是否发送通知

    Returns:
        是否成功完成
    """
    import logging
    from ..models import Message
    from .notifications import notify_user

    logger = logging.getLogger(__name__)

    if recruitment.status != TroopRecruitment.Status.RECRUITING:
        return False

    if recruitment.complete_at > timezone.now():
        return False

    with transaction.atomic():
        # 添加护院到玩家存储
        from battle.models import TroopTemplate

        try:
            troop_template = TroopTemplate.objects.get(key=recruitment.troop_key)
        except TroopTemplate.DoesNotExist:
            logger.error(f"TroopTemplate not found: {recruitment.troop_key}")
            return False

        player_troop, created = PlayerTroop.objects.get_or_create(
            manor=recruitment.manor,
            troop_template=troop_template,
            defaults={"count": 0},
        )
        player_troop.count += recruitment.quantity
        player_troop.save(update_fields=["count", "updated_at"])

        # 更新募兵状态
        recruitment.status = TroopRecruitment.Status.COMPLETED
        recruitment.finished_at = timezone.now()
        recruitment.save(update_fields=["status", "finished_at"])

    if send_notification:
        from .messages import create_message

        quantity_text = f"x{recruitment.quantity}" if recruitment.quantity > 1 else ""
        create_message(
            manor=recruitment.manor,
            kind=Message.Kind.SYSTEM,
            title=f"{recruitment.troop_name}{quantity_text}募兵完成",
            body=f"您的{recruitment.troop_name}{quantity_text}已募兵完成。",
        )

        notify_user(
            recruitment.manor.user_id,
            {
                "kind": "system",
                "title": f"{recruitment.troop_name}{quantity_text}募兵完成",
                "troop_key": recruitment.troop_key,
                "quantity": recruitment.quantity,
            },
            log_context="troop recruitment notification",
        )

    return True


def refresh_troop_recruitments(manor: Manor) -> int:
    """
    刷新募兵状态，完成所有到期的募兵。

    Args:
        manor: 庄园实例

    Returns:
        完成的募兵数量
    """
    completed = 0
    recruiting = manor.troop_recruitments.filter(
        status=TroopRecruitment.Status.RECRUITING,
        complete_at__lte=timezone.now()
    )

    for recruitment in recruiting:
        if finalize_troop_recruitment(recruitment, send_notification=True):
            completed += 1

    return completed


def get_active_recruitments(manor: Manor) -> List[TroopRecruitment]:
    """
    获取正在进行的募兵列表。

    Args:
        manor: 庄园实例

    Returns:
        募兵列表
    """
    return list(
        manor.troop_recruitments.filter(
            status=TroopRecruitment.Status.RECRUITING
        ).order_by("complete_at")
    )


def get_player_troops(manor: Manor) -> List[Dict[str, Any]]:
    """
    获取玩家已拥有的护院列表（count > 0）。

    Args:
        manor: 庄园实例

    Returns:
        护院列表（只包含数量大于0的护院）
    """
    troops = PlayerTroop.objects.filter(manor=manor, count__gt=0).select_related("troop_template")

    result = []
    for pt in troops:
        template = pt.troop_template

        # 使用数据库的 avatar 字段，与战报保持一致
        avatar_url = template.avatar.url if template.avatar else ""

        result.append({
            "key": template.key,
            "name": template.name,
            "description": template.description,
            "count": pt.count,
            "base_attack": template.base_attack,
            "base_defense": template.base_defense,
            "base_hp": template.base_hp,
            "speed_bonus": template.speed_bonus,
            "avatar": avatar_url,
        })

    return result
