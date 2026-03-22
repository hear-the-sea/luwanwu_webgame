"""
WebSocket 通知服务模块

提供统一的 WebSocket 推送通知功能。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from core.utils.infrastructure import NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from gameplay.models import Manor


def notify_user(
    user_id: int,
    payload: Dict[str, Any],
    *,
    log_context: str = "WebSocket notification",
) -> bool:
    """
    向指定用户发送 WebSocket 通知。

    Args:
        user_id: 用户ID
        payload: 通知内容字典，应包含 'kind' 和 'title' 等字段
        log_context: 日志上下文描述，用于调试

    Returns:
        是否发送成功

    用法示例:
        notify_user(
            user_id=manor.user_id,
            payload={
                "kind": "production_complete",
                "title": "装备锻造完成",
                "equipment_key": "equip_sword",
                "quantity": 10,
            },
            log_context="equipment forging notification",
        )
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        logger.debug("Channel layer not available, skipping %s", log_context)
        return False

    try:
        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {"type": "notify.message", "payload": payload},
        )
        return True
    except NOTIFICATION_INFRASTRUCTURE_EXCEPTIONS as exc:
        logger.warning("Failed to send %s via channels: %s", log_context, exc, exc_info=True)
        return False


def notify_manor(
    manor: "Manor",  # noqa: F821
    payload: Dict[str, Any],
    *,
    log_context: str = "WebSocket notification",
) -> bool:
    """
    向指定庄园所有者发送 WebSocket 通知。

    Args:
        manor: 庄园对象（需要有 user_id 属性）
        payload: 通知内容字典
        log_context: 日志上下文描述

    Returns:
        是否发送成功
    """
    return notify_user(manor.user_id, payload, log_context=log_context)
