# guilds/tasks.py
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import Guild, GuildDonationLog, GuildExchangeLog, GuildResourceLog
from .services.contribution import reset_weekly_contributions
from .services.warehouse import produce_equipment, produce_experience_items, produce_resource_packs

logger = logging.getLogger(__name__)


@shared_task(name="guilds.process_single_guild_production", bind=True, max_retries=3, default_retry_delay=60)
def process_single_guild_production(self, guild_id: int):
    """
    处理单个帮会的每日科技产出
    """
    try:
        guild = Guild.objects.prefetch_related("technologies").get(pk=guild_id)
        if not guild.is_active:
            return f"guild {guild_id} is inactive"

        # 构建科技字典，避免重复查询
        techs = {t.tech_key: t for t in guild.technologies.all()}
        produced_items = []

        # 装备锻造
        tech = techs.get("equipment_forge")
        if tech and tech.level > 0:
            try:
                produce_equipment(guild, tech.level)
                tech.last_production_at = timezone.now()
                tech.save(update_fields=["last_production_at"])
                produced_items.append("equipment")
            except Exception as exc:
                logger.error("Failed to produce equipment for guild %s: %s", guild.id, exc)

        # 经验炼制
        tech = techs.get("experience_refine")
        if tech and tech.level > 0:
            try:
                produce_experience_items(guild, tech.level)
                tech.last_production_at = timezone.now()
                tech.save(update_fields=["last_production_at"])
                produced_items.append("experience")
            except Exception as exc:
                logger.error("Failed to produce experience items for guild %s: %s", guild.id, exc)

        # 资源补给
        tech = techs.get("resource_supply")
        if tech and tech.level > 0:
            try:
                produce_resource_packs(guild, tech.level)
                tech.last_production_at = timezone.now()
                tech.save(update_fields=["last_production_at"])
                produced_items.append("resource")
            except Exception as exc:
                logger.error("Failed to produce resource packs for guild %s: %s", guild.id, exc)

        return f"processed guild {guild_id}: {', '.join(produced_items)}"
    except Guild.DoesNotExist:
        logger.warning("Guild %s not found during daily production", guild_id)
        return "guild not found"
    except Exception as exc:
        logger.exception("Failed to process guild %s production: %s", guild_id, exc)
        raise self.retry(exc=exc)


@shared_task(name="guilds.tech_daily_production", bind=True, max_retries=2, default_retry_delay=60)
def guild_tech_daily_production(self):
    """
    每日帮会科技产出（Master任务）
    执行时间：每天00:00（UTC+8）
    采用 Fan-out 模式分发任务，避免单次任务超时
    """
    try:
        from common.utils.celery import safe_apply_async

        # 获取所有活跃帮会ID
        guild_ids = list(Guild.objects.filter(is_active=True).values_list("id", flat=True))
        dispatched_count = 0

        for guild_id in guild_ids:
            dispatched = safe_apply_async(
                process_single_guild_production,
                args=[guild_id],
                logger=logger,
                log_message=f"Failed to dispatch daily production for guild {guild_id}",
            )
            if dispatched:
                dispatched_count += 1

        return f"dispatched {dispatched_count} guild tasks"
    except Exception as exc:
        logger.exception("Failed to run guild tech daily production master task: %s", exc)
        raise self.retry(exc=exc)


@shared_task(name="guilds.reset_weekly_stats", bind=True, max_retries=2, default_retry_delay=60)
def reset_guild_weekly_stats(self):
    """
    重置帮会每周统计
    执行时间：每周一00:00（UTC+8）
    """
    try:
        reset_weekly_contributions()
        return "reset completed"
    except Exception as exc:
        logger.exception("Failed to reset guild weekly stats: %s", exc)
        raise self.retry(exc=exc)


@shared_task(name="guilds.cleanup_old_logs", bind=True, max_retries=2, default_retry_delay=60)
def cleanup_old_guild_logs(self):
    """
    清理旧的帮会日志
    执行时间：每天凌晨03:00（UTC+8）
    保留最近30天的日志
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=30)

        donation_deleted, _ = GuildDonationLog.objects.filter(donated_at__lt=cutoff_date).delete()
        exchange_deleted, _ = GuildExchangeLog.objects.filter(exchanged_at__lt=cutoff_date).delete()
        resource_deleted, _ = GuildResourceLog.objects.filter(created_at__lt=cutoff_date).delete()

        total = donation_deleted + exchange_deleted + resource_deleted
        logger.info(
            "Cleaned up %d old guild logs (donation=%d, exchange=%d, resource=%d)",
            total,
            donation_deleted,
            exchange_deleted,
            resource_deleted,
        )
        return f"cleaned up {total} logs"
    except Exception as exc:
        logger.exception("Failed to cleanup old guild logs: %s", exc)
        raise self.retry(exc=exc)
