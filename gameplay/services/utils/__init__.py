"""
游戏玩法工具模块

本模块包含各种工具函数和辅助服务：
- cache: 缓存管理
- notifications: 通知服务
- messages: 消息管理
- query_optimization: 查询优化
- template_cache: 模板缓存
"""

from __future__ import annotations

# 缓存管理
from .cache import *  # noqa: F401, F403

# 消息管理
from .messages import (
    MESSAGE_RETENTION_DAYS,
    claim_message_attachments,
    cleanup_old_messages,
    create_message,
    delete_all_messages,
    delete_messages,
    list_messages,
    mark_all_messages_read,
    mark_messages_read,
    unread_message_count,
)

# 通知服务
from .notifications import *  # noqa: F401, F403

# 查询优化
from .query_optimization import *  # noqa: F401, F403

# 模板缓存
from .template_cache import *  # noqa: F401, F403

__all__ = [
    # 消息管理
    "MESSAGE_RETENTION_DAYS",
    "claim_message_attachments",
    "cleanup_old_messages",
    "create_message",
    "delete_all_messages",
    "delete_messages",
    "list_messages",
    "mark_all_messages_read",
    "mark_messages_read",
    "unread_message_count",
]
