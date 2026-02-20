"""
聊天服务层
"""
from __future__ import annotations

import logging
from typing import Tuple

from gameplay.models import Manor
from core.exceptions import InsufficientStockError
from gameplay.services.inventory import consume_inventory_item

logger = logging.getLogger(__name__)

TRUMPET_ITEM_KEY = "small_trumpet"


def consume_trumpet(user_id: int) -> Tuple[bool, str]:
    """
    消耗小喇叭道具（世界频道发言）

    Args:
        user_id: 用户ID

    Returns:
        (success, error_message)
    """
    if not user_id:
        return False, "未登录，无法发言"

    try:
        manor = Manor.objects.get(user_id=int(user_id))
    except Manor.DoesNotExist:
        return False, "庄园不存在，无法发言"

    try:
        # 消耗道具（内部包含事务处理）
        consume_inventory_item(manor, TRUMPET_ITEM_KEY, 1)
        return True, ""
    except InsufficientStockError:
        return False, "小喇叭不足，无法在世界频道发言"
    except ValueError as exc:
        logger.warning("Failed to consume trumpet due to invalid input: %s", exc)
        return False, "扣除小喇叭失败，请稍后重试"
    except Exception:
        logger.exception("Unexpected error when consuming trumpet for user_id=%s", user_id)
        return False, "扣除小喇叭失败，请稍后重试"
