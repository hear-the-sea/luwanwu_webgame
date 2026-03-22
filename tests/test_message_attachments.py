from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from django_redis.exceptions import ConnectionInterrupted

from gameplay.models import ItemTemplate, Message, ResourceEvent, ResourceType
from gameplay.services.manor.core import ensure_manor
from gameplay.services.utils import messages as message_service
from gameplay.services.utils.cache import CacheKeys
from gameplay.services.utils.messages import (
    bulk_create_messages,
    claim_message_attachments,
    cleanup_old_messages,
    delete_all_messages,
    delete_messages,
    unread_message_count,
)

User = get_user_model()


@pytest.mark.django_db
def test_claim_message_attachments_records_actual_and_stores_claimed():
    user = User.objects.create_user(username="mail_user", password="pass123")
    manor = ensure_manor(user)

    manor.silver_capacity = 100
    manor.silver = 95
    manor.save(update_fields=["silver_capacity", "silver"])

    ItemTemplate.objects.create(
        key="mail_test_item",
        name="测试道具",
    )

    message = Message.objects.create(
        manor=manor,
        kind=Message.Kind.REWARD,
        title="测试邮件",
        attachments={
            "resources": {"silver": 20},
            "items": {"mail_test_item": 3},
        },
    )

    claimed = claim_message_attachments(message)

    assert claimed["silver"] == 5
    assert claimed["item_mail_test_item"] == 3

    message.refresh_from_db()
    assert message.is_claimed is True
    assert message.is_read is True
    assert message.attachments["resources"]["silver"] == 20
    assert message.attachments["items"]["mail_test_item"] == 3
    assert message.attachments["claimed"]["resources"]["silver"] == 5
    assert message.attachments["claimed"]["items"]["mail_test_item"] == 3

    manor.refresh_from_db()
    assert manor.silver == 100

    event = ResourceEvent.objects.filter(
        manor=manor,
        resource_type=ResourceType.SILVER,
        reason=ResourceEvent.Reason.ADMIN_ADJUST,
        note="邮件附件：测试邮件",
    ).first()
    assert event is not None
    assert event.delta == 5

    assert message.get_attachment_summary() == "银两×5、1种道具"


@pytest.mark.django_db
def test_claim_message_attachments_invalidates_unread_cache():
    user = User.objects.create_user(username="mail_user_cache", password="pass123")
    manor = ensure_manor(user)
    ItemTemplate.objects.create(key="mail_test_item_cache", name="测试道具")
    message = Message.objects.create(
        manor=manor,
        kind=Message.Kind.REWARD,
        title="测试邮件缓存",
        attachments={"items": {"mail_test_item_cache": 1}},
    )

    cache_key = CacheKeys.unread_count(manor.id)
    cache.set(cache_key, 999, timeout=60)
    assert cache.get(cache_key) == 999

    claim_message_attachments(message)
    assert cache.get(cache_key) is None


@pytest.mark.django_db
def test_delete_messages_invalidates_unread_cache():
    user = User.objects.create_user(username="mail_user_del", password="pass123")
    manor = ensure_manor(user)
    msg = Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="t1")

    cache_key = CacheKeys.unread_count(manor.id)
    cache.set(cache_key, 999, timeout=60)
    delete_messages(manor, [msg.id])
    assert cache.get(cache_key) is None


@pytest.mark.django_db
def test_delete_all_messages_invalidates_unread_cache():
    user = User.objects.create_user(username="mail_user_del_all", password="pass123")
    manor = ensure_manor(user)
    Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="t2")
    Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="t3")

    cache_key = CacheKeys.unread_count(manor.id)
    cache.set(cache_key, 999, timeout=60)
    delete_all_messages(manor)
    assert cache.get(cache_key) is None


@pytest.mark.django_db
def test_cleanup_old_messages_invalidates_unread_cache_when_deleting():
    user = User.objects.create_user(username="mail_user_cleanup", password="pass123")
    manor = ensure_manor(user)
    message = Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="old_msg")
    Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - timedelta(days=30))

    cache_key = CacheKeys.unread_count(manor.id)
    cache.set(cache_key, 999, timeout=60)
    assert cache.get(cache_key) == 999

    cleanup_old_messages(manor)

    assert Message.objects.filter(pk=message.pk).exists() is False
    assert cache.get(cache_key) is None


@pytest.mark.django_db
def test_unread_message_count_tolerates_cache_errors(monkeypatch):
    user = User.objects.create_user(username="mail_user_cache_fail", password="pass123")
    manor = ensure_manor(user)
    Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="cache fail msg")

    monkeypatch.setattr(
        "gameplay.services.utils.messages.cache.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache get failed")),
    )
    monkeypatch.setattr(
        "gameplay.services.utils.messages.cache.set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache set failed")),
    )

    assert unread_message_count(manor) == 1


@pytest.mark.django_db
def test_cleanup_old_messages_tolerates_cache_add_error(monkeypatch):
    user = User.objects.create_user(username="mail_user_cleanup_cache_fail", password="pass123")
    manor = ensure_manor(user)
    message = Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="old_msg_cache_fail")
    Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - timedelta(days=30))

    monkeypatch.setattr(
        "gameplay.services.utils.messages.cache.add",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache add failed")),
    )
    message_service._LOCAL_CLEANUP_FALLBACK.clear()

    cleanup_old_messages(manor)
    assert Message.objects.filter(pk=message.pk).exists() is False


@pytest.mark.django_db
def test_cleanup_old_messages_cache_add_error_uses_local_fallback_gate(monkeypatch):
    user = User.objects.create_user(username="mail_user_cleanup_gate", password="pass123")
    manor = ensure_manor(user)

    first_message = Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="old_msg_first")
    Message.objects.filter(pk=first_message.pk).update(created_at=timezone.now() - timedelta(days=30))

    monkeypatch.setattr(
        "gameplay.services.utils.messages.cache.add",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache add failed")),
    )
    message_service._LOCAL_CLEANUP_FALLBACK.clear()

    cleanup_old_messages(manor)
    assert Message.objects.filter(pk=first_message.pk).exists() is False

    second_message = Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="old_msg_second")
    Message.objects.filter(pk=second_message.pk).update(created_at=timezone.now() - timedelta(days=30))

    # 第二次应被本地节流门禁拦截，避免缓存故障时每次请求都触发清理扫描
    cleanup_old_messages(manor)
    assert Message.objects.filter(pk=second_message.pk).exists() is True


@pytest.mark.django_db
def test_unread_message_count_runtime_marker_bubbles_up(monkeypatch):
    user = User.objects.create_user(username="mail_user_cache_runtime", password="pass123")
    manor = ensure_manor(user)
    Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="cache runtime msg")

    monkeypatch.setattr(
        "gameplay.services.utils.messages.cache.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache get failed")),
    )

    with pytest.raises(RuntimeError, match="cache get failed"):
        unread_message_count(manor)


@pytest.mark.django_db
def test_unread_message_count_cache_set_runtime_marker_bubbles_up(monkeypatch):
    user = User.objects.create_user(username="mail_user_cache_set_runtime", password="pass123")
    manor = ensure_manor(user)
    Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="cache set runtime msg")

    monkeypatch.setattr("gameplay.services.utils.messages.cache.get", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "gameplay.services.utils.messages.cache.set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache set failed")),
    )

    with pytest.raises(RuntimeError, match="cache set failed"):
        unread_message_count(manor)


@pytest.mark.django_db
def test_delete_messages_cache_delete_runtime_marker_bubbles_up(monkeypatch):
    user = User.objects.create_user(username="mail_user_delete_runtime", password="pass123")
    manor = ensure_manor(user)
    message = Message.objects.create(manor=manor, kind=Message.Kind.SYSTEM, title="delete runtime msg")

    monkeypatch.setattr(
        "gameplay.services.utils.messages.cache.delete",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache delete failed")),
    )

    with pytest.raises(RuntimeError, match="cache delete failed"):
        delete_messages(manor, [message.id])

    assert Message.objects.filter(pk=message.pk).exists() is False


@pytest.mark.django_db
def test_bulk_create_messages_cache_delete_many_runtime_marker_bubbles_up(monkeypatch):
    user = User.objects.create_user(username="mail_user_bulk_runtime", password="pass123")
    manor = ensure_manor(user)

    monkeypatch.setattr(
        "gameplay.services.utils.messages.cache.delete_many",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache delete_many failed")),
    )

    with pytest.raises(RuntimeError, match="cache delete_many failed"):
        bulk_create_messages(
            [
                {"manor": manor, "kind": Message.Kind.SYSTEM, "title": "bulk runtime msg 1"},
                {"manor": manor, "kind": Message.Kind.SYSTEM, "title": "bulk runtime msg 2"},
            ]
        )

    assert Message.objects.filter(manor=manor, title__startswith="bulk runtime msg").count() == 2


def test_local_cleanup_fallback_evicts_oldest_when_oversized(monkeypatch):
    message_service._LOCAL_CLEANUP_FALLBACK.clear()
    monkeypatch.setattr(message_service, "_LOCAL_CLEANUP_FALLBACK_MAX_SIZE", 3)
    monkeypatch.setattr(message_service, "_LOCAL_CLEANUP_FALLBACK_EVICT_COUNT", 2)
    monkeypatch.setattr(message_service.time, "monotonic", lambda: 100.0)

    message_service._LOCAL_CLEANUP_FALLBACK.update(
        {
            1: 90.0,
            2: 91.0,
            3: 92.0,
            4: 93.0,
        }
    )

    allowed = message_service._allow_cleanup_via_local_fallback(5, interval_seconds=120)
    assert allowed is True
    assert 5 in message_service._LOCAL_CLEANUP_FALLBACK
    assert 1 not in message_service._LOCAL_CLEANUP_FALLBACK
    assert len(message_service._LOCAL_CLEANUP_FALLBACK) <= message_service._LOCAL_CLEANUP_FALLBACK_MAX_SIZE


def test_local_cleanup_fallback_evicts_enough_to_respect_max_size(monkeypatch):
    message_service._LOCAL_CLEANUP_FALLBACK.clear()
    monkeypatch.setattr(message_service, "_LOCAL_CLEANUP_FALLBACK_MAX_SIZE", 3)
    monkeypatch.setattr(message_service, "_LOCAL_CLEANUP_FALLBACK_EVICT_COUNT", 1)
    monkeypatch.setattr(message_service.time, "monotonic", lambda: 100.0)

    message_service._LOCAL_CLEANUP_FALLBACK.update(
        {
            1: 90.0,
            2: 91.0,
            3: 92.0,
            4: 93.0,
            5: 94.0,
        }
    )

    allowed = message_service._allow_cleanup_via_local_fallback(6, interval_seconds=120)
    assert allowed is True
    assert len(message_service._LOCAL_CLEANUP_FALLBACK) <= message_service._LOCAL_CLEANUP_FALLBACK_MAX_SIZE
