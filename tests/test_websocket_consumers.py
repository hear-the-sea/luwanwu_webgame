from __future__ import annotations

import asyncio
import time
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
        consumer._ensure_valid_session = AsyncMock(return_value=True)

        asyncio.run(consumer.connect())

        assert consumer.group_name == "user_7"
        consumer.channel_layer.group_add.assert_awaited_once_with("user_7", "chan")
        consumer.accept.assert_awaited_once()
        consumer.close.assert_not_awaited()

    def test_connect_rejects_stale_single_session(self):
        class _User:
            id = 7
            is_authenticated = True

        consumer = NotificationConsumer()
        consumer.scope = {"user": _User(), "path": "/ws/", "client": ("127.0.0.1", 1234)}
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()
        consumer.channel_layer = AsyncMock()
        consumer._ensure_valid_session = AsyncMock(return_value=False)

        asyncio.run(consumer.connect())

        consumer.close.assert_awaited_once_with()
        consumer.accept.assert_not_awaited()

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
    class _PresenceRedis:
        def __init__(self):
            self._zsets: dict[str, dict[str, float]] = {}

        def zadd(self, key: str, mapping: dict[object, float]):
            zset = self._zsets.setdefault(key, {})
            for member, score in mapping.items():
                zset[str(member)] = float(score)
            return len(mapping)

        def expire(self, *_args, **_kwargs):
            return True

        def zcard(self, key: str):
            return len(self._zsets.get(key, {}))

        def zremrangebyscore(self, key: str, min_score, max_score):
            zset = self._zsets.setdefault(key, {})
            lower = float("-inf") if min_score == "-inf" else float(min_score)
            upper = float(max_score)
            removed = [member for member, score in zset.items() if lower <= score <= upper]
            for member in removed:
                zset.pop(member, None)
            return len(removed)

        def zunionstore(self, dest: str, keys, aggregate=None):
            del aggregate
            union: dict[str, float] = {}
            for key in keys:
                for member, score in self._zsets.get(key, {}).items():
                    union[member] = max(union.get(member, float("-inf")), float(score))
            self._zsets[dest] = union
            return len(union)

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
        consumer._ensure_valid_session = AsyncMock(return_value=True)

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

    def test_connect_rejects_stale_single_session(self):
        class _User:
            id = 11
            is_authenticated = True
            is_staff = False
            is_superuser = False

        consumer = self._build_consumer()
        consumer.scope = {"user": _User(), "path": "/ws/", "client": ("127.0.0.1", 1234)}
        consumer._ensure_valid_session = AsyncMock(return_value=False)

        asyncio.run(consumer.connect())

        consumer.close.assert_awaited_once_with()
        consumer.accept.assert_not_awaited()

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

        calls = {"zcard": 0, "zunionstore": 0}
        redis = self._PresenceRedis()
        now = time.time()
        redis.zadd("online_users_http_zset", {"1": now, "2": now})
        redis.zadd("online_users_ws_zset", {"2": now + 1, "3": now + 1})

        original_zcard = redis.zcard
        original_zunionstore = redis.zunionstore

        def _zcard(*args, **kwargs):
            calls["zcard"] += 1
            return original_zcard(*args, **kwargs)

        def _zunionstore(*args, **kwargs):
            calls["zunionstore"] += 1
            return original_zunionstore(*args, **kwargs)

        redis.zcard = _zcard  # type: ignore[method-assign]
        redis.zunionstore = _zunionstore  # type: ignore[method-assign]

        consumer._get_redis = lambda: redis  # type: ignore[method-assign]

        # First call should hit Redis.
        assert consumer._get_online_count_sync() == 3
        # Second call should hit cache.
        assert consumer._get_online_count_sync() == 3
        assert calls["zcard"] == 1
        assert calls["zunionstore"] == 1

    def test_remove_online_connection_keeps_recent_http_presence_counted(self):
        consumer = OnlineStatsConsumer()
        cache.delete(consumer.ONLINE_COUNT_CACHE_KEY)
        redis = self._PresenceRedis()
        user_id = 7
        now = time.time()
        redis.zadd("online_users_http_zset", {str(user_id): now})
        redis.zadd("online_users_ws_zset", {str(user_id): now + 1})

        class _RedisWithScript(self._PresenceRedis):
            def __init__(self, backing):
                self._zsets = backing._zsets
                self._counters = {f"{consumer.ONLINE_USER_CONN_COUNT_KEY_PREFIX}{user_id}": 1}

            def script_load(self, *_args, **_kwargs):
                return "sha"

            def evalsha(self, *_args, **_kwargs):
                self._zsets["online_users_ws_zset"].pop(str(user_id), None)
                self._counters.pop(f"{consumer.ONLINE_USER_CONN_COUNT_KEY_PREFIX}{user_id}", None)
                return 0

        redis_with_script = _RedisWithScript(redis)
        consumer._get_redis = lambda: redis_with_script  # type: ignore[method-assign]

        assert consumer._remove_online_connection_sync(user_id) == 0
        assert consumer._get_online_count_sync() == 1

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
