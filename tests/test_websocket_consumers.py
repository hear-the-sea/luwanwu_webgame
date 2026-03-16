from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from django.core.cache import cache
from django.test import SimpleTestCase
from redis.exceptions import RedisError

from websocket.consumers import NotificationConsumer, OnlineStatsConsumer


class NotificationConsumerTests(SimpleTestCase):
    def test_connect_rejects_unauthenticated(self):
        consumer = NotificationConsumer()
        consumer.scope = {"user": None, "path": "/ws/", "client": ("127.0.0.1", 1234)}
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()
        consumer.channel_layer = AsyncMock()

        asyncio.run(consumer.connect())

        consumer.close.assert_awaited_once()
        consumer.accept.assert_not_awaited()

    def test_connect_adds_group_for_authenticated_user(self):
        class _User:
            id = 7
            is_authenticated = True

        consumer = NotificationConsumer()
        consumer.scope = {"user": _User(), "path": "/ws/", "client": ("127.0.0.1", 1234)}
        consumer.channel_name = "chan"
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()
        consumer.channel_layer = AsyncMock()

        asyncio.run(consumer.connect())

        assert consumer.group_name == "user_7"
        consumer.channel_layer.group_add.assert_awaited_once_with("user_7", "chan")
        consumer.accept.assert_awaited_once()
        consumer.close.assert_not_awaited()

    def test_notify_message_filters_payload(self):
        consumer = NotificationConsumer()
        consumer.send_json = AsyncMock()

        event = {
            "payload": {
                "type": "info",
                "title": "t",
                "message": "m",
                "data": {"a": 1},
                "timestamp": 1,
                "extra": "drop",
            }
        }

        asyncio.run(consumer.notify_message(event))

        consumer.send_json.assert_awaited_once_with(
            {"type": "info", "title": "t", "message": "m", "data": {"a": 1}, "timestamp": 1}
        )


class OnlineStatsConsumerTests(SimpleTestCase):
    def _build_consumer(self) -> OnlineStatsConsumer:
        consumer = OnlineStatsConsumer()
        # Disable debouncing so assertions on group_send are deterministic.
        consumer.BROADCAST_DEBOUNCE_SECONDS = 0
        consumer.channel_name = "test-channel"
        consumer.channel_layer = AsyncMock()
        consumer.send_json = AsyncMock()
        consumer.accept = AsyncMock()
        consumer.close = AsyncMock()
        return consumer

    def test_connect_rejects_unauthenticated(self):
        consumer = self._build_consumer()
        consumer.scope = {"user": None, "path": "/ws/", "client": ("127.0.0.1", 1234)}

        asyncio.run(consumer.connect())

        consumer.close.assert_awaited_once()
        consumer.accept.assert_not_awaited()

    def test_connect_sends_stats_and_broadcasts(self):
        class _User:
            id = 11
            is_authenticated = True
            is_staff = False
            is_superuser = False

        consumer = self._build_consumer()
        consumer.scope = {"user": _User(), "path": "/ws/", "client": ("127.0.0.1", 1234)}

        async def _noop_heartbeat():
            return None

        consumer._heartbeat_loop = _noop_heartbeat
        consumer.add_online_connection = AsyncMock()
        consumer.get_stats = AsyncMock(return_value={"online_count": 1, "total_count": 2})

        asyncio.run(consumer.connect())

        consumer.channel_layer.group_add.assert_awaited_once_with(consumer.STATS_GROUP, consumer.channel_name)
        consumer.accept.assert_awaited_once()
        consumer.add_online_connection.assert_awaited_once_with(11)
        consumer.send_json.assert_awaited_once_with({"online_count": 1, "total_count": 2})
        consumer.channel_layer.group_send.assert_awaited_once()

    def test_disconnect_removes_connection_and_broadcasts(self):
        consumer = self._build_consumer()
        consumer.is_real_user = True
        consumer.user_id = 12
        consumer.remove_online_connection = AsyncMock()
        consumer.get_stats = AsyncMock(return_value={"online_count": 0, "total_count": 1})

        async def _run():
            consumer.heartbeat_task = asyncio.create_task(asyncio.sleep(3600))
            await consumer.disconnect(1000)

        asyncio.run(_run())

        consumer.remove_online_connection.assert_awaited_once_with(12)
        consumer.channel_layer.group_discard.assert_awaited_once_with(consumer.STATS_GROUP, consumer.channel_name)
        consumer.channel_layer.group_send.assert_awaited_once()

    def test_get_online_count_sync_uses_cache(self):
        consumer = OnlineStatsConsumer()
        cache.delete(consumer.ONLINE_COUNT_CACHE_KEY)

        calls = {"zcard": 0}

        class _Redis:
            def zcard(self, *_args, **_kwargs):
                calls["zcard"] += 1
                return 3

        consumer._get_redis = lambda: _Redis()  # type: ignore[method-assign]
        consumer._cleanup_expired_users_sync = lambda *_args, **_kwargs: 0  # type: ignore[method-assign]

        # First call should hit Redis.
        assert consumer._get_online_count_sync() == 3
        # Second call should hit cache.
        assert consumer._get_online_count_sync() == 3
        assert calls["zcard"] == 1

    def test_cleanup_expired_users_sync_handles_redis_error(self):
        consumer = OnlineStatsConsumer()

        class _Redis:
            def zremrangebyscore(self, *_args, **_kwargs):
                raise RedisError("down")

        consumer._get_redis = lambda: _Redis()  # type: ignore[method-assign]

        assert consumer._cleanup_expired_users_sync(1000.0) == 0

    def test_add_online_connection_sync_tolerates_cache_delete_failure(self):
        consumer = OnlineStatsConsumer()

        class _Redis:
            def pipeline(self):
                class _Pipeline:
                    def incr(self, *_args, **_kwargs):
                        return self

                    def expire(self, *_args, **_kwargs):
                        return self

                    def zadd(self, *_args, **_kwargs):
                        return self

                    def execute(self):
                        return []

                return _Pipeline()

        consumer._get_redis = lambda: _Redis()  # type: ignore[method-assign]
        original_delete = cache.delete
        cache.delete = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cache down"))
        try:
            consumer._add_online_connection_sync(7, 1000.0)
        finally:
            cache.delete = original_delete

    def test_remove_online_connection_sync_tolerates_cache_delete_failure(self):
        consumer = OnlineStatsConsumer()

        class _Redis:
            def script_load(self, *_args, **_kwargs):
                return "sha"

            def evalsha(self, *_args, **_kwargs):
                return 0

        consumer._get_redis = lambda: _Redis()  # type: ignore[method-assign]
        original_delete = cache.delete
        cache.delete = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cache down"))
        try:
            assert consumer._remove_online_connection_sync(7) == 0
        finally:
            cache.delete = original_delete
