from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from gameplay.models import MissionRun
from gameplay.services.manor import finalize_building_upgrade
from gameplay.services.missions import finalize_mission_run
from gameplay.services.technology import finalize_technology_upgrade

logger = logging.getLogger(__name__)


@shared_task(name="gameplay.complete_mission", bind=True, max_retries=2, default_retry_delay=30)
def complete_mission_task(self, run_id: int):
    try:
        run = MissionRun.objects.select_related("mission", "manor").prefetch_related("guests").filter(pk=run_id).first()
        if not run:
            logger.warning(f"MissionRun {run_id} not found")
            return "not_found"
        now = timezone.now()
        # 检查任务是否已到达完成时间（与 complete_building_upgrade 保持一致）
        if run.return_at and run.return_at > now:
            remaining = int((run.return_at - now).total_seconds())
            if remaining > 0:
                complete_mission_task.apply_async(args=[run_id], countdown=remaining)
                return "rescheduled"
        finalize_mission_run(run, now=now)
        return "completed"
    except Exception as exc:
        logger.exception(f"Failed to complete mission {run_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.complete_building_upgrade", bind=True, max_retries=2, default_retry_delay=30)
def complete_building_upgrade(self, building_id: int):
    from gameplay.models import Building

    try:
        building = (
            Building.objects.select_related("manor", "manor__user", "building_type").filter(pk=building_id).first()
        )
        if not building:
            logger.warning(f"Building {building_id} not found")
            return "not_found"
        now = timezone.now()
        if building.upgrade_complete_at and building.upgrade_complete_at > now:
            remaining = int((building.upgrade_complete_at - now).total_seconds())
            if remaining > 0:
                complete_building_upgrade.apply_async(args=[building_id], countdown=remaining)
                return "rescheduled"
        finalized = finalize_building_upgrade(building, now=now, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete building upgrade {building_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_building_upgrades")
def scan_building_upgrades(limit: int = 200):
    """
    Fallback scan to complete any overdue upgrades (in case of worker downtime).
    """
    from gameplay.models import Building

    now = timezone.now()
    qs = (
        Building.objects.select_related("manor", "manor__user", "building_type")
        .filter(is_upgrading=True, upgrade_complete_at__lte=now)
        .order_by("upgrade_complete_at")[:limit]
    )
    count = 0
    for building in qs:
        try:
            if finalize_building_upgrade(building, now=now, send_notification=True):
                count += 1
        except Exception:
            logger.exception(f"Failed to finalize building {building.id}")
    return count


@shared_task(name="gameplay.complete_technology_upgrade", bind=True, max_retries=2, default_retry_delay=30)
def complete_technology_upgrade(self, tech_id: int):
    """
    完成技术升级的后台任务。
    """
    from gameplay.models import PlayerTechnology

    try:
        tech = PlayerTechnology.objects.select_related("manor", "manor__user").filter(pk=tech_id).first()
        if not tech:
            logger.warning(f"PlayerTechnology {tech_id} not found")
            return "not_found"
        now = timezone.now()
        if tech.upgrade_complete_at and tech.upgrade_complete_at > now:
            remaining = int((tech.upgrade_complete_at - now).total_seconds())
            if remaining > 0:
                complete_technology_upgrade.apply_async(args=[tech_id], countdown=remaining)
                return "rescheduled"
        finalized = finalize_technology_upgrade(tech, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete technology upgrade {tech_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_technology_upgrades")
def scan_technology_upgrades(limit: int = 200):
    """
    扫描并完成所有到期的技术升级（用于 worker 宕机恢复）。
    """
    from gameplay.models import PlayerTechnology

    now = timezone.now()
    qs = (
        PlayerTechnology.objects.select_related("manor", "manor__user")
        .filter(is_upgrading=True, upgrade_complete_at__lte=now)
        .order_by("upgrade_complete_at")[:limit]
    )
    count = 0
    for tech in qs:
        try:
            if finalize_technology_upgrade(tech, send_notification=True):
                count += 1
        except Exception:
            logger.exception(f"Failed to finalize technology {tech.id}")
    return count


@shared_task(name="gameplay.complete_work_assignments")
def complete_work_assignments_task():
    """
    定时完成到期的打工任务
    每分钟执行一次
    """
    from gameplay.services.work import complete_work_assignments
    try:
        count = complete_work_assignments()
        return f"完成 {count} 个打工任务"
    except Exception:
        logger.exception("Failed to complete work assignments")
        raise


@shared_task(name="gameplay.complete_horse_production", bind=True, max_retries=2, default_retry_delay=30)
def complete_horse_production(self, production_id: int):
    """
    完成马匹生产的后台任务。
    """
    from gameplay.models import HorseProduction
    from gameplay.services.stable import finalize_horse_production

    try:
        production = (
            HorseProduction.objects
            .select_related("manor", "manor__user")
            .filter(pk=production_id)
            .first()
        )
        if not production:
            logger.warning(f"HorseProduction {production_id} not found")
            return "not_found"

        now = timezone.now()
        if production.complete_at and production.complete_at > now:
            remaining = int((production.complete_at - now).total_seconds())
            if remaining > 0:
                complete_horse_production.apply_async(args=[production_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_horse_production(production, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete horse production {production_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_horse_productions")
def scan_horse_productions(limit: int = 200):
    """
    扫描并完成所有到期的马匹生产（用于 worker 宕机恢复）。
    """
    from gameplay.models import HorseProduction
    from gameplay.services.stable import finalize_horse_production

    now = timezone.now()
    qs = (
        HorseProduction.objects
        .select_related("manor", "manor__user")
        .filter(status=HorseProduction.Status.PRODUCING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0
    for production in qs:
        try:
            if finalize_horse_production(production, send_notification=True):
                count += 1
        except Exception:
            logger.exception(f"Failed to finalize horse production {production.id}")
    return count


@shared_task(name="gameplay.complete_livestock_production", bind=True, max_retries=2, default_retry_delay=30)
def complete_livestock_production(self, production_id: int):
    """
    完成家畜养殖的后台任务。
    """
    from gameplay.models import LivestockProduction
    from gameplay.services.ranch import finalize_livestock_production

    try:
        production = (
            LivestockProduction.objects
            .select_related("manor", "manor__user")
            .filter(pk=production_id)
            .first()
        )
        if not production:
            logger.warning(f"LivestockProduction {production_id} not found")
            return "not_found"

        now = timezone.now()
        if production.complete_at and production.complete_at > now:
            remaining = int((production.complete_at - now).total_seconds())
            if remaining > 0:
                complete_livestock_production.apply_async(args=[production_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_livestock_production(production, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete livestock production {production_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_livestock_productions")
def scan_livestock_productions(limit: int = 200):
    """
    扫描并完成所有到期的家畜养殖（用于 worker 宕机恢复）。
    """
    from gameplay.models import LivestockProduction
    from gameplay.services.ranch import finalize_livestock_production

    now = timezone.now()
    qs = (
        LivestockProduction.objects
        .select_related("manor", "manor__user")
        .filter(status=LivestockProduction.Status.PRODUCING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0
    for production in qs:
        try:
            if finalize_livestock_production(production, send_notification=True):
                count += 1
        except Exception:
            logger.exception(f"Failed to finalize livestock production {production.id}")
    return count


@shared_task(name="gameplay.complete_smelting_production", bind=True, max_retries=2, default_retry_delay=30)
def complete_smelting_production(self, production_id: int):
    """
    完成金属冶炼的后台任务。
    """
    from gameplay.models import SmeltingProduction
    from gameplay.services.smithy import finalize_smelting_production

    try:
        production = (
            SmeltingProduction.objects
            .select_related("manor", "manor__user")
            .filter(pk=production_id)
            .first()
        )
        if not production:
            logger.warning(f"SmeltingProduction {production_id} not found")
            return "not_found"

        now = timezone.now()
        if production.complete_at and production.complete_at > now:
            remaining = int((production.complete_at - now).total_seconds())
            if remaining > 0:
                complete_smelting_production.apply_async(args=[production_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_smelting_production(production, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete smelting production {production_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_smelting_productions")
def scan_smelting_productions(limit: int = 200):
    """
    扫描并完成所有到期的金属冶炼（用于 worker 宕机恢复）。
    """
    from gameplay.models import SmeltingProduction
    from gameplay.services.smithy import finalize_smelting_production

    now = timezone.now()
    qs = (
        SmeltingProduction.objects
        .select_related("manor", "manor__user")
        .filter(status=SmeltingProduction.Status.PRODUCING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0
    for production in qs:
        try:
            if finalize_smelting_production(production, send_notification=True):
                count += 1
        except Exception:
            logger.exception(f"Failed to finalize smelting production {production.id}")
    return count


@shared_task(name="gameplay.complete_equipment_forging", bind=True, max_retries=2, default_retry_delay=30)
def complete_equipment_forging(self, production_id: int):
    """
    完成装备锻造的后台任务。
    """
    from gameplay.models import EquipmentProduction
    from gameplay.services.forge import finalize_equipment_forging

    try:
        production = (
            EquipmentProduction.objects
            .select_related("manor", "manor__user")
            .filter(pk=production_id)
            .first()
        )
        if not production:
            logger.warning(f"EquipmentProduction {production_id} not found")
            return "not_found"

        now = timezone.now()
        if production.complete_at and production.complete_at > now:
            remaining = int((production.complete_at - now).total_seconds())
            if remaining > 0:
                complete_equipment_forging.apply_async(args=[production_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_equipment_forging(production, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete equipment forging {production_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_equipment_forgings")
def scan_equipment_forgings(limit: int = 200):
    """
    扫描并完成所有到期的装备锻造（用于 worker 宕机恢复）。
    """
    from gameplay.models import EquipmentProduction
    from gameplay.services.forge import finalize_equipment_forging

    now = timezone.now()
    qs = (
        EquipmentProduction.objects
        .select_related("manor", "manor__user")
        .filter(status=EquipmentProduction.Status.FORGING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0
    for production in qs:
        try:
            if finalize_equipment_forging(production, send_notification=True):
                count += 1
        except Exception:
            logger.exception(f"Failed to finalize equipment forging {production.id}")
    return count


@shared_task(name="gameplay.complete_troop_recruitment", bind=True, max_retries=2, default_retry_delay=30)
def complete_troop_recruitment(self, recruitment_id: int):
    """
    完成护院募兵的后台任务。
    """
    from gameplay.models import TroopRecruitment
    from gameplay.services.recruitment import finalize_troop_recruitment

    try:
        recruitment = (
            TroopRecruitment.objects
            .select_related("manor", "manor__user")
            .filter(pk=recruitment_id)
            .first()
        )
        if not recruitment:
            logger.warning(f"TroopRecruitment {recruitment_id} not found")
            return "not_found"

        now = timezone.now()
        if recruitment.complete_at and recruitment.complete_at > now:
            remaining = int((recruitment.complete_at - now).total_seconds())
            if remaining > 0:
                complete_troop_recruitment.apply_async(args=[recruitment_id], countdown=remaining)
                return "rescheduled"

        finalized = finalize_troop_recruitment(recruitment, send_notification=True)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete troop recruitment {recruitment_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_troop_recruitments")
def scan_troop_recruitments(limit: int = 200):
    """
    扫描并完成所有到期的护院募兵（用于 worker 宕机恢复）。
    """
    from gameplay.models import TroopRecruitment
    from gameplay.services.recruitment import finalize_troop_recruitment

    now = timezone.now()
    qs = (
        TroopRecruitment.objects
        .select_related("manor", "manor__user")
        .filter(status=TroopRecruitment.Status.RECRUITING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    count = 0
    for recruitment in qs:
        try:
            if finalize_troop_recruitment(recruitment, send_notification=True):
                count += 1
        except Exception:
            logger.exception(f"Failed to finalize troop recruitment {recruitment.id}")
    return count


# ============ 踢馆/侦察系统任务 ============


@shared_task(name="gameplay.complete_scout", bind=True, max_retries=2, default_retry_delay=30)
def complete_scout_task(self, record_id: int):
    """
    完成侦察的后台任务。
    """
    from gameplay.models import ScoutRecord
    from gameplay.services.raid import finalize_scout

    try:
        record = (
            ScoutRecord.objects
            .select_related("attacker", "defender")
            .filter(pk=record_id)
            .first()
        )
        if not record:
            logger.warning(f"ScoutRecord {record_id} not found")
            return "not_found"

        now = timezone.now()
        # 检查是否已经完成
        if record.status != ScoutRecord.Status.SCOUTING:
            return "already_completed"

        # 检查是否到达完成时间
        if record.complete_at and record.complete_at > now:
            remaining = int((record.complete_at - now).total_seconds())
            if remaining > 0:
                complete_scout_task.apply_async(args=[record_id], countdown=remaining)
                return "rescheduled"

        finalize_scout(record, now=now)
        return "completed"
    except Exception as exc:
        logger.exception(f"Failed to complete scout {record_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.complete_scout_return", bind=True, max_retries=2, default_retry_delay=30)
def complete_scout_return_task(self, record_id: int):
    """
    完成侦察返程的后台任务。

    侦察返程完成后，发送结果消息给进攻方。
    """
    from gameplay.models import ScoutRecord
    from gameplay.services.raid import finalize_scout_return

    try:
        record = (
            ScoutRecord.objects
            .select_related("attacker", "defender")
            .filter(pk=record_id)
            .first()
        )
        if not record:
            logger.warning(f"ScoutRecord {record_id} not found")
            return "not_found"

        now = timezone.now()
        # 检查是否处于返程状态
        if record.status != ScoutRecord.Status.RETURNING:
            return "invalid_status"

        # 检查是否到达返程完成时间
        if record.return_at and record.return_at > now:
            remaining = int((record.return_at - now).total_seconds())
            if remaining > 0:
                complete_scout_return_task.apply_async(args=[record_id], countdown=remaining)
                return "rescheduled"

        finalize_scout_return(record, now=now)
        return "completed"
    except Exception as exc:
        logger.exception(f"Failed to complete scout return {record_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_scout_records")
def scan_scout_records(limit: int = 200):
    """
    扫描并完成所有到期的侦察任务（用于 worker 宕机恢复）。

    处理两种状态：
    - SCOUTING：去程到达，判定成功/失败，进入返程
    - RETURNING：返程完成，发送结果消息给进攻方
    """
    from gameplay.models import ScoutRecord
    from gameplay.services.raid import finalize_scout, finalize_scout_return

    now = timezone.now()
    count = 0

    # 处理去程到达（SCOUTING -> RETURNING）
    scouting_qs = (
        ScoutRecord.objects
        .select_related("attacker", "defender")
        .filter(status=ScoutRecord.Status.SCOUTING, complete_at__lte=now)
        .order_by("complete_at")[:limit]
    )
    for record in scouting_qs:
        try:
            finalize_scout(record, now=now)
            count += 1
        except Exception:
            logger.exception(f"Failed to finalize scout record {record.id}")

    # 处理返程完成（RETURNING -> SUCCESS/FAILED）
    returning_qs = (
        ScoutRecord.objects
        .select_related("attacker", "defender")
        .filter(status=ScoutRecord.Status.RETURNING, return_at__lte=now)
        .order_by("return_at")[:limit]
    )
    for record in returning_qs:
        try:
            finalize_scout_return(record, now=now)
            count += 1
        except Exception:
            logger.exception(f"Failed to finalize scout return {record.id}")

    return count


@shared_task(name="gameplay.process_raid_battle", bind=True, max_retries=2, default_retry_delay=30)
def process_raid_battle_task(self, run_id: int):
    """
    处理踢馆战斗的后台任务。
    """
    from gameplay.models import RaidRun
    from gameplay.services.raid import process_raid_battle

    try:
        run = (
            RaidRun.objects
            .select_related("attacker", "defender")
            .prefetch_related("guests")
            .filter(pk=run_id)
            .first()
        )
        if not run:
            logger.warning(f"RaidRun {run_id} not found")
            return "not_found"

        now = timezone.now()
        # 检查状态
        if run.status not in [RaidRun.Status.MARCHING, RaidRun.Status.RETREATED]:
            return "invalid_status"

        # 撤退中的队伍不应在 battle_at 被提前结算；按 return_at 等待完成
        if run.status == RaidRun.Status.RETREATED:
            if run.return_at and run.return_at > now:
                remaining = int((run.return_at - now).total_seconds())
                if remaining > 0:
                    complete_raid_task.apply_async(args=[run_id], countdown=remaining)
                    return "retreated_rescheduled"
            # return_at 已到（或缺失），交给完成任务收尾
            complete_raid_task.apply_async(args=[run_id], countdown=0)
            return "retreated_forwarded"

        # 检查是否到达战斗时间
        if run.status == RaidRun.Status.MARCHING and run.battle_at and run.battle_at > now:
            remaining = int((run.battle_at - now).total_seconds())
            if remaining > 0:
                process_raid_battle_task.apply_async(args=[run_id], countdown=remaining)
                return "rescheduled"

        process_raid_battle(run, now=now)
        return "completed"
    except Exception as exc:
        logger.exception(f"Failed to process raid battle {run_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.complete_raid", bind=True, max_retries=2, default_retry_delay=30)
def complete_raid_task(self, run_id: int):
    """
    完成踢馆返程的后台任务。
    """
    from gameplay.models import RaidRun
    from gameplay.services.raid import finalize_raid

    try:
        run = (
            RaidRun.objects
            .select_related("attacker", "defender", "battle_report")
            .prefetch_related("guests")
            .filter(pk=run_id)
            .first()
        )
        if not run:
            logger.warning(f"RaidRun {run_id} not found")
            return "not_found"

        now = timezone.now()
        # 检查状态
        if run.status == RaidRun.Status.COMPLETED:
            return "already_completed"

        # 撤退状态直接完成
        if run.status == RaidRun.Status.RETREATED:
            if run.return_at and run.return_at > now:
                remaining = int((run.return_at - now).total_seconds())
                if remaining > 0:
                    complete_raid_task.apply_async(args=[run_id], countdown=remaining)
                    return "rescheduled"
            finalize_raid(run, now=now)
            return "completed"

        # 返程状态检查时间
        if run.status == RaidRun.Status.RETURNING:
            if run.return_at and run.return_at > now:
                remaining = int((run.return_at - now).total_seconds())
                if remaining > 0:
                    complete_raid_task.apply_async(args=[run_id], countdown=remaining)
                    return "rescheduled"
            finalize_raid(run, now=now)
            return "completed"

        return "invalid_status"
    except Exception as exc:
        logger.exception(f"Failed to complete raid {run_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="gameplay.scan_raid_runs")
def scan_raid_runs(limit: int = 200):
    """
    扫描并处理所有到期的踢馆任务（用于 worker 宕机恢复）。
    """
    from gameplay.models import RaidRun
    from gameplay.services.raid import process_raid_battle, finalize_raid

    now = timezone.now()
    count = 0

    # 处理行军中但已到达战斗时间的
    marching_qs = (
        RaidRun.objects
        .select_related("attacker", "defender")
        .prefetch_related("guests")
        .filter(status=RaidRun.Status.MARCHING, battle_at__lte=now)
        .order_by("battle_at")[:limit]
    )
    for run in marching_qs:
        try:
            process_raid_battle(run, now=now)
            count += 1
        except Exception:
            logger.exception(f"Failed to process raid battle {run.id}")

    # 处理返程中但已完成的
    returning_qs = (
        RaidRun.objects
        .select_related("attacker", "defender", "battle_report")
        .prefetch_related("guests")
        .filter(status=RaidRun.Status.RETURNING, return_at__lte=now)
        .order_by("return_at")[:limit]
    )
    for run in returning_qs:
        try:
            finalize_raid(run, now=now)
            count += 1
        except Exception:
            logger.exception(f"Failed to finalize raid {run.id}")

    # 处理撤退中但已完成的
    retreated_qs = (
        RaidRun.objects
        .select_related("attacker", "defender")
        .prefetch_related("guests")
        .filter(status=RaidRun.Status.RETREATED, return_at__lte=now)
        .order_by("return_at")[:limit]
    )
    for run in retreated_qs:
        try:
            finalize_raid(run, now=now)
            count += 1
        except Exception:
            logger.exception(f"Failed to finalize retreated raid {run.id}")

    return count


# ============ 数据清理任务 ============


@shared_task(name="gameplay.cleanup_old_data")
def cleanup_old_data_task():
    """
    清理过期的流水记录数据，节省数据库空间。

    每天凌晨执行一次，清理：
    - ResourceEvent: 保留30天
    - 其他日志表由各自模块的任务处理
    """
    from datetime import timedelta
    from gameplay.models import ResourceEvent

    cutoff = timezone.now() - timedelta(days=30)
    deleted, _ = ResourceEvent.objects.filter(created_at__lt=cutoff).delete()

    logger.info(f"清理了 {deleted} 条30天前的资源流水记录")
    return deleted


# ============ 监牢系统任务 ============


@shared_task(name="gameplay.decay_prisoner_loyalty")
def decay_prisoner_loyalty_task():
    """
    每日衰减囚犯忠诚度。

    每天执行一次，将所有关押中的囚犯忠诚度降低指定值（默认5点）。
    忠诚度最低降至0。
    """
    from django.db.models import F, Greatest

    from gameplay.constants import PVPConstants
    from gameplay.models import JailPrisoner

    decay_amount = int(getattr(PVPConstants, "JAIL_LOYALTY_DAILY_DECAY", 5) or 5)

    # 批量更新所有关押中的囚犯，忠诚度减少但不低于0
    updated = JailPrisoner.objects.filter(
        status=JailPrisoner.Status.HELD
    ).update(
        loyalty=Greatest(F("loyalty") - decay_amount, 0)
    )

    logger.info(f"囚犯忠诚度每日衰减：更新了 {updated} 名囚犯，每人降低 {decay_amount} 点")
    return updated
