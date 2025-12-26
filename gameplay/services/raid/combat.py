"""
踢馆战斗服务

提供踢馆出征、战斗处理、战利品计算等功能。
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction, IntegrityError
from django.db.models import F, Q
from django.utils import timezone

from core.utils.time_scale import scale_duration
from guests.models import Guest, GuestStatus

from ...constants import PVPConstants
from ...models import (
    InventoryItem,
    ItemTemplate,
    Manor,
    PlayerTroop,
    RaidRun,
    ResourceEvent,
)
from ..messages import create_message
from ..resources import grant_resources, log_resource_gain, spend_resources
from .utils import calculate_distance, can_attack_target, is_same_region

logger = logging.getLogger(__name__)


def calculate_raid_travel_time(
    attacker: Manor,
    defender: Manor,
    guests: List[Guest],
    troop_loadout: Dict[str, int]
) -> int:
    """
    计算踢馆行军时间（单程，秒）。

    公式：
    单程时间 = (基础时间 + 距离 × 速度系数) × 跨区系数 × 敏捷修正
    """
    distance = calculate_distance(attacker, defender)
    base_time = PVPConstants.RAID_BASE_TRAVEL_TIME
    distance_time = distance * PVPConstants.RAID_TRAVEL_TIME_PER_DISTANCE

    # 跨区惩罚
    cross_region_mult = 1.0
    if not is_same_region(attacker, defender):
        cross_region_mult = PVPConstants.RAID_CROSS_REGION_MULTIPLIER

    total_time = (base_time + distance_time) * cross_region_mult

    # 敏捷加成：每10点平均敏捷减少1%时间
    if guests:
        avg_agility = sum(g.agility for g in guests) / len(guests)
        agility_reduction = min(0.5, avg_agility / 1000)  # 最多减少50%
        total_time *= (1 - agility_reduction)

    # 骑兵加成：检查是否有骑兵类兵种
    from ..recruitment import load_troop_templates
    templates_data = load_troop_templates()
    cavalry_keys = {"scout"}  # 探子算骑兵
    for tmpl in templates_data.get("troops", []):
        if tmpl.get("speed_bonus", 0) >= 5:
            cavalry_keys.add(tmpl["key"])

    has_cavalry = any(
        key in cavalry_keys and count > 0
        for key, count in troop_loadout.items()
    )
    if has_cavalry:
        total_time *= 0.8  # 骑兵减少20%时间

    return scale_duration(max(60, int(total_time)), minimum=1)  # 最少1分钟（游戏时间）


def get_active_raid_count(manor: Manor) -> int:
    """获取当前进行中的踢馆数量"""
    return RaidRun.objects.filter(
        attacker=manor,
        status__in=[RaidRun.Status.MARCHING, RaidRun.Status.BATTLING, RaidRun.Status.RETURNING]
    ).count()


def get_incoming_raids(manor: Manor) -> List[RaidRun]:
    """获取来袭的敌军列表"""
    return list(
        RaidRun.objects.filter(
            defender=manor,
            status=RaidRun.Status.MARCHING
        ).select_related("attacker").order_by("battle_at")
    )


def _dismiss_marching_raids_if_protected(defender: Manor) -> int:
    """
    检查防守方是否触发保护（24小时被攻击达到上限），如果是则遣返所有正在行军的进攻队伍。

    Args:
        defender: 防守方庄园

    Returns:
        遣返的队伍数量
    """
    now = timezone.now()

    # 检查24小时内被攻击次数（不含正在行军的）
    recent_attacks = RaidRun.objects.filter(
        defender=defender,
        started_at__gte=now - timedelta(hours=24)
    ).exclude(status=RaidRun.Status.MARCHING).count()

    if recent_attacks < PVPConstants.RAID_MAX_DAILY_ATTACKS_RECEIVED:
        return 0

    # 查找所有正在行军中的、目标是该防守方的队伍
    marching_runs = list(
        RaidRun.objects.filter(defender=defender, status=RaidRun.Status.MARCHING)
        .select_related("attacker")
        .prefetch_related("guests")
    )

    if not marching_runs:
        return 0

    dismissed_count = 0
    for run in marching_runs:
        with transaction.atomic():
            # 重新锁定该记录
            locked_run = RaidRun.objects.select_for_update().filter(
                pk=run.pk, status=RaidRun.Status.MARCHING
            ).first()
            if not locked_run:
                continue

            # 计算已行军时间，按原路返回
            elapsed = max(0, int((now - locked_run.started_at).total_seconds()))
            return_time = max(1, elapsed)

            # 设为撤退状态
            locked_run.status = RaidRun.Status.RETREATED
            locked_run.return_at = now + timedelta(seconds=return_time)
            locked_run.save(update_fields=["status", "return_at"])

            # 发送消息通知进攻方
            create_message(
                manor=locked_run.attacker,
                kind="system",
                title="部队已遣返",
                body=f"目标 {defender.display_name} 已触发攻击保护，您的部队已自动遣返。",
            )

        # 调度返程完成任务（事务外）
        try:
            from gameplay.tasks import complete_raid_task
            complete_raid_task.apply_async(args=[run.id], countdown=return_time)
        except Exception:
            logger.warning("complete_raid_task dispatch failed for dismissed raid", exc_info=True)

        dismissed_count += 1

    if dismissed_count > 0:
        logger.info(f"Dismissed {dismissed_count} marching raids to {defender.display_name} due to protection trigger")

    return dismissed_count


def start_raid(
    attacker: Manor,
    defender: Manor,
    guest_ids: List[int],
    troop_loadout: Dict[str, int],
    seed: Optional[int] = None
) -> RaidRun:
    """
    发起踢馆出征。

    Args:
        attacker: 进攻方庄园
        defender: 防守方庄园
        guest_ids: 出征门客ID列表
        troop_loadout: 兵种配置
        seed: 随机数种子（可选）

    Returns:
        踢馆记录

    Raises:
        ValueError: 无法发起踢馆时
    """
    # 检查是否可以攻击目标
    can_attack, reason = can_attack_target(attacker, defender)
    if not can_attack:
        raise ValueError(reason)

    # 检查出征上限
    active_count = get_active_raid_count(attacker)
    if active_count >= PVPConstants.RAID_MAX_CONCURRENT:
        raise ValueError(f"同时最多进行 {PVPConstants.RAID_MAX_CONCURRENT} 次出征")

    # 检查门客
    if not guest_ids:
        raise ValueError("请选择至少一名门客")
    if not isinstance(guest_ids, list):
        raise ValueError("门客参数无效")
    try:
        guest_ids = [int(gid) for gid in guest_ids]
    except (TypeError, ValueError):
        raise ValueError("门客参数无效")

    if troop_loadout is None:
        troop_loadout = {}
    if not isinstance(troop_loadout, dict):
        raise ValueError("护院配置无效")

    run = None
    with transaction.atomic():
        # 锁定并验证门客
        guests = list(
            attacker.guests.select_for_update()
            .filter(id__in=guest_ids)
            .select_related("template")
            .prefetch_related("skills")
        )

        if len(guests) != len(set(guest_ids)):
            raise ValueError("部分门客不可用或已离开庄园")

        # 门客数量不超过出战上限（游侠宝塔）
        max_squad_size = getattr(attacker, "max_squad_size", None) or 0
        if max_squad_size and len(guests) > max_squad_size:
            raise ValueError(f"最多只能派出 {max_squad_size} 名门客出征")

        for guest in guests:
            if guest.status != GuestStatus.IDLE:
                raise ValueError(f"门客 {guest.display_name} 当前不可出征")

        # 规范化兵种配置
        from battle.combatants import normalize_troop_loadout
        loadout = normalize_troop_loadout(troop_loadout, default_if_empty=False)
        loadout = {key: count for key, count in loadout.items() if count > 0}

        # 验证兵力上限
        from battle.services import validate_troop_capacity
        validate_troop_capacity(guests, loadout)

        # 扣除护院
        _deduct_troops(attacker, loadout)

        # 计算行军时间
        travel_time = calculate_raid_travel_time(attacker, defender, guests, loadout)

        # 批量更新门客状态
        for guest in guests:
            guest.status = GuestStatus.DEPLOYED
        Guest.objects.bulk_update(guests, ["status"])

        # 创建踢馆记录
        now = timezone.now()
        battle_at = now + timedelta(seconds=travel_time)
        return_at = now + timedelta(seconds=travel_time * 2)

        run = RaidRun.objects.create(
            attacker=attacker,
            defender=defender,
            troop_loadout=loadout,
            status=RaidRun.Status.MARCHING,
            travel_time=travel_time,
            battle_at=battle_at,
            return_at=return_at,
        )
        run.guests.set(guests)

    # 发送来袭警报给防守方
    _send_raid_incoming_message(run)

    # 调度战斗任务
    try:
        from gameplay.tasks import process_raid_battle_task
        process_raid_battle_task.apply_async(args=[run.id], countdown=travel_time)
    except Exception:
        logger.warning("process_raid_battle_task dispatch failed", exc_info=True)

    return run


def _deduct_troops(manor: Manor, loadout: Dict[str, int]) -> None:
    """从庄园批量扣除指定数量的护院"""
    if not loadout:
        return

    # 过滤掉数量为0的
    loadout = {k: v for k, v in loadout.items() if v > 0}
    if not loadout:
        return

    # 1次查询获取所有需要的护院记录
    troops = {
        t.troop_template.key: t
        for t in PlayerTroop.objects.select_for_update()
        .filter(manor=manor, troop_template__key__in=loadout.keys())
        .select_related("troop_template")
    }

    to_update = []
    for troop_key, count in loadout.items():
        troop = troops.get(troop_key)
        if not troop:
            raise ValueError("没有该类型的护院")
        if troop.count < count:
            raise ValueError(f"护院 {troop.troop_template.name} 数量不足")
        troop.count -= count
        to_update.append(troop)

    # 1次批量更新
    if to_update:
        PlayerTroop.objects.bulk_update(to_update, ["count", "updated_at"])


def _send_raid_incoming_message(run: RaidRun) -> None:
    """发送来袭警报消息"""
    # 格式化预计抵达时间
    arrive_time = run.battle_at.strftime("%Y-%m-%d %H:%M:%S")

    body = f"""来自 {run.attacker.location_display} 的 {run.attacker.display_name} 正在向你发起进攻！

预计抵达时间：{arrive_time}

请立即做好防守准备！"""

    create_message(
        manor=run.defender,
        kind="system",
        title="紧急警报 - 敌军来袭！",
        body=body,
    )


def process_raid_battle(run: RaidRun, now=None) -> None:
    """
    处理踢馆战斗。

    Args:
        run: 踢馆记录
        now: 当前时间（可选）
    """
    now = now or timezone.now()

    with transaction.atomic():
        locked_run = RaidRun.objects.select_for_update().select_related(
            "attacker", "defender"
        ).prefetch_related("guests").filter(pk=run.pk).first()

        if not locked_run:
            return

        # 检查状态
        if locked_run.status == RaidRun.Status.RETREATED:
            # 已撤退，直接完成
            _finalize_raid_retreat(locked_run, now)
            return

        if locked_run.status != RaidRun.Status.MARCHING:
            return

        locked_run.status = RaidRun.Status.BATTLING
        locked_run.save(update_fields=["status"])

        # 执行战斗
        report = _execute_raid_battle(locked_run)

        # 应用防守方护院损失（护院实际损耗）
        _apply_defender_troop_losses(locked_run.defender, report)

        # 判定胜负
        is_attacker_victory = report.winner == "attacker"
        locked_run.is_attacker_victory = is_attacker_victory
        locked_run.battle_report = report

        # 计算战利品（仅进攻方胜利时）
        if is_attacker_victory:
            locked_defender = Manor.objects.select_for_update().get(pk=locked_run.defender_id)
            loot_resources, loot_items = _calculate_loot(locked_defender)
            # 扣除防守方资源和物品，记录实际扣除量
            applied_resources, applied_items = _apply_loot(
                locked_defender,
                loot_resources,
                loot_items,
                locked_manor=locked_defender,
            )
            locked_run.loot_resources = applied_resources
            locked_run.loot_items = applied_items

        # 计算声望变化
        _apply_prestige_changes(locked_run, is_attacker_victory)

        # 计算并发放战斗通用奖励（经验果+装备回收）给胜利方
        from gameplay.services.battle_salvage import calculate_battle_salvage, grant_battle_salvage

        exp_fruit_count, equipment_recovery = calculate_battle_salvage(report)
        if exp_fruit_count > 0 or equipment_recovery:
            winner_manor = locked_run.attacker if is_attacker_victory else locked_run.defender
            grant_battle_salvage(winner_manor, exp_fruit_count, equipment_recovery)
            # 记录战斗奖励到 run 以便消息显示
            locked_run.battle_rewards = {
                "exp_fruit": exp_fruit_count,
                "equipment": equipment_recovery,
            }

        # 更新状态为返程
        locked_run.status = RaidRun.Status.RETURNING
        locked_run.save()

    # 发送战报消息
    _send_raid_battle_messages(locked_run)

    # 检查防守方是否触发保护（达到24小时被攻击上限），遣返其他正在路上的进攻队伍
    _dismiss_marching_raids_if_protected(locked_run.defender)

    # 调度返程完成任务
    try:
        from gameplay.tasks import complete_raid_task
        remaining = locked_run.travel_time  # 返程时间等于单程时间
        complete_raid_task.apply_async(args=[locked_run.id], countdown=remaining)
    except Exception:
        logger.warning("complete_raid_task dispatch failed", exc_info=True)


def _execute_raid_battle(run: RaidRun):
    """执行踢馆战斗"""
    from battle.services import simulate_report

    attacker = run.attacker
    defender = run.defender
    guests = list(run.guests.select_for_update().select_related("template").prefetch_related("skills"))
    loadout = run.troop_loadout or {}

    # 到达时刻快照：防守方为庄园中未出征的门客与护院（仅取空闲门客）
    defender_guests = list(
        defender.guests.select_for_update()
        .filter(status=GuestStatus.IDLE)
        .select_related("template")
        .prefetch_related("skills")
        .order_by("-template__rarity", "-level", "id")
    )

    defender_troops: Dict[str, int] = {}
    for troop in (
        PlayerTroop.objects.select_for_update()
        .filter(manor=defender, count__gt=0)
        .select_related("troop_template")
    ):
        defender_troops[troop.troop_template.key] = troop.count

    defender_setup = {
        "troop_loadout": defender_troops,
        "technology": {},  # 可扩展防守方科技
    }

    report = simulate_report(
        manor=attacker,
        battle_type="raid",
        troop_loadout=loadout,
        fill_default_troops=False,
        attacker_guests=guests,
        defender_setup=defender_setup,
        defender_guests=defender_guests,
        defender_max_squad=getattr(defender, "max_squad_size", None),
        opponent_name=defender.display_name,
        travel_seconds=0,
        send_message=False,
        auto_reward=False,
        apply_damage=True,
        use_lock=False,
    )

    return report


def _calculate_loot(defender: Manor) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    计算战利品。

    Returns:
        (掠夺的资源, 掠夺的物品)
    """
    # 资源掠夺：10%~30%
    loot_percent = random.uniform(
        PVPConstants.LOOT_RESOURCE_MIN_PERCENT,
        PVPConstants.LOOT_RESOURCE_MAX_PERCENT
    )

    loot_resources = {}
    if defender.grain > 0:
        loot_grain = min(
            int(defender.grain * loot_percent),
            10000  # 单次上限
        )
        if loot_grain > 0:
            loot_resources["grain"] = loot_grain

    if defender.silver > 0:
        loot_silver = min(
            int(defender.silver * loot_percent),
            10000
        )
        if loot_silver > 0:
            loot_resources["silver"] = loot_silver

    # 物品掠夺
    loot_items = {}
    tradeable_items = InventoryItem.objects.filter(
        manor=defender,
        template__tradeable=True,
        quantity__gt=0,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE
    ).select_related("template")

    items_looted = 0
    for item in tradeable_items:
        if items_looted >= PVPConstants.LOOT_ITEM_MAX_COUNT:
            break

        # 计算掠夺概率
        rarity = item.template.rarity or "gray"
        rarity_mult = PVPConstants.RARITY_LOOT_MULTIPLIER.get(rarity, 1.0)
        loot_chance = PVPConstants.LOOT_ITEM_BASE_CHANCE * rarity_mult

        if random.random() < loot_chance:
            # 掠夺数量
            max_qty = min(
                int(item.quantity * PVPConstants.LOOT_ITEM_MAX_QUANTITY_PERCENT),
                PVPConstants.LOOT_ITEM_MAX_QUANTITY
            )
            loot_qty = random.randint(1, max(1, max_qty))
            loot_qty = min(loot_qty, item.quantity)

            if loot_qty > 0:
                loot_items[item.template.key] = loot_qty
                items_looted += 1

    return loot_resources, loot_items


def _apply_loot(
    defender: Manor,
    loot_resources: Dict[str, int],
    loot_items: Dict[str, int],
    locked_manor: Manor | None = None,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    从防守方扣除被掠夺的资源和物品，返回实际扣除量。
    """
    manor = locked_manor or Manor.objects.select_for_update().get(pk=defender.pk)
    actual_resources: Dict[str, int] = {}
    actual_items: Dict[str, int] = {}

    # 扣除资源（按当前可用量裁剪，避免不足导致回滚）
    for resource_key, amount in loot_resources.items():
        if amount <= 0:
            continue
        current_value = getattr(manor, resource_key, 0)
        deducted = min(current_value, amount)
        if deducted <= 0:
            continue
        setattr(manor, resource_key, current_value - deducted)
        actual_resources[resource_key] = deducted

    if actual_resources:
        manor.save(update_fields=list(actual_resources.keys()))
        log_resource_gain(
            manor,
            {key: -val for key, val in actual_resources.items()},
            ResourceEvent.Reason.ADMIN_ADJUST,
            note="踢馆被掠夺",
        )

    # 扣除物品（按当前库存裁剪）
    for item_key, qty in loot_items.items():
        if qty <= 0:
            continue
        try:
            item = InventoryItem.objects.select_for_update().get(
                manor=defender,
                template__key=item_key,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE
            )
        except InventoryItem.DoesNotExist:
            continue
        deducted = min(item.quantity, qty)
        if deducted <= 0:
            continue
        item.quantity -= deducted
        if item.quantity <= 0:
            item.delete()
        else:
            item.save(update_fields=["quantity", "updated_at"])
        actual_items[item_key] = deducted

    return actual_resources, actual_items


def _apply_prestige_changes(run: RaidRun, is_attacker_victory: bool) -> None:
    """应用声望变化"""
    from ..prestige import PRESTIGE_SILVER_THRESHOLD
    from gameplay.models import Manor as ManorModel

    if is_attacker_victory:
        attacker_change = PVPConstants.RAID_ATTACKER_WIN_PRESTIGE
        defender_change = PVPConstants.RAID_DEFENDER_LOSE_PRESTIGE
    else:
        attacker_change = PVPConstants.RAID_ATTACKER_LOSE_PRESTIGE
        defender_change = PVPConstants.RAID_DEFENDER_WIN_PRESTIGE

    def _apply_pvp_delta(manor: Manor, delta: int) -> int:
        """
        将踢馆声望变化作用于“PVP附加声望”部分，避免覆盖消费声望。

        Returns:
            实际总声望变化值（考虑下限后的结果）
        """
        before_total = manor.prestige
        spending_prestige = manor.prestige_silver_spent // PRESTIGE_SILVER_THRESHOLD
        before_pvp = max(0, before_total - spending_prestige)
        after_pvp = max(0, before_pvp + delta)
        after_total = spending_prestige + after_pvp
        manor.prestige = after_total
        manor.save(update_fields=["prestige"])
        return after_total - before_total

    # 行级锁防并发（例如多场踢馆同时结算）
    attacker = ManorModel.objects.select_for_update().get(pk=run.attacker_id)
    defender = ManorModel.objects.select_for_update().get(pk=run.defender_id)

    run.attacker_prestige_change = _apply_pvp_delta(attacker, attacker_change)
    run.defender_prestige_change = _apply_pvp_delta(defender, defender_change)


def _send_raid_battle_messages(run: RaidRun) -> None:
    """发送踢馆战报消息"""
    is_victory = run.is_attacker_victory
    battle_rewards = run.battle_rewards or {}
    battle_rewards_desc = _format_battle_rewards_description(battle_rewards)

    # 进攻方消息
    if is_victory:
        attacker_title = "踢馆战报 - 踢馆胜利"
        loot_desc = _format_loot_description(run.loot_resources, run.loot_items)
        attacker_body = f"""对 {run.defender.display_name} 的踢馆行动取得胜利！

战利品：
{loot_desc}

声望变化：+{run.attacker_prestige_change}"""
        # 胜利方获得战斗通用奖励
        if battle_rewards_desc:
            attacker_body += f"""

战斗回收：
{battle_rewards_desc}"""
    else:
        attacker_title = "踢馆战报 - 踢馆失败"
        attacker_body = f"""对 {run.defender.display_name} 的踢馆行动失败了。

声望变化：{run.attacker_prestige_change}"""

    create_message(
        manor=run.attacker,
        kind="battle",
        title=attacker_title,
        body=attacker_body,
        battle_report=run.battle_report,
    )

    # 防守方消息
    if is_victory:
        defender_title = "踢馆战报 - 防守失败"
        loot_desc = _format_loot_description(run.loot_resources, run.loot_items)
        defender_body = f"""来自 {run.attacker.location_display} 的 {run.attacker.display_name} 踢馆成功！

损失：
{loot_desc}

声望变化：{run.defender_prestige_change}
已获得30分钟战败保护"""
    else:
        defender_title = "踢馆战报 - 防守成功"
        defender_body = f"""成功抵御了来自 {run.attacker.location_display} 的 {run.attacker.display_name} 的踢馆！

声望变化：+{run.defender_prestige_change}"""
        # 防守方胜利时获得战斗通用奖励
        if battle_rewards_desc:
            defender_body += f"""

战斗回收：
{battle_rewards_desc}"""

    create_message(
        manor=run.defender,
        kind="battle",
        title=defender_title,
        body=defender_body,
        battle_report=run.battle_report,
    )


def _format_loot_description(resources: Dict[str, int], items: Dict[str, int]) -> str:
    """格式化战利品描述"""
    parts = []

    if resources.get("grain"):
        parts.append(f"粮食 {resources['grain']}")
    if resources.get("silver"):
        parts.append(f"银两 {resources['silver']}")

    if items:
        templates = {
            t.key: t.name
            for t in ItemTemplate.objects.filter(key__in=items.keys())
        }
        for key, qty in items.items():
            name = templates.get(key, key)
            parts.append(f"{name} x{qty}")

    return "\n".join(parts) if parts else "无"


def _format_battle_rewards_description(battle_rewards: Dict[str, Any]) -> str:
    """格式化战斗通用奖励描述"""
    if not battle_rewards:
        return ""

    parts = []
    exp_fruit = battle_rewards.get("exp_fruit", 0)
    equipment = battle_rewards.get("equipment", {})

    if exp_fruit > 0:
        parts.append(f"经验果 x{exp_fruit}")

    if equipment:
        templates = {
            t.key: t.name
            for t in ItemTemplate.objects.filter(key__in=equipment.keys())
        }
        for key, qty in equipment.items():
            name = templates.get(key, key)
            parts.append(f"{name} x{qty}")

    return "\n".join(parts) if parts else ""


def finalize_raid(run: RaidRun, now=None) -> None:
    """
    完成踢馆返程，释放门客和发放战利品。

    Args:
        run: 踢馆记录
        now: 当前时间（可选）
    """
    now = now or timezone.now()

    with transaction.atomic():
        locked_run = RaidRun.objects.select_for_update().select_related(
            "attacker", "defender", "battle_report"
        ).prefetch_related("guests").filter(pk=run.pk).first()

        if not locked_run:
            return

        if locked_run.status == RaidRun.Status.COMPLETED:
            return

        # 批量释放门客
        guests = list(locked_run.guests.select_for_update())
        guests_to_update = []
        for guest in guests:
            # 保留战斗造成的重伤状态，仅将仍处于 DEPLOYED 的门客恢复为空闲
            if guest.status == GuestStatus.DEPLOYED:
                guest.status = GuestStatus.IDLE
                guests_to_update.append(guest)

        if guests_to_update:
            Guest.objects.bulk_update(guests_to_update, ["status"])

        # 归还进攻方护院（存活的）
        _return_surviving_troops(locked_run)

        # 发放战利品给进攻方
        if locked_run.is_attacker_victory:
            if locked_run.loot_resources:
                grant_resources(
                    locked_run.attacker,
                    locked_run.loot_resources,
                    note="踢馆掠夺",
                    reason=ResourceEvent.Reason.BATTLE_REWARD
                )
            if locked_run.loot_items:
                _grant_loot_items(locked_run.attacker, locked_run.loot_items)

        locked_run.status = RaidRun.Status.COMPLETED
        locked_run.completed_at = now
        locked_run.save(update_fields=["status", "completed_at"])


def _return_surviving_troops(run: RaidRun) -> None:
    """批量归还存活的护院"""
    loadout = run.troop_loadout or {}
    if not loadout:
        return

    if not run.battle_report:
        # 没有战报（撤退等情况），全部归还
        _add_troops_batch(run.attacker, loadout)
        return

    # 根据战报计算存活护院
    attacker_losses = (run.battle_report.losses or {}).get("attacker", {}) or {}
    casualties = attacker_losses.get("casualties", []) or []

    from battle.troops import load_troop_templates
    troop_definitions = load_troop_templates()

    troops_lost: Dict[str, int] = {}
    for entry in casualties:
        key = entry.get("key")
        if key not in loadout:
            continue
        if key not in troop_definitions:
            continue
        try:
            lost = int(entry.get("lost", 0) or 0)
        except (TypeError, ValueError):
            continue
        if lost > 0:
            troops_lost[key] = troops_lost.get(key, 0) + lost

    # 计算存活数量
    surviving_troops = {}
    for troop_key, original_count in loadout.items():
        lost = troops_lost.get(troop_key, 0)
        surviving = max(0, original_count - lost)
        if surviving > 0:
            surviving_troops[troop_key] = surviving

    # 批量归还
    if surviving_troops:
        _add_troops_batch(run.attacker, surviving_troops)


def _apply_defender_troop_losses(defender: Manor, report) -> None:
    """
    批量应用防守方护院损失到 PlayerTroop（护院实际损耗）。

    说明：
    - 进攻方护院：在出征时已扣除，返程时仅归还存活的（见 _return_surviving_troops）
    - 防守方护院：未预扣，因此需要在战斗结算时扣除阵亡数量
    """
    defender_loadout = getattr(report, "defender_troops", None) or {}
    defender_losses = (getattr(report, "losses", None) or {}).get("defender", {}) or {}
    casualties = defender_losses.get("casualties", []) or []

    from battle.troops import load_troop_templates
    troop_definitions = load_troop_templates()

    troops_lost: Dict[str, int] = {}
    for entry in casualties:
        key = entry.get("key")
        if key not in defender_loadout:
            continue
        if key not in troop_definitions:
            continue
        try:
            lost = int(entry.get("lost", 0) or 0)
        except (TypeError, ValueError):
            continue
        if lost > 0:
            troops_lost[key] = troops_lost.get(key, 0) + lost

    if not troops_lost:
        return

    # 1次查询获取所有需要更新的护院记录
    troops = {
        t.troop_template.key: t
        for t in PlayerTroop.objects.select_for_update()
        .filter(manor=defender, troop_template__key__in=troops_lost.keys())
        .select_related("troop_template")
    }

    to_update = []
    for troop_key, lost in troops_lost.items():
        troop = troops.get(troop_key)
        if not troop:
            continue
        troop.count = max(0, troop.count - lost)
        to_update.append(troop)

    # 1次批量更新
    if to_update:
        PlayerTroop.objects.bulk_update(to_update, ["count", "updated_at"])


def _add_troops(manor: Manor, troop_key: str, count: int) -> None:
    """给庄园添加护院（单个兵种）"""
    if count <= 0:
        return
    _add_troops_batch(manor, {troop_key: count})


def _add_troops_batch(manor: Manor, troops_to_add: Dict[str, int]) -> None:
    """批量给庄园添加护院"""
    from battle.models import TroopTemplate

    if not troops_to_add:
        return

    # 过滤掉数量为0的
    troops_to_add = {k: v for k, v in troops_to_add.items() if v > 0}
    if not troops_to_add:
        return

    # 预加载模板
    templates = {
        t.key: t for t in TroopTemplate.objects.filter(key__in=troops_to_add.keys())
    }

    if not templates:
        return

    # 预加载现有护院
    existing = {
        pt.troop_template.key: pt
        for pt in PlayerTroop.objects.select_for_update()
        .filter(manor=manor, troop_template__key__in=troops_to_add.keys())
        .select_related("troop_template")
    }

    to_update = []
    to_create = []
    now = timezone.now()

    for key, count in troops_to_add.items():
        template = templates.get(key)
        if not template:
            logger.warning(f"Unknown troop template: {key}")
            continue

        if key in existing:
            existing[key].count += count
            existing[key].updated_at = now
            to_update.append(existing[key])
        else:
            to_create.append(PlayerTroop(
                manor=manor,
                troop_template=template,
                count=count,
            ))

    if to_update:
        PlayerTroop.objects.bulk_update(to_update, ["count", "updated_at"])
    if to_create:
        try:
            PlayerTroop.objects.bulk_create(to_create, ignore_conflicts=True)
        except IntegrityError:
            # 并发创建时回退到逐个处理
            for pt in to_create:
                PlayerTroop.objects.filter(manor=manor, troop_template=pt.troop_template).update(
                    count=F("count") + pt.count,
                    updated_at=now,
                )


def _grant_loot_items(manor: Manor, items: Dict[str, int]) -> None:
    """批量发放掠夺的物品"""
    if not items:
        return

    templates = {
        t.key: t
        for t in ItemTemplate.objects.filter(key__in=items.keys())
    }

    if not templates:
        return

    # 预��载现有库存
    existing_items = {
        item.template.key: item
        for item in InventoryItem.objects.filter(
            manor=manor,
            template__key__in=items.keys(),
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        ).select_related("template")
    }

    to_update: List[InventoryItem] = []
    to_create: List[InventoryItem] = []

    for key, qty in items.items():
        template = templates.get(key)
        if not template:
            continue

        existing = existing_items.get(key)
        if existing:
            existing.quantity += qty
            to_update.append(existing)
        else:
            to_create.append(InventoryItem(
                manor=manor,
                template=template,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                quantity=qty,
            ))

    # 批量创建新物品
    if to_create:
        InventoryItem.objects.bulk_create(to_create)

    # 批量更新现有物品
    if to_update:
        InventoryItem.objects.bulk_update(to_update, ["quantity"])


def request_raid_retreat(run: RaidRun) -> None:
    """
    请求踢馆撤退（仅在行军阶段可用）。

    Args:
        run: 踢馆记录

    Raises:
        ValueError: 无法撤退时
    """
    if run.status != RaidRun.Status.MARCHING:
        raise ValueError("当前状态无法撤退")

    if run.is_retreating:
        raise ValueError("已在撤退中")

    now = timezone.now()
    elapsed = max(0, int((now - run.started_at).total_seconds()))

    with transaction.atomic():
        locked_run = RaidRun.objects.select_for_update().filter(pk=run.pk).first()
        if not locked_run or locked_run.status != RaidRun.Status.MARCHING:
            raise ValueError("当前状态无法撤退")

        locked_run.is_retreating = True
        locked_run.status = RaidRun.Status.RETREATED
        locked_run.return_at = now + timedelta(seconds=max(1, elapsed))
        locked_run.save(update_fields=["is_retreating", "status", "return_at"])

    # 调度撤退完成任务
    try:
        from gameplay.tasks import complete_raid_task
        countdown = max(1, elapsed)
        complete_raid_task.apply_async(args=[run.id], countdown=countdown)
    except Exception:
        logger.warning("complete_raid_task dispatch failed for retreat", exc_info=True)


def _finalize_raid_retreat(run: RaidRun, now=None) -> None:
    """完成撤退，归还所有护院和门客"""
    now = now or timezone.now()

    # 批量释放门客
    guests = list(run.guests.select_for_update())
    for guest in guests:
        guest.status = GuestStatus.IDLE
    if guests:
        Guest.objects.bulk_update(guests, ["status"])

    # 批量全额归还护院
    loadout = run.troop_loadout or {}
    if loadout:
        _add_troops_batch(run.attacker, loadout)

    run.status = RaidRun.Status.COMPLETED
    run.completed_at = now
    run.save(update_fields=["status", "completed_at"])


def can_raid_retreat(run: RaidRun, now=None) -> bool:
    """判断踢馆是否可以撤退"""
    if run.status != RaidRun.Status.MARCHING:
        return False
    if run.is_retreating:
        return False
    return True


def refresh_raid_runs(manor: Manor) -> None:
    """刷新庄园的踢馆状态"""
    now = timezone.now()

    # 处理行军中但已到达战斗时间的
    marching_runs = RaidRun.objects.filter(
        attacker=manor,
        status=RaidRun.Status.MARCHING,
        battle_at__lte=now
    )
    for run in marching_runs:
        process_raid_battle(run, now=now)

    # 处理返程中但已完成的
    returning_runs = RaidRun.objects.filter(
        attacker=manor,
        status=RaidRun.Status.RETURNING,
        return_at__lte=now
    )
    for run in returning_runs:
        finalize_raid(run, now=now)


def get_active_raids(manor: Manor) -> List[RaidRun]:
    """获取进行中的踢馆列表"""
    return list(
        RaidRun.objects.filter(
            attacker=manor,
            status__in=[RaidRun.Status.MARCHING, RaidRun.Status.RETURNING]
        ).select_related("defender", "battle_report").order_by("-started_at")
    )


def get_raid_history(manor: Manor, limit: int = 20) -> List[RaidRun]:
    """获取踢馆历史记录"""
    return list(
        RaidRun.objects.filter(
            Q(attacker=manor) | Q(defender=manor)
        ).select_related(
            "attacker", "defender", "battle_report"
        ).order_by("-started_at")[:limit]
    )


# 需要导入 models
