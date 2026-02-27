from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.utils import timezone

from gameplay.models import GlobalMailCampaign, Manor
from gameplay.services.global_mail import deliver_campaign_to_manor

logger = logging.getLogger(__name__)

GLOBAL_MAIL_BACKFILL_DEFAULT_BATCH_SIZE = 500
GLOBAL_MAIL_BACKFILL_MIN_BATCH_SIZE = 50
GLOBAL_MAIL_BACKFILL_ERROR_LOG_LIMIT = 5


@shared_task(name="gameplay.backfill_global_mail_campaign")
def backfill_global_mail_campaign_task(
    campaign_id: int, batch_size: int = GLOBAL_MAIL_BACKFILL_DEFAULT_BATCH_SIZE
) -> dict[str, Any]:
    """
    异步补发全服邮件活动（幂等）。

    说明：
    - 若活动不存在，返回 not_found；
    - 若活动当前不生效，返回 inactive；
    - 投递过程为 best-effort：单个庄园失败会记录并继续，避免整任务中断。
    """
    campaign = GlobalMailCampaign.objects.filter(pk=campaign_id).first()
    if campaign is None:
        logger.warning("Global mail backfill skipped: campaign not found (campaign_id=%s)", campaign_id)
        return {
            "status": "not_found",
            "campaign_id": int(campaign_id),
            "scanned": 0,
            "delivered": 0,
            "failed": 0,
        }

    current_time = timezone.now()
    if not campaign.is_active_at(current_time):
        logger.info(
            "Global mail backfill skipped: campaign inactive at dispatch time (campaign_id=%s key=%s)",
            campaign.id,
            campaign.key,
        )
        return {
            "status": "inactive",
            "campaign_id": int(campaign.id),
            "scanned": 0,
            "delivered": 0,
            "failed": 0,
        }

    normalized_batch_size = max(
        GLOBAL_MAIL_BACKFILL_MIN_BATCH_SIZE, int(batch_size or GLOBAL_MAIL_BACKFILL_DEFAULT_BATCH_SIZE)
    )
    delivered_count = 0
    failed_count = 0
    scanned_count = 0

    for manor in Manor.objects.only("id").order_by("id").iterator(chunk_size=normalized_batch_size):
        scanned_count += 1
        try:
            if deliver_campaign_to_manor(campaign, manor, now=current_time):
                delivered_count += 1
        except Exception as exc:
            failed_count += 1
            if failed_count <= GLOBAL_MAIL_BACKFILL_ERROR_LOG_LIMIT:
                logger.exception(
                    "Global mail backfill delivery failed: campaign_id=%s manor_id=%s error=%s",
                    campaign.id,
                    manor.id,
                    exc,
                )

    logger.info(
        "Global mail backfill completed: campaign_id=%s key=%s scanned=%s delivered=%s failed=%s",
        campaign.id,
        campaign.key,
        scanned_count,
        delivered_count,
        failed_count,
    )
    return {
        "status": "ok",
        "campaign_id": int(campaign.id),
        "scanned": int(scanned_count),
        "delivered": int(delivered_count),
        "failed": int(failed_count),
    }


def enqueue_global_mail_backfill(campaign_id: int, *, batch_size: int = GLOBAL_MAIL_BACKFILL_DEFAULT_BATCH_SIZE):
    """提交异步补发任务并返回 Celery AsyncResult。"""
    return backfill_global_mail_campaign_task.apply_async(args=[int(campaign_id), int(batch_size)])
