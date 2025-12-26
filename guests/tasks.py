from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="guests.complete_training", bind=True, max_retries=2, default_retry_delay=30)
def complete_guest_training(self, guest_id: int):
    from guests.models import Guest
    from guests.services import finalize_guest_training

    try:
        guest = Guest.objects.select_related("manor").filter(pk=guest_id).first()
        if not guest:
            logger.warning(f"Guest {guest_id} not found")
            return "not_found"
        now = timezone.now()
        if guest.training_complete_at and guest.training_complete_at > now:
            remaining = int((guest.training_complete_at - now).total_seconds())
            if remaining > 0:
                complete_guest_training.apply_async(args=[guest_id], countdown=remaining, queue="timer")
                return "rescheduled"
        finalized = finalize_guest_training(guest, now=now)
        return "completed" if finalized else "skipped"
    except Exception as exc:
        logger.exception(f"Failed to complete guest training {guest_id}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="guests.scan_training")
def scan_guest_training(limit: int = 200):
    from guests.models import Guest
    from guests.services import finalize_guest_training

    now = timezone.now()
    qs = (
        Guest.objects.select_related("manor")
        .filter(training_complete_at__isnull=False, training_complete_at__lte=now)
        .order_by("training_complete_at")[:limit]
    )
    count = 0
    for guest in qs:
        try:
            if finalize_guest_training(guest, now=now):
                count += 1
        except Exception:
            logger.exception(f"Failed to finalize guest training {guest.id}")
    return count


@shared_task(name="guests.process_daily_loyalty", bind=True, max_retries=2, default_retry_delay=60)
def process_daily_loyalty(self):
    """
    处理每日门客忠诚度变化
    建议每日凌晨执行一次
    """
    import random
    from datetime import timedelta

    from guests.models import Guest, SalaryPayment, GuestDefection
    from gameplay.services.messages import create_message

    try:
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)

        # 批量查询所有昨日已支付工资的 guest_ids（优化 N+1）
        paid_guest_ids = set(
            SalaryPayment.objects.filter(for_date=yesterday).values_list("guest_id", flat=True)
        )

        # 获取所有门客
        guests = list(Guest.objects.select_related("manor__user", "template").all())

        # 分类处理
        to_increase = []  # 需要增加忠诚度的门客
        to_decrease = []  # 需要减少忠诚度的门客
        defection_candidates = []  # 可能叛逃的门客

        for guest in guests:
            paid = guest.id in paid_guest_ids

            if paid:
                # 支付了工资，忠诚度+1，最高100
                if guest.loyalty < 100:
                    guest.loyalty = min(100, guest.loyalty + 1)
                    to_increase.append(guest)
            else:
                # 未支付工资，忠诚度-1
                guest.loyalty = max(0, guest.loyalty - 1)
                to_decrease.append(guest)

                # 检查是否叛逃（忠诚度<30时有30%概率）
                if guest.loyalty < 30 and random.random() < 0.3:
                    defection_candidates.append(guest)

        # 批量更新忠诚度（优化：减少数据库写入次数）
        all_updated = to_increase + to_decrease
        if all_updated:
            Guest.objects.bulk_update(all_updated, ["loyalty"], batch_size=500)

        # 处理叛逃（这些需要单独处理，因为涉及删除和发送消息）
        defection_count = 0
        for guest in defection_candidates:
            try:
                # 记录叛逃信息
                GuestDefection.objects.create(
                    manor=guest.manor,
                    guest_name=guest.display_name,
                    guest_level=guest.level,
                    guest_rarity=guest.rarity,
                    loyalty_at_defection=guest.loyalty
                )

                # 发送邮件通知
                create_message(
                    manor=guest.manor,
                    kind="system",
                    title="【门客叛逃】门客离开了庄园",
                    body=(
                        f"由于长期未支付工资，您的门客 {guest.display_name} (Lv{guest.level}) "
                        f"对您失去了信任，已经离开了庄园。\n\n"
                        f"门客信息：\n"
                        f"- 名称：{guest.display_name}\n"
                        f"- 等级：{guest.level}\n"
                        f"- 稀有度：{guest.get_rarity_display()}\n"
                        f"- 叛逃时忠诚度：{guest.loyalty}\n\n"
                        f"提示：请及时支付门客工资以保持他们的忠诚。"
                    ),
                )

                # 删除门客
                guest.delete()
                defection_count += 1
            except Exception:
                logger.exception(f"Failed to process defection for guest {guest.id}")

        updated_count = len(all_updated)
        return f"处理了 {updated_count} 个门客的忠诚度，{defection_count} 个门客叛逃"
    except Exception as exc:
        logger.exception(f"Failed to process daily loyalty: {exc}")
        raise self.retry(exc=exc)
