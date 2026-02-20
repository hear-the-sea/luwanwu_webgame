"""
侦察系统服务

提供侦察相关功能：发起侦察、完成侦察、撤退等。
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.db import models, transaction
from django.utils import timezone

from common.utils.celery import safe_apply_async, safe_apply_async_with_dedup

from core.utils.time_scale import scale_duration

from ...constants import PVPConstants
from ...models import Manor, PlayerTroop, ScoutCooldown, ScoutRecord
from ..messages import create_message
from .utils import calculate_distance, can_attack_target, get_asset_level, get_troop_description

logger = logging.getLogger(__name__)


_REFRESH_DISPATCH_DEDUP_SECONDS = 5


def _try_dispatch_scout_refresh_task(task, record_id: int, phase: str) -> bool:
    return safe_apply_async_with_dedup(
        task,
        dedup_key=f"pvp:refresh_dispatch:scout:{phase}:{record_id}",
        dedup_timeout=_REFRESH_DISPATCH_DEDUP_SECONDS,
        args=[record_id],
        countdown=0,
        logger=logger,
        log_message=f"scout refresh dispatch failed: phase={phase} record_id={record_id}",
    )


def _collect_due_scout_record_ids(manor: Manor, now) -> tuple[list[int], list[int]]:
    scouting_ids = list(
        ScoutRecord.objects.filter(
            attacker=manor,
            status=ScoutRecord.Status.SCOUTING,
            complete_at__lte=now,
        ).values_list("id", flat=True)
    )
    returning_ids = list(
        ScoutRecord.objects.filter(
            attacker=manor,
            status=ScoutRecord.Status.RETURNING,
            return_at__lte=now,
        ).values_list("id", flat=True)
    )
    return scouting_ids, returning_ids


def _dispatch_async_scout_refresh(
    scouting_ids: list[int],
    returning_ids: list[int],
) -> tuple[list[int], list[int], bool]:
    try:
        from gameplay.tasks import complete_scout_return_task, complete_scout_task
    except Exception:
        logger.warning("Failed to import scout tasks, falling back to sync refresh", exc_info=True)
        return scouting_ids, returning_ids, False

    sync_scouting_ids: list[int] = []
    for record_id in scouting_ids:
        if not _try_dispatch_scout_refresh_task(complete_scout_task, record_id, "outbound"):
            sync_scouting_ids.append(record_id)

    sync_returning_ids: list[int] = []
    for record_id in returning_ids:
        if not _try_dispatch_scout_refresh_task(complete_scout_return_task, record_id, "return"):
            sync_returning_ids.append(record_id)

    if not sync_scouting_ids and not sync_returning_ids:
        return [], [], True
    return sync_scouting_ids, sync_returning_ids, False


def _finalize_due_scout_records(now, scouting_ids: list[int], returning_ids: list[int]) -> None:
    if scouting_ids:
        scouting_records = ScoutRecord.objects.select_related("attacker", "defender").filter(id__in=scouting_ids)
        for record in scouting_records:
            finalize_scout(record, now=now)

    if returning_ids:
        returning_records = ScoutRecord.objects.select_related("attacker", "defender").filter(id__in=returning_ids)
        for record in returning_records:
            finalize_scout_return(record, now=now)


def get_scout_tech_level(manor: Manor) -> int:
    """获取庄园的侦察术等级"""
    from ..technology import get_player_technology_level
    return get_player_technology_level(manor, "scout_art")


def calculate_scout_success_rate(attacker: Manor, defender: Manor) -> float:
    """
    计算侦察成功率。

    公式：
    基础成功率 = 50%
    成功率修正 = (我方侦察术等级 - 对方侦察术等级) × 5%
    最终成功率 = min(95%, max(10%, 基础成功率 + 成功率修正))
    """
    attacker_level = get_scout_tech_level(attacker)
    defender_level = get_scout_tech_level(defender)

    base_rate = PVPConstants.SCOUT_BASE_SUCCESS_RATE
    rate_modifier = (attacker_level - defender_level) * PVPConstants.SCOUT_TECH_RATE_PER_LEVEL

    final_rate = base_rate + rate_modifier
    return max(
        PVPConstants.SCOUT_MIN_SUCCESS_RATE,
        min(PVPConstants.SCOUT_MAX_SUCCESS_RATE, final_rate)
    )


def calculate_scout_travel_time(attacker: Manor, defender: Manor) -> int:
    """
    计算侦察所需时间（秒）。

    公式：侦察时间 = 距离 × 2 + 60
    """
    distance = calculate_distance(attacker, defender)
    raw = int(
        distance * PVPConstants.SCOUT_TRAVEL_TIME_PER_DISTANCE
        + PVPConstants.SCOUT_BASE_TRAVEL_TIME
    )
    return scale_duration(raw, minimum=1)


def check_scout_cooldown(attacker: Manor, defender: Manor) -> Tuple[bool, Optional[int]]:
    """
    检查对同一目标的侦察冷却。

    Returns:
        (是否在冷却中, 剩余冷却秒数)
    """
    now = timezone.now()
    cooldown = ScoutCooldown.objects.filter(
        attacker=attacker,
        defender=defender,
        cooldown_until__gt=now
    ).first()

    if cooldown:
        remaining = int((cooldown.cooldown_until - now).total_seconds())
        return True, remaining

    return False, None


def get_scout_count(manor: Manor) -> int:
    """获取庄园的探子数量"""
    try:
        troop = PlayerTroop.objects.select_related("troop_template").get(
            manor=manor,
            troop_template__key=PVPConstants.SCOUT_TROOP_KEY
        )
        return troop.count
    except PlayerTroop.DoesNotExist:
        return 0


def start_scout(attacker: Manor, defender: Manor) -> ScoutRecord:
    """
    发起侦察。

    Args:
        attacker: 进攻方庄园
        defender: 防守方庄园

    Returns:
        侦察记录

    Raises:
        ValueError: 无法发起侦察时
    """
    # 检查是否可以攻击目标
    can_attack, reason = can_attack_target(attacker, defender)
    if not can_attack:
        raise ValueError(reason)

    # 检查冷却
    in_cooldown, remaining = check_scout_cooldown(attacker, defender)
    if in_cooldown:
        minutes = remaining // 60
        seconds = remaining % 60
        raise ValueError(f"侦察冷却中，剩余 {minutes}分{seconds}秒")

    # 检查探子数量
    scout_count = get_scout_count(attacker)
    if scout_count < 1:
        raise ValueError("探子不足，无法发起侦察")

    # 计算成功率和时间
    success_rate = calculate_scout_success_rate(attacker, defender)
    travel_time = calculate_scout_travel_time(attacker, defender)

    with transaction.atomic():
        # 扣除探子
        troop = PlayerTroop.objects.select_for_update().get(
            manor=attacker,
            troop_template__key=PVPConstants.SCOUT_TROOP_KEY
        )
        if troop.count < 1:
            raise ValueError("探子不足，无法发起侦察")
        troop.count -= 1
        troop.save(update_fields=["count"])

        # 创建侦察记录
        now = timezone.now()
        complete_at = now + timedelta(seconds=travel_time)

        record = ScoutRecord.objects.create(
            attacker=attacker,
            defender=defender,
            status=ScoutRecord.Status.SCOUTING,
            scout_cost=1,
            success_rate=success_rate,
            travel_time=travel_time,
            complete_at=complete_at,
        )

    # 调度侦察完成任务
    try:
        from gameplay.tasks import complete_scout_task
    except Exception as exc:
        logger.warning(
            "complete_scout_task dispatch failed: record_id=%s attacker=%s defender=%s error=%s",
            record.id,
            attacker.id,
            defender.id,
            exc,
            exc_info=True,
        )
    else:
        safe_apply_async(
            complete_scout_task,
            args=[record.id],
            countdown=travel_time,
            logger=logger,
            log_message="complete_scout_task dispatch failed",
        )

    return record


def finalize_scout(record: ScoutRecord, now=None) -> None:
    """
    侦察到达目标，判定成功/失败并进入返程阶段。

    流程：
    1. 去程到达 → 判定成功/失败
    2. 如果失败 → 立即给防守方发送警告消息
    3. 设置状态为 RETURNING，计算 return_at
    4. 返程完成后才给进攻方发送结果消息（通过 finalize_scout_return）

    Args:
        record: 侦察记录
        now: 当前时间（可选）
    """
    now = now or timezone.now()

    with transaction.atomic():
        locked_record = ScoutRecord.objects.select_for_update().select_related(
            "attacker", "defender"
        ).filter(pk=record.pk).first()

        if not locked_record or locked_record.status != ScoutRecord.Status.SCOUTING:
            return

        # 判定成功/失败
        is_success = random.random() < locked_record.success_rate
        locked_record.is_success = is_success

        if is_success:
            # 收集情报（成功时）
            locked_record.intel_data = _gather_scout_intel(locked_record.defender)
        else:
            # 失败时：立即给防守方发送警告消息（探子被发现）
            _send_scout_detected_message(locked_record)

        # 进入返程阶段
        locked_record.status = ScoutRecord.Status.RETURNING
        locked_record.return_at = now + timedelta(seconds=locked_record.travel_time)
        locked_record.save(update_fields=["status", "is_success", "intel_data", "return_at"])

        # 设置冷却
        cooldown_until = now + timedelta(minutes=PVPConstants.SCOUT_COOLDOWN_MINUTES)
        ScoutCooldown.objects.update_or_create(
            attacker=locked_record.attacker,
            defender=locked_record.defender,
            defaults={"cooldown_until": cooldown_until}
        )

    # 调度返程完成任务
    try:
        from gameplay.tasks import complete_scout_return_task
    except Exception as exc:
        logger.warning(
            "complete_scout_return_task dispatch failed: record_id=%s error=%s",
            locked_record.id,
            exc,
            exc_info=True,
        )
    else:
        safe_apply_async(
            complete_scout_return_task,
            args=[locked_record.id],
            countdown=locked_record.travel_time,
            logger=logger,
            log_message="complete_scout_return_task dispatch failed",
        )


def finalize_scout_return(record: ScoutRecord, now=None) -> None:
    """
    侦察返程完成，发送结果消息给进攻方。

    Args:
        record: 侦察记录
        now: 当前时间（可选）
    """
    now = now or timezone.now()

    with transaction.atomic():
        locked_record = ScoutRecord.objects.select_for_update().select_related(
            "attacker", "defender"
        ).filter(pk=record.pk).first()

        if not locked_record or locked_record.status != ScoutRecord.Status.RETURNING:
            return

        # 根据 is_success 设置最终状态并发送消息
        if locked_record.is_success:
            locked_record.status = ScoutRecord.Status.SUCCESS
            # 归还探子（成功时探子安全返回）
            try:
                troop = PlayerTroop.objects.select_for_update().get(
                    manor=locked_record.attacker,
                    troop_template__key=PVPConstants.SCOUT_TROOP_KEY
                )
                troop.count += locked_record.scout_cost
                troop.save(update_fields=["count"])
            except PlayerTroop.DoesNotExist:
                pass
            # 发送成功消息给进攻方
            _send_scout_success_message(locked_record)
        else:
            locked_record.status = ScoutRecord.Status.FAILED
            # 发送失败消息给进攻方（探子损失，不归还）
            _send_scout_fail_message(locked_record)

        locked_record.completed_at = now
        locked_record.save(update_fields=["status", "completed_at"])


def _gather_scout_intel(defender: Manor) -> Dict[str, Any]:
    """收集目标庄园的情报"""
    # 护院数量（模糊）
    total_troops = PlayerTroop.objects.filter(manor=defender).aggregate(
        total=models.Sum("count")
    )["total"] or 0

    # 门客数量和平均等级
    guests = defender.guests.all()
    guest_count = guests.count()
    avg_guest_level = 0
    if guest_count > 0:
        total_level = sum(g.level for g in guests)
        avg_guest_level = round(total_level / guest_count)

    # 资产等级
    asset_level, _ = get_asset_level(defender)

    return {
        "troop_description": get_troop_description(total_troops),
        "guest_count": guest_count,
        "avg_guest_level": avg_guest_level,
        "asset_level": asset_level,
        "scouted_at": timezone.now().isoformat(),
    }


def _send_scout_success_message(record: ScoutRecord) -> None:
    """发送侦察成功消息"""
    intel = record.intel_data or {}
    body = f"""探子已成功潜入 {record.defender.display_name}，获取到以下情报：

【护院情况】{intel.get('troop_description', '未知')}
【门客数量】{intel.get('guest_count', 0)} 人
【门客等级】平均 {intel.get('avg_guest_level', 0)} 级
【资产状况】{intel.get('asset_level', '未知')}"""

    create_message(
        manor=record.attacker,
        kind="system",
        title=f"侦察报告 - {record.defender.display_name}",
        body=body,
    )


def _send_scout_fail_message(record: ScoutRecord) -> None:
    """发送侦察失败消息"""
    body = f"""派往 {record.defender.display_name} 的探子被对方发现，侦察任务失败。
探子已损失。"""

    create_message(
        manor=record.attacker,
        kind="system",
        title="侦察失败",
        body=body,
    )


def _send_scout_detected_message(record: ScoutRecord) -> None:
    """发送被侦察警告消息给防守方"""
    body = f"""我方巡逻队在庄园附近发现并抓获了一名探子！

探子来源：{record.attacker.display_name}
所在地区：{record.attacker.location_display}
发现时间：{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}

建议加强防备，敌人可能即将来袭！"""

    create_message(
        manor=record.defender,
        kind="system",
        title="发现敌方探子！",
        body=body,
    )


def refresh_scout_records(manor: Manor, *, prefer_async: bool = False) -> None:
    """刷新庄园的侦察记录状态（支持异步优先结算）。"""
    now = timezone.now()
    scouting_ids, returning_ids = _collect_due_scout_record_ids(manor, now)

    if not scouting_ids and not returning_ids:
        return

    if prefer_async:
        scouting_ids, returning_ids, done_async = _dispatch_async_scout_refresh(scouting_ids, returning_ids)
        if done_async:
            return

    _finalize_due_scout_records(now, scouting_ids, returning_ids)


def get_active_scouts(manor: Manor) -> List[ScoutRecord]:
    """获取进行中的侦察列表（包括去程和返程）"""
    return list(
        ScoutRecord.objects.filter(
            attacker=manor,
            status__in=[ScoutRecord.Status.SCOUTING, ScoutRecord.Status.RETURNING]
        ).select_related("defender").order_by("-started_at")
    )


def get_scout_history(manor: Manor, limit: int = 20) -> List[ScoutRecord]:
    """获取侦察历史记录"""
    return list(
        ScoutRecord.objects.filter(
            attacker=manor
        ).select_related("defender").order_by("-started_at")[:limit]
    )


def can_scout_retreat(record: ScoutRecord) -> bool:
    """判断侦察是否可以撤退（仅在去程阶段可撤退）"""
    return record.status == ScoutRecord.Status.SCOUTING


def request_scout_retreat(record: ScoutRecord) -> None:
    """
    请求侦察撤退（仅在去程阶段可用）。

    撤退后探子立即返程，不消耗探子（撤退时归还）。

    Args:
        record: 侦察记录

    Raises:
        ValueError: 无法撤退时
    """
    if record.status != ScoutRecord.Status.SCOUTING:
        raise ValueError("当前状态无法撤退")

    now = timezone.now()
    elapsed = max(0, int((now - record.started_at).total_seconds()))

    with transaction.atomic():
        locked_record = ScoutRecord.objects.select_for_update().select_related(
            "attacker"
        ).filter(pk=record.pk).first()

        if not locked_record or locked_record.status != ScoutRecord.Status.SCOUTING:
            raise ValueError("当前状态无法撤退")

        # 设置为失败状态（撤退视为失败，但不扣探子）
        locked_record.status = ScoutRecord.Status.RETURNING
        locked_record.is_success = False
        locked_record.return_at = now + timedelta(seconds=max(1, elapsed))
        locked_record.save(update_fields=["status", "is_success", "return_at"])

        # 归还探子（撤退不消耗探子）
        try:
            troop = PlayerTroop.objects.select_for_update().get(
                manor=locked_record.attacker,
                troop_template__key=PVPConstants.SCOUT_TROOP_KEY
            )
            troop.count += locked_record.scout_cost
            troop.save(update_fields=["count"])
        except PlayerTroop.DoesNotExist:
            pass

    # 调度撤退返程完成任务
    try:
        from gameplay.tasks import complete_scout_return_task
    except Exception as exc:
        logger.warning(
            "complete_scout_return_task dispatch failed for retreat: record_id=%s error=%s",
            locked_record.id,
            exc,
            exc_info=True,
        )
    else:
        countdown = max(1, elapsed)
        safe_apply_async(
            complete_scout_return_task,
            args=[locked_record.id],
            countdown=countdown,
            logger=logger,
            log_message="complete_scout_return_task dispatch failed for retreat",
        )
