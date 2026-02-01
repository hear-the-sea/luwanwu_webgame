"""
商铺和拍卖行定时任务
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from .models import ShopStock
from .services.shop_config import get_shop_config, reload_shop_config

logger = logging.getLogger(__name__)


@shared_task(name="trade.refresh_shop_stock", bind=True, max_retries=2, default_retry_delay=60)
def refresh_shop_stock(self):
    """
    每日刷新商铺库存

    对于配置了 daily_refresh: true 的商品，
    将其库存重置为 YAML 配置的初始值。
    """
    try:
        # 重新加载配置（清除缓存）
        reload_shop_config()
        config_list = get_shop_config()

        today = timezone.now().date()
        refreshed_count = 0
        failed_items = []

        for item in config_list:
            # 只刷新设置了 daily_refresh 且有限库存的商品
            if item.daily_refresh and item.stock > 0:
                try:
                    ShopStock.objects.update_or_create(
                        item_key=item.item_key,
                        defaults={"current_stock": item.stock, "last_refresh": today},
                    )
                    refreshed_count += 1
                except Exception as e:
                    logger.exception(f"Failed to refresh stock for item {item.item_key}")
                    failed_items.append({"item_key": item.item_key, "error": str(e)})

        # 记录失败统计，便于监控告警
        if failed_items:
            logger.error(
                f"Shop stock refresh completed with {len(failed_items)} failures: "
                f"{[f['item_key'] for f in failed_items]}"
            )
            return f"refreshed {refreshed_count} items, {len(failed_items)} failed"

        return f"refreshed {refreshed_count} items"
    except Exception as exc:
        logger.exception(f"Failed to refresh shop stock: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="trade.process_expired_listings", bind=True, max_retries=2, default_retry_delay=60)
def process_expired_listings(self):
    """
    处理过期的交易行挂单
    建议每10分钟执行一次
    """
    try:
        from .services.market_service import expire_listings

        count = expire_listings()
        return f"处理了 {count} 个过期挂单"
    except Exception as exc:
        logger.exception(f"Failed to process expired listings: {exc}")
        raise self.retry(exc=exc)


# ============ 拍卖行定时任务 ============


@shared_task(name="trade.settle_auction_round", bind=True, max_retries=2, default_retry_delay=60)
def settle_auction_round_task(self):
    """
    结算到期的拍卖轮次

    每天0点和12点各检查一次，如果有到期的轮次则进行结算：
    - 中标者：消耗冻结金条，通过邮件发放物品
    - 落选者：金条已在出价时即时退还
    - 流拍商品：标记状态，不重新上架

    结算完成后自动触发创建新轮次任务。
    """
    try:
        from .services.auction_service import settle_auction_round

        stats = settle_auction_round()

        if stats["settled"] > 0:
            # 结算完成后触发创建新轮次
            create_auction_round_task.delay()
            logger.info(
                f"拍卖轮次结算完成：售出 {stats['sold']} 件，"
                f"流拍 {stats['unsold']} 件，"
                f"共收取 {stats['total_gold_bars']} 金条"
            )
            return (
                f"结算完成：售出 {stats['sold']} 件，流拍 {stats['unsold']} 件，"
                f"共 {stats['total_gold_bars']} 金条"
            )
        else:
            return "没有需要结算的拍卖轮次"
    except Exception as exc:
        logger.exception(f"结算拍卖轮次失败: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="trade.create_auction_round", bind=True, max_retries=2, default_retry_delay=60)
def create_auction_round_task(self):
    """
    创建新的拍卖轮次

    在以下情况触发：
    1. 结算完成后自动触发
    2. 每天0:10的定时检查（防止遗漏）

    如果已存在进行中的轮次，则不会创建新轮次。
    """
    try:
        from .services.auction_config import reload_auction_config
        from .services.auction_service import create_auction_round

        # 重新加载配置（清除缓存，确保获取最新配置）
        reload_auction_config()

        auction_round = create_auction_round()

        if auction_round:
            logger.info(
                f"创建拍卖轮次 #{auction_round.round_number}，"
                f"共 {auction_round.slots.count()} 个拍卖位"
            )
            return (
                f"创建拍卖轮次 #{auction_round.round_number}，"
                f"拍卖位数量: {auction_round.slots.count()}"
            )
        else:
            return "已有进行中的拍卖轮次或无可用商品，跳过创建"
    except Exception as exc:
        logger.exception(f"创建拍卖轮次失败: {exc}")
        raise self.retry(exc=exc)
