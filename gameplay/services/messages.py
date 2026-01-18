"""
消息管理服务
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.exceptions import (
    AttachmentAlreadyClaimedError,
    MessageNotFoundError,
    NoAttachmentError,
)
from ..models import InventoryItem, ItemTemplate, Manor, Message, ResourceEvent
from .cache import CacheKeys, CACHE_TIMEOUT_SHORT
from .resources import grant_resources

# 消息保留天数（自动清理超过此天数的消息）
MESSAGE_RETENTION_DAYS = 7


def create_message(
    manor: Manor,
    kind: str,
    title: str,
    body: str = "",
    battle_report=None,
    is_read: bool = False,
    attachments: Dict = None,
) -> Message:
    """
    为庄园创建一条消息。

    Args:
        manor: 庄园对象
        kind: 消息类型（battle/system/reward）
        title: 消息标题
        body: 消息内容
        battle_report: 关联的战报��象（可选）
        is_read: 是否已读
        attachments: 附件数据，格式：{"resources": {"grain": 100}, "items": {"item_key": 5}}

    Returns:
        创建的消息对象
    """
    from django.core.cache import cache

    message = Message.objects.create(
        manor=manor,
        kind=kind,
        title=title,
        body=body,
        battle_report=battle_report,
        is_read=is_read,
        attachments=attachments or {},
    )

    # 清除未读消息数缓存
    cache.delete(CacheKeys.unread_count(manor.id))

    return message


def bulk_create_messages(messages_data: list) -> list:
    """
    批量创建消息。

    Args:
        messages_data: 消息数据列表，每项包含 manor, kind, title, body 等字段

    Returns:
        创建的消息对象列表
    """
    from django.core.cache import cache

    if not messages_data:
        return []

    messages_to_create = [
        Message(
            manor=data["manor"],
            kind=data.get("kind", "system"),
            title=data["title"],
            body=data.get("body", ""),
            battle_report=data.get("battle_report"),
            is_read=data.get("is_read", False),
            attachments=data.get("attachments") or {},
        )
        for data in messages_data
    ]

    created_messages = Message.objects.bulk_create(messages_to_create)

    # 批量清除相关庄园的未读消息缓存
    manor_ids = {data["manor"].id for data in messages_data}
    cache_keys = [CacheKeys.unread_count(manor_id) for manor_id in manor_ids]
    cache.delete_many(cache_keys)

    return created_messages


def cleanup_old_messages(manor: Manor) -> None:
    """
    删除超过保留期限的旧消息。

    Args:
        manor: 庄园对象
    """
    from django.core.cache import cache

    # 性能优化：避免每次打开消息列表都触发一次 DELETE 扫描。
    # 保留期以“天”为单位，清理无需高频执行；这里对每个庄园做节流（默认 6 小时一次）。
    cleanup_gate_key = f"messages:cleanup_old:{manor.id}"
    if not cache.add(cleanup_gate_key, "1", timeout=6 * 60 * 60):
        return

    threshold = timezone.now() - timedelta(days=MESSAGE_RETENTION_DAYS)
    manor.messages.filter(created_at__lt=threshold).delete()


def list_messages(manor: Manor):
    """
    获取庄园的最新消息列表，并自动执行清理策略。

    Args:
        manor: 庄园对象

    Returns:
        消息查询集（按创建时间倒序）
    """
    cleanup_old_messages(manor)
    return manor.messages.select_related("battle_report").order_by("-created_at")


def delete_messages(manor: Manor, message_ids):
    """
    批量删除玩家选中的消息。

    Args:
        manor: 庄园对象
        message_ids: 消息ID列表
    """
    manor.messages.filter(id__in=message_ids).delete()


def delete_all_messages(manor: Manor):
    """
    一键清空所有消息。

    Args:
        manor: 庄园对象
    """
    manor.messages.all().delete()


def mark_messages_read(manor: Manor, message_ids):
    """
    将指定的消息标记为已读（不删除）。

    Args:
        manor: 庄园对象
        message_ids: 消息ID列表
    """
    from django.core.cache import cache

    manor.messages.filter(id__in=message_ids).update(is_read=True)

    # 清除未读消息数缓存
    cache.delete(CacheKeys.unread_count(manor.id))


def mark_all_messages_read(manor: Manor):
    """
    一键将所有消息标记为已读，清除UI中的未读标记。

    Args:
        manor: 庄园对象
    """
    from django.core.cache import cache

    manor.messages.filter(is_read=False).update(is_read=True)

    # 清除未读消息数缓存
    cache.delete(CacheKeys.unread_count(manor.id))


def unread_message_count(manor: Manor) -> int:
    """
    获取未读消息数量（用于显示通知点）。

    使用 5 秒缓存来避免频繁查询数据库。

    Args:
        manor: 庄园对象

    Returns:
        未读消息数量
    """
    from django.core.cache import cache

    cache_key = CacheKeys.unread_count(manor.id)
    count = cache.get(cache_key)

    if count is None:
        count = manor.messages.filter(is_read=False).count()
        cache.set(cache_key, count, timeout=CACHE_TIMEOUT_SHORT)

    return count


@transaction.atomic
def claim_message_attachments(message: Message) -> Dict:
    """
    领取消息附件，将资源和道具发放到玩家仓库。

    This function uses row-level locking to prevent race conditions
    in concurrent claim attempts.

    Args:
        message: 消息对象

    Returns:
        领取的物品摘要字典

    Raises:
        MessageNotFoundError: 消息不存在时抛出
        NoAttachmentError: 消息无附件时抛出
        AttachmentAlreadyClaimedError: 附件已领取时抛出
    """
    # CRITICAL: Use select_for_update to acquire row lock and prevent concurrent claims
    # This must be the first database operation in the transaction
    message = (
        Message.objects.select_for_update()
        .select_related("manor")
        .filter(pk=message.pk)
        .first()
    )

    if not message:
        raise MessageNotFoundError()

    if not message.has_attachments:
        raise NoAttachmentError()

    # Check claim status AFTER acquiring lock
    if message.is_claimed:
        raise AttachmentAlreadyClaimedError()

    manor = Manor.objects.select_for_update().get(pk=message.manor_id)
    attachments = message.attachments
    claimed_summary = {}

    # 发放资源
    resources = attachments.get("resources", {})
    claimed_resources = grant_resources(
        manor,
        resources,
        note=f"邮件附件：{message.title}",
        reason=ResourceEvent.Reason.ADMIN_ADJUST,
    )
    claimed_summary.update(claimed_resources)

    # 发放道具
    items = attachments.get("items", {})
    claimed_items: Dict[str, int] = {}
    if items:
        # 批量预加载物品模板，避免N+1查询
        item_keys = list(items.keys())
        item_templates_map = {
            tpl.key: tpl for tpl in ItemTemplate.objects.filter(key__in=item_keys)
        }

        for item_key, quantity in items.items():
            if quantity <= 0:
                continue

            # 从预加载的字典中查找物品模板
            item_template = item_templates_map.get(item_key)
            if not item_template:
                continue

            # 获取或创建库存记录（明确指定存储位置为仓库）
            # Use select_for_update for get_or_create to prevent race conditions
            # IMPORTANT: Must explicitly specify manor in get_or_create lookup to avoid NULL manor_id
            inventory_item, created = (
                InventoryItem.objects.select_for_update()
                .get_or_create(
                    manor=manor,
                    template=item_template,
                    storage_location=InventoryItem.StorageLocation.WAREHOUSE,
                    defaults={"quantity": 0},
                )
            )

            # Atomic quantity update using F() expression
            InventoryItem.objects.filter(pk=inventory_item.pk).update(
                quantity=F("quantity") + quantity,
                updated_at=timezone.now()
            )

            claimed_summary[f"item_{item_key}"] = quantity
            claimed_items[item_key] = quantity

    # Refresh manor to get updated resource values
    manor.refresh_from_db()

    # 标记为已领取
    message.is_claimed = True
    message.is_read = True
    attachments["claimed"] = {
        "resources": claimed_resources,
        "items": claimed_items,
    }
    message.attachments = attachments
    message.save(update_fields=["is_claimed", "is_read", "attachments"])

    return claimed_summary
