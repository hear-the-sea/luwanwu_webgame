# guilds/tasks.py
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import Guild, GuildDonationLog, GuildExchangeLog, GuildResourceLog
from .services.warehouse import (
    produce_equipment,
    produce_experience_items,
    produce_resource_packs
)
from .services.contribution import reset_weekly_contributions

logger = logging.getLogger(__name__)


@shared_task(name="guilds.tech_daily_production", bind=True, max_retries=2, default_retry_delay=60)
def guild_tech_daily_production(self):
    """
    每日帮会科技产出
    执行时间：每天00:00（UTC+8）
    """
    try:
        # 预加载所有帮会科技，优化 N+1 查询
        guilds = Guild.objects.filter(is_active=True).prefetch_related("technologies")
        processed_count = 0

        for guild in guilds:
            # 构建科技字典，避免重复查询
            techs = {t.tech_key: t for t in guild.technologies.all()}

            # 装备锻造
            tech = techs.get("equipment_forge")
            if tech and tech.level > 0:
                try:
                    produce_equipment(guild, tech.level)
                    tech.last_production_at = timezone.now()
                    tech.save(update_fields=["last_production_at"])
                except Exception:
                    logger.exception(f"Failed to produce equipment for guild {guild.id}")

            # 经验炼制
            tech = techs.get("experience_refine")
            if tech and tech.level > 0:
                try:
                    produce_experience_items(guild, tech.level)
                    tech.last_production_at = timezone.now()
                    tech.save(update_fields=["last_production_at"])
                except Exception:
                    logger.exception(f"Failed to produce experience items for guild {guild.id}")

            # 资源补给
            tech = techs.get("resource_supply")
            if tech and tech.level > 0:
                try:
                    produce_resource_packs(guild, tech.level)
                    tech.last_production_at = timezone.now()
                    tech.save(update_fields=["last_production_at"])
                except Exception:
                    logger.exception(f"Failed to produce resource packs for guild {guild.id}")

            processed_count += 1

        return f"processed {processed_count} guilds"
    except Exception as exc:
        logger.exception(f"Failed to run guild tech daily production: {exc}")
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
        logger.exception(f"Failed to reset guild weekly stats: {exc}")
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
        logger.info(f"Cleaned up {total} old guild logs (donation={donation_deleted}, exchange={exchange_deleted}, resource={resource_deleted})")
        return f"cleaned up {total} logs"
    except Exception as exc:
        logger.exception(f"Failed to cleanup old guild logs: {exc}")
        raise self.retry(exc=exc)
