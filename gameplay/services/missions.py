"""
任务管理服务
"""

from __future__ import annotations

import logging
import os
import random
from datetime import timedelta
from typing import Dict, List

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.utils.celery import safe_apply_async

from ..models import InventoryItem, ItemTemplate, Manor, MissionRun, MissionTemplate, ResourceEvent, ResourceType
from .messages import create_message
from .notifications import notify_user
from .resources import grant_resources
from .troops import apply_defender_troop_losses
from core.utils.time_scale import scale_duration

# 延迟导入battle模块避免循环依赖
# validate_troop_capacity 在 launch_mission 中调用时导入

logger = logging.getLogger(__name__)


def normalize_mission_loadout(raw: Dict[str, int] | None) -> Dict[str, int]:
    """
    规范化任务出征的兵种配置。

    Args:
        raw: 原始兵种配置字典

    Returns:
        规范化后的兵种配置
    """
    from battle.troops import load_troop_templates

    from ..utils.resource_calculator import normalize_mission_loadout as normalize_loadout_util

    templates = load_troop_templates()
    if not templates:
        return {}

    loadout = normalize_loadout_util(raw, templates)
    # 不再自动填充默认兵力，允许不带兵出征
    return loadout


def _travel_time_seconds(base_time: int, guests, troop_loadout: Dict[str, int]) -> int:
    """
    计算任务的旅行时间。

    Args:
        base_time: 基础旅行时间
        guests: 门客列表
        troop_loadout: 兵种配置

    Returns:
        实际旅行时间（秒）
    """
    from battle.troops import load_troop_templates

    from ..utils.resource_calculator import calculate_travel_time

    templates = load_troop_templates()
    travel_seconds = calculate_travel_time(base_time, guests, troop_loadout, templates)
    return scale_duration(travel_seconds, minimum=1)


def refresh_mission_runs(manor: Manor) -> None:
    """
    刷新庄园的任务状态，释放完成任务的门客并发放奖励/战报。

    Args:
        manor: 庄园对象
    """
    now = timezone.now()
    active_runs = list(
        manor.mission_runs.select_related("mission")
        .prefetch_related("guests")
        .filter(status=MissionRun.Status.ACTIVE, return_at__isnull=False, return_at__lte=now)
    )
    if not active_runs:
        return

    for run in active_runs:
        finalize_mission_run(run, now=now)


def finalize_mission_run(run: MissionRun, now=None) -> None:
    """
    完成任务后释放门客、发放奖励、发送消息（幂等）。

    Args:
        run: 任务执行对象
        now: 当前时间（可选）
    """
    now = now or timezone.now()

    from guests.models import Guest, GuestStatus

    with transaction.atomic():
        locked_run = (
            MissionRun.objects.select_for_update()
            .select_related("mission", "manor", "battle_report")
            .prefetch_related("guests")
            .filter(pk=run.pk)
            .first()
        )
        if not locked_run or locked_run.status == MissionRun.Status.COMPLETED:
            return

        report = locked_run.battle_report
        player_side = "defender" if locked_run.mission.is_defense else "attacker"
        if not report and (not locked_run.is_retreating) and locked_run.mission.is_defense:
            from ..models import PlayerTroop

            defender_guests = list(
                locked_run.manor.guests.select_for_update()
                .filter(status=GuestStatus.IDLE)
                .select_related("template")
                .prefetch_related("skills")
                .order_by("-template__rarity", "-level", "id")
            )
            defender_loadout = {
                troop.troop_template.key: troop.count
                for troop in (
                    PlayerTroop.objects.select_for_update()
                    .filter(manor=locked_run.manor, count__gt=0)
                    .select_related("troop_template")
                )
            }
            report = _generate_sync_battle_report(
                manor=locked_run.manor,
                mission=locked_run.mission,
                guests=defender_guests,
                loadout=defender_loadout,
                defender_setup={},
                travel_seconds=0,
                seed=locked_run.id,
            )
            locked_run.battle_report = report
            locked_run.save(update_fields=["battle_report"])
        hp_updates: Dict[int, int] = {}
        defeated_guest_ids: set[int] = set()
        participant_ids: set[int] = set()
        if report:
            loss_updates = ((report.losses or {}).get(player_side) or {}).get("hp_updates") or {}
            for gid, hp in loss_updates.items():
                try:
                    gid_int = int(gid)
                    hp_int = int(hp)
                except (TypeError, ValueError):
                    continue
                hp_updates[gid_int] = hp_int
            team_entries = report.defender_team if player_side == "defender" else report.attacker_team
            for entry in team_entries or []:
                gid = entry.get("guest_id")
                remaining = entry.get("remaining_hp")
                try:
                    gid_int = int(gid)
                    remaining_int = int(remaining)
                except (TypeError, ValueError):
                    continue
                participant_ids.add(gid_int)
                hp_updates.setdefault(gid_int, remaining_int)
                if remaining_int <= 0:
                    defeated_guest_ids.add(gid_int)

        if locked_run.is_retreating:
            guests = list(locked_run.guests.select_for_update())
        elif report and participant_ids:
            guests = list(
                locked_run.manor.guests.select_for_update()
                .filter(id__in=participant_ids)
            )
        else:
            guests = list(locked_run.guests.select_for_update())
        # 批量更新门客状态
        guests_to_update = []
        for guest in guests:
            # 撤退不会进入战斗：仅释放门客，不应用战斗结果
            if locked_run.is_retreating:
                guest.status = GuestStatus.IDLE
            else:
                guest.status = GuestStatus.INJURED if guest.id in defeated_guest_ids else GuestStatus.IDLE
                target_hp = hp_updates.get(guest.id)
                if target_hp is not None:
                    guest.current_hp = max(1, min(guest.max_hp, target_hp))
                    guest.last_hp_recovery_at = now
            guests_to_update.append(guest)

        if guests_to_update:
            # 根据是否撤退决定更新字段
            if locked_run.is_retreating:
                Guest.objects.bulk_update(guests_to_update, ["status"])
            else:
                Guest.objects.bulk_update(guests_to_update, ["status", "current_hp", "last_hp_recovery_at"])

        locked_run.status = MissionRun.Status.COMPLETED
        locked_run.completed_at = now
        locked_run.save(update_fields=['status', 'completed_at'])

        # 防守任务：扣除玩家方护院损失
        if report and locked_run.mission.is_defense and not locked_run.is_retreating:
            apply_defender_troop_losses(locked_run.manor, report)

        # 进攻任务：归还存活的护院（必须在report检查外，处理无战报情况）
        if not locked_run.mission.is_defense:
            from .troops import _return_surviving_troops_batch
            loadout = locked_run.troop_loadout or {}
            if loadout:
                if locked_run.is_retreating:
                    # 安全修复：撤退时检查是否已经开始战斗
                    # 如果有战报，说明战斗已发生，应按战报归还（可能有损失）
                    if report:
                        logger.warning(
                            f"撤退但存在战报，按战报归还护院: run_id={locked_run.id}",
                            extra={"run_id": locked_run.id, "manor_id": locked_run.manor.id}
                        )
                        _return_surviving_troops_batch(locked_run.manor, loadout, report)
                    else:
                        # 无战报的撤退：全额归还
                        _return_surviving_troops_batch(locked_run.manor, loadout)
                elif not report:
                    # 非撤退但无战报（异常情况）：记录警告并全额归还
                    logger.warning(
                        f"任务完成但无战报，全额归还护院: run_id={locked_run.id}",
                        extra={"run_id": locked_run.id, "manor_id": locked_run.manor.id}
                    )
                    _return_surviving_troops_batch(locked_run.manor, loadout)
                else:
                    # 按战报归还存活的护院
                    _return_surviving_troops_batch(locked_run.manor, loadout, report)

        # 计算玩家是否获胜（需要report存在）
        player_won = False
        if report:
            player_won = (not locked_run.is_retreating) and report.winner == player_side

        if report and player_won:
            drops = dict(report.drops or {})
            if locked_run.mission.is_defense and not drops:
                from common.utils.loot import resolve_drop_rewards
                seed = getattr(report, "seed", None)
                rng = random.Random(seed) if seed is not None else random.Random()
                drops = resolve_drop_rewards(locked_run.mission.drop_table or {}, rng)

            # 胜利方战斗回收：经验果 + 护院装备回收（参考踢馆设定）
            try:
                from .battle_salvage import calculate_battle_salvage
                exp_fruit_count, equipment_recovery = calculate_battle_salvage(report)
                # 把回收奖励合并到战报掉落中，统一发放
                if exp_fruit_count > 0:
                    drops["experience_fruit"] = drops.get("experience_fruit", 0) + exp_fruit_count
                for equip_key, count in equipment_recovery.items():
                    drops[equip_key] = drops.get(equip_key, 0) + count
            except Exception:
                logger.warning("Failed to calculate mission battle salvage rewards", exc_info=True)

            # 更新战报掉落并发放奖励
            if drops:
                report.drops = drops
                report.save(update_fields=["drops"])
                award_mission_drops(locked_run.manor, drops, locked_run.mission.name)

        if report and not locked_run.is_retreating:
            create_message(
                manor=locked_run.manor,
                kind='battle',
                title=f"{locked_run.mission.name} 战报",
                body='',
                battle_report=report,
            )

            # 只有当report存在时才发送WebSocket通知
            if report:
                notify_user(
                    locked_run.manor.user_id,
                    {
                        'kind': 'battle',
                        'title': f"{locked_run.mission.name} 战报",
                        'report_id': report.id,
                        'mission_key': locked_run.mission.key,
                        'mission_name': locked_run.mission.name,
                    },
                    log_context="mission battle notification",
                )


def _get_today_date_range():
    """
    获取今日的时间范围（按服务器时区）。

    Returns:
        tuple: (start_of_day, end_of_day, today_date)
    """
    now = timezone.now()
    tz = timezone.get_current_timezone()
    start_of_day = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    today_date = start_of_day.date()
    return start_of_day, end_of_day, today_date


def get_mission_extra_attempts(manor: Manor, mission: MissionTemplate) -> int:
    """
    获取今日该任务通过任务卡获得的额外次数。

    Args:
        manor: 庄园对象
        mission: 任务模板对象

    Returns:
        今日额外次数
    """
    from ..models import MissionExtraAttempt

    _, _, today_date = _get_today_date_range()
    extra = MissionExtraAttempt.objects.filter(
        manor=manor, mission=mission, date=today_date
    ).first()
    return extra.extra_count if extra else 0


def bulk_get_mission_extra_attempts(manor: Manor, missions: List[MissionTemplate]) -> Dict[str, int]:
    """
    批量获取今日各任务通过任务卡获得的额外次数。

    Args:
        manor: 庄园对象
        missions: 任务模板列表

    Returns:
        字典 {mission_key: 额外次数}
    """
    from ..models import MissionExtraAttempt

    _, _, today_date = _get_today_date_range()
    extras = MissionExtraAttempt.objects.filter(
        manor=manor, date=today_date, mission__in=missions
    ).select_related("mission")

    result = {m.key: 0 for m in missions}
    for extra in extras:
        result[extra.mission.key] = extra.extra_count
    return result


def add_mission_extra_attempt(manor: Manor, mission: MissionTemplate, count: int = 1) -> int:
    """
    为任务增加额外次数（使用任务卡时调用）。

    Args:
        manor: 庄园对象
        mission: 任务模板对象
        count: 增加的次数

    Returns:
        增加后的总额外次数
    """
    from django.db import IntegrityError

    from ..models import MissionExtraAttempt

    _, _, today_date = _get_today_date_range()
    with transaction.atomic():
        # 尝试获取现有记录并加锁
        extra = (
            MissionExtraAttempt.objects
            .select_for_update()
            .filter(manor=manor, mission=mission, date=today_date)
            .first()
        )
        if extra:
            extra.extra_count += count
            extra.save(update_fields=["extra_count", "updated_at"])
            return extra.extra_count

    # 不存在则尝试创建（在事务外处理并发创建冲突）
    try:
        with transaction.atomic():
            extra = MissionExtraAttempt.objects.create(
                manor=manor, mission=mission, date=today_date, extra_count=count
            )
            return extra.extra_count
    except IntegrityError:
        # 并发创建冲突，重新获取并更新
        with transaction.atomic():
            extra = (
                MissionExtraAttempt.objects
                .select_for_update()
                .get(manor=manor, mission=mission, date=today_date)
            )
            extra.extra_count += count
            extra.save(update_fields=["extra_count", "updated_at"])
            return extra.extra_count


def get_mission_daily_limit(manor: Manor, mission: MissionTemplate) -> int:
    """
    获取任务今日的有效次数上限（基础 + 额外）。

    Args:
        manor: 庄园对象
        mission: 任务模板对象

    Returns:
        今日有效次数上限
    """
    extra = get_mission_extra_attempts(manor, mission)
    return mission.daily_limit + extra


def mission_attempts_today(manor: Manor, mission: MissionTemplate) -> int:
    """
    查询今日该任务的挑战次数。

    Args:
        manor: 庄园对象
        mission: 任务模板对象

    Returns:
        今日挑战次数
    """
    start_of_day, end_of_day, _ = _get_today_date_range()
    return manor.mission_runs.filter(mission=mission, started_at__gte=start_of_day, started_at__lt=end_of_day).count()


def bulk_mission_attempts_today(manor: Manor, missions: List[MissionTemplate]) -> Dict[str, int]:
    """
    批量查询今日各任务的挑战次数（优化 N+1 查询）。

    Args:
        manor: 庄园对象
        missions: 任务模板列表

    Returns:
        字典 {mission_key: 今日挑战次数}
    """
    from django.db.models import Count

    start_of_day, end_of_day, _ = _get_today_date_range()

    # 单次查询获取所有任务的今日挑战次数
    counts = (
        manor.mission_runs
        .filter(started_at__gte=start_of_day, started_at__lt=end_of_day)
        .values('mission__key')
        .annotate(count=Count('id'))
    )

    # 转换为字典，默认值为 0
    result = {m.key: 0 for m in missions}
    for row in counts:
        key = row['mission__key']
        if key in result:
            result[key] = row['count']

    return result


def award_mission_drops(manor: Manor, drops: Dict[str, int], note: str) -> None:
    """
    发放任务掉落奖励（资源和物品）。

    Args:
        manor: 庄园对象
        drops: 掉落字典 {key: amount}
        note: 奖励说明
    """
    if not drops:
        return
    resource_keys = set(ResourceType.values)
    resources = {k: v for k, v in drops.items() if k in resource_keys}
    item_keys = {k: v for k, v in drops.items() if k not in resource_keys}
    if resources:
        grant_resources(manor, resources, note, ResourceEvent.Reason.BATTLE_REWARD)
    if item_keys:
        from guests.models import SkillBook

        templates = {it.key: it for it in ItemTemplate.objects.filter(key__in=item_keys.keys())}
        missing_keys = set(item_keys.keys()) - set(templates.keys())
        if missing_keys:
            # 尝试将技能书回填到 ItemTemplate
            books = {book.key: book for book in SkillBook.objects.filter(key__in=missing_keys)}
            for key in list(missing_keys):
                book = books.get(key)
                if not book:
                    continue
                tmpl, _ = ItemTemplate.objects.get_or_create(
                    key=key,
                    defaults={
                        "name": book.name,
                        "description": book.description,
                        "effect_type": ItemTemplate.EffectType.SKILL_BOOK,
                        "effect_payload": {"skill_key": book.skill.key, "skill_name": book.skill.name},
                    },
                )
                templates[key] = tmpl
        # 没有模板的掉落键会被忽略，确保在 item_templates.yaml 中定义
        # 性能优化：预加载现有库存物品，减少 N 次 get_or_create 查询
        template_ids = [templates[key].id for key in item_keys.keys() if key in templates]
        existing_items = {
            item.template_id: item
            for item in InventoryItem.objects.filter(
                manor=manor,
                template_id__in=template_ids,
                storage_location=InventoryItem.StorageLocation.WAREHOUSE,
            )
        }

        to_update: List[InventoryItem] = []
        to_create: List[InventoryItem] = []
        for key, amount in item_keys.items():
            template = templates.get(key)
            if not template:
                continue
            existing_item = existing_items.get(template.id)
            if existing_item:
                existing_item.quantity += amount
                to_update.append(existing_item)
            else:
                new_item = InventoryItem(
                    manor=manor,
                    template=template,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                    quantity=amount,
                )
                to_create.append(new_item)

        # 批量创建新物品（1次查询）
        if to_create:
            InventoryItem.objects.bulk_create(to_create)

        # 批量更新现有物品（1次查询）
        if to_update:
            InventoryItem.objects.bulk_update(to_update, ["quantity"])


def launch_mission(
    manor: Manor, mission: MissionTemplate, guest_ids: List[int], troop_loadout: Dict[str, int], seed=None
):
    """
    发起任务执行。

    Args:
        manor: 庄园对象
        mission: 任务模板对象
        guest_ids: 出征门客ID列表
        troop_loadout: 兵种配置
        seed: 随机数种子（可选）

    Returns:
        任务执行对象

    Raises:
        ValueError: 参数不合法时抛出
    """
    refresh_mission_runs(manor)
    attempts = mission_attempts_today(manor, mission)
    daily_limit = get_mission_daily_limit(manor, mission)
    if attempts >= daily_limit:
        raise ValueError("今日该任务次数已耗尽")
    from guests.models import Guest, GuestStatus

    # Lock guests, validate status, update to DEPLOYED, and create mission run
    # All in one atomic block to prevent crash-induced stuck states
    run = None
    with transaction.atomic():
        if mission.is_defense:
            # 防守任务不锁定门客，战斗时以到达时刻的状态为准
            guests = []
            loadout = {}
            travel_seconds = scale_duration(mission.base_travel_time, minimum=1)
        else:
            # Lock guests before validating status to prevent concurrent assignment
            guests = list(
                manor.guests.select_for_update()
                .filter(id__in=guest_ids)
                .select_related("template")
                .prefetch_related("skills")
            )

            # Validate that all requested guests exist and are IDLE
            if len(guests) != len(set(guest_ids)):
                raise ValueError("部分门客不可用或已离开庄园")
            if any(guest.status != GuestStatus.IDLE for guest in guests):
                raise ValueError("部分门客不可用或已离开庄园")
            if not guests:
                raise ValueError("请选择至少一名门客")

            # Calculate loadout and travel time
            if mission.guest_only:
                loadout = {}
            else:
                loadout = normalize_mission_loadout(troop_loadout)

                # 验证兵力是否超过门客带兵上限
                from battle.services import validate_troop_capacity
                validate_troop_capacity(guests, loadout)

            # 进攻任务：扣除护院（防守任务不扣除，战斗结算时扣除）
            if not mission.is_defense and loadout:
                from .troops import _deduct_troops_batch
                _deduct_troops_batch(manor, loadout)

            travel_seconds = _travel_time_seconds(mission.base_travel_time, guests, loadout)

        # Update guest status（防守任务不锁定门客）
        if not mission.is_defense and guests:
            for guest in guests:
                guest.status = GuestStatus.DEPLOYED
            Guest.objects.bulk_update(guests, ["status"])

        # Create mission run and assign guests (same transaction as status update)
        run = MissionRun.objects.create(
            manor=manor,
            mission=mission,
            troop_loadout=loadout,
            travel_time=travel_seconds,
            return_at=timezone.now()
            + timedelta(seconds=travel_seconds if mission.is_defense else travel_seconds * 2),
        )
        if not mission.is_defense:
            run.guests.set(guests)

    # Guest locks released - now perform expensive operations without holding locks
    try:
        # 延迟导入避免循环依赖
        from battle.tasks import generate_report_task
        from gameplay.tasks import complete_mission_task

        if mission.is_defense:
            defender_setup = {"troop_loadout": loadout}
            drop_table = {}
        else:
            defender_setup = {
                "guest_keys": mission.enemy_guests or [],
                "troop_loadout": mission.enemy_troops or {},
                "technology": mission.enemy_technology or {},
            }
            drop_table = mission.drop_table or {}

        def _sync_report():
            return _generate_sync_battle_report(
                manor=manor,
                mission=mission,
                guests=guests,
                loadout=loadout,
                defender_setup=defender_setup,
                travel_seconds=travel_seconds,
                seed=seed,
            )

        report = None
        if not mission.is_defense:
            force_sync = bool(
                getattr(settings, "DEBUG", False)
                or os.environ.get("PYTEST_CURRENT_TEST")
            )
            if force_sync:
                # 测试/开发环境直接同步生成，避免异步与同步重复写入
                report = _sync_report()
            else:
                ok = safe_apply_async(
                    generate_report_task,
                    kwargs={
                        "manor_id": manor.id,
                        "mission_id": mission.id,
                        "run_id": run.id,
                        "guest_ids": [g.id for g in guests],
                        "troop_loadout": loadout,
                        "fill_default_troops": False,
                        "battle_type": mission.battle_type or "task",
                        "opponent_name": mission.name,
                        "defender_setup": defender_setup,
                        "drop_table": drop_table,
                        "travel_seconds": travel_seconds,
                        "seed": seed,
                    },
                    logger=logger,
                    log_message="generate_report_task dispatch failed; falling back to sync generation",
                )
                if not ok:
                    report = _sync_report()

        if report:
            updated = MissionRun.objects.filter(pk=run.pk, battle_report__isnull=True).update(
                battle_report=report
            )
            if updated:
                run.battle_report = report

        # 调度任务完成回调
        countdown = max(0, int((run.return_at - timezone.now()).total_seconds()))
        safe_apply_async(
            complete_mission_task,
            args=[run.id],
            countdown=countdown,
            logger=logger,
            log_message="complete_mission_task dispatch failed; relying on refresh_mission_runs",
        )

        # Best-effort: 异步任务启动失败不删除 run，保留用于审计
        # 事务已提交，资源已扣除，此时删除 run 会导致资源永久丢失
        # 任务失败由 complete_mission 处理（标记 failed），不影响资源
        return run
    except ValueError as exc:
        # 业务逻辑错误（如门客状态、资源不足等）- 事务未提交，无资源损失
        logger.warning(
            "launch_mission validation failed: %s",
            exc,
            extra={"manor_id": manor.id, "mission_id": mission.id},
        )
        raise
    except Exception:
        # 未预期的异常 - 事务未提交，无资源损失
        logger.exception(
            "launch_mission unexpected error",
            extra={"manor_id": manor.id, "mission_id": mission.id},
        )
        raise


def schedule_mission_completion(run: MissionRun) -> None:
    """
    调度任务完成的后台任务。

    Args:
        run: 任务执行对象
    """
    from gameplay.tasks import complete_mission_task

    if not run.return_at:
        return
    countdown = max(0, int((run.return_at - timezone.now()).total_seconds()))
    safe_apply_async(
        complete_mission_task,
        args=[run.id],
        countdown=countdown,
        logger=logger,
        log_message="complete_mission_task dispatch failed; relying on refresh_mission_runs",
    )


def _generate_sync_battle_report(
    manor: Manor,
    mission: MissionTemplate,
    guests,
    loadout: Dict[str, int],
    defender_setup: Dict[str, object],
    travel_seconds: int,
    seed=None,
):
    """
    同步生成战报的辅助函数（当 Celery 不可用或测试需要即时结果时使用）。

    Args:
        manor: 庄园对象
        mission: 任务模板对象
        guests: 门客列表
        loadout: 兵种配置
        defender_setup: 防守方配置
        travel_seconds: 旅行时间
        seed: 随机数种子

    Returns:
        战报对象
    """
    from battle.services import simulate_report

    if mission.is_defense:
        from battle.combatants import build_named_ai_guests
        from gameplay.services.technology import resolve_enemy_tech_levels, get_guest_stat_bonuses

        tech_conf = mission.enemy_technology or {}
        attacker_guest_level = int(tech_conf.get("guest_level", 50)) if tech_conf else 50
        attacker_guests = build_named_ai_guests(mission.enemy_guests or [], level=attacker_guest_level)
        attacker_tech_levels = resolve_enemy_tech_levels(tech_conf) if tech_conf else {}
        attacker_guest_bonuses = get_guest_stat_bonuses(tech_conf) if tech_conf else {}
        attacker_guest_skills = tech_conf.get("guest_skills") or None

        return simulate_report(
            manor=manor,
            battle_type=mission.battle_type or "task",
            seed=seed,
            troop_loadout=mission.enemy_troops or {},
            fill_default_troops=False,
            attacker_guests=attacker_guests,
            defender_setup={"troop_loadout": loadout},
            defender_guests=guests,
            defender_max_squad=len(guests) if guests else None,
            drop_table={},
            opponent_name=mission.name,
            travel_seconds=travel_seconds,
            send_message=False,
            auto_reward=False,
            drop_handler=None,
            max_squad=len(attacker_guests) if attacker_guests else None,
            apply_damage=False,
            use_lock=False,  # 任务系统已自行管理门客状态，无需重复加锁
            attacker_tech_levels=attacker_tech_levels,
            attacker_guest_bonuses=attacker_guest_bonuses or None,
            attacker_guest_skills=attacker_guest_skills,
            attacker_manor=None,
        )

    return simulate_report(
        manor=manor,
        battle_type=mission.battle_type or "task",
        seed=seed,
        troop_loadout=loadout,
        fill_default_troops=False,
        attacker_guests=guests,
        defender_setup=defender_setup,
        drop_table=mission.drop_table or {},
        opponent_name=mission.name,
        travel_seconds=travel_seconds,
        send_message=False,
        auto_reward=False,
        drop_handler=None,
        max_squad=getattr(manor, "max_squad_size", None),
        apply_damage=False,
        use_lock=False,  # 任务系统已自行管理门客状态，无需重复加锁
    )


def request_retreat(run: MissionRun) -> None:
    """
    请求任务撤退（仅在出征途中可用）。

    Args:
        run: 任务执行对象

    Raises:
        ValueError: 任务状态不允许撤退时抛出
    """
    if run.status != MissionRun.Status.ACTIVE:
        raise ValueError("任务已结束，无法撤退")
    now = timezone.now()
    outbound_finish = run.started_at + timedelta(seconds=run.travel_time)
    if now >= outbound_finish:
        raise ValueError("已进入返程，无法撤退")
    elapsed = max(0, int((now - run.started_at).total_seconds()))
    return_time = max(1, elapsed)
    run.is_retreating = True
    run.return_at = now + timedelta(seconds=return_time)
    run.save(update_fields=["is_retreating", "return_at"])
    schedule_mission_completion(run)


def can_retreat(run: MissionRun, now=None) -> bool:
    """
    判断任务是否可以撤退。

    Args:
        run: 任务执行对象
        now: 当前时间（可选）

    Returns:
        是否可以撤退
    """
    if run.status != MissionRun.Status.ACTIVE:
        return False
    if run.is_retreating:
        return False
    now = now or timezone.now()
    outbound_finish = run.started_at + timedelta(seconds=run.travel_time)
    return now < outbound_finish
