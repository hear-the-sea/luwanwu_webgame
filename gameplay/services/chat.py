"""
聊天服务层
"""

from __future__ import annotations

import logging
from typing import Tuple

from core.exceptions import InsufficientStockError
from gameplay.models import Manor
from gameplay.services.inventory.core import add_item_to_inventory, consume_inventory_item

logger = logging.getLogger(__name__)

TRUMPET_ITEM_KEY = "small_trumpet"


def _get_manor_for_user(user_id: int) -> Manor | None:
    if not user_id:
        return None
    try:
        return Manor.objects.get(user_id=int(user_id))
    except (TypeError, ValueError):
        logger.warning("Invalid user_id when resolving manor for chat service: %r", user_id)
        return None
    except Manor.DoesNotExist:
        return None


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

    manor = _get_manor_for_user(user_id)
    if manor is None:
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


def refund_trumpet(user_id: int) -> bool:
    """
    返还世界频道发言失败后已扣除的小喇叭。
    """
    manor = _get_manor_for_user(user_id)
    if manor is None:
        logger.warning("Failed to refund trumpet because manor was not found: user_id=%s", user_id)
        return False

    try:
        add_item_to_inventory(manor, TRUMPET_ITEM_KEY, 1)
        return True
    except Exception:
        logger.exception("Unexpected error when refunding trumpet for user_id=%s", user_id)
        return False
