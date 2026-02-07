from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from django.core.cache import cache
from django.db import DatabaseError
from django.test import SimpleTestCase
from redis.exceptions import RedisError

from websocket.consumers import OnlineStatsConsumer


class _FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._ops: list[tuple] = []

    def incr(self, key: str):
        self._ops.append(("incr", key))
        return self

    def expire(self, key: str, ttl: int):
        self._ops.append(("expire", key, ttl))
        return self

    def zadd(self, key: str, mapping: dict):
        self._ops.append(("zadd", key, mapping))
        return self

    def execute(self):
        for op in self._ops:
            if op[0] == "incr":
                self._redis.incr(op[1])
            elif op[0] == "expire":
                continue
            elif op[0] == "zadd":
                _, key, mapping = op
                self._redis.zadd(key, mapping)
        return []


class _FakeRedis:
    def __init__(self):
        self._counters: dict[str, int] = {}
        self._zsets: dict[str, dict[int, float]] = {}
        self.eval_called: int = 0

    def pipeline(self):
        return _FakePipeline(self)

    def incr(self, key: str):
        self._counters[key] = int(self._counters.get(key, 0)) + 1
        return self._counters[key]

    def get(self, key: str):
        return str(self._counters.get(key)).encode("utf-8") if key in self._counters else None

    def expire(self, key: str, ttl: int):
        return True

    def zadd(self, key: str, mapping: dict[int, float]):
        self._zsets.setdefault(key, {}).update({int(k): float(v) for k, v in mapping.items()})
        return True

    def zremrangebyscore(self, key: str, _min: str, cutoff: float):
        z = self._zsets.get(key, {})
        before = len(z)
        self._zsets[key] = {k: v for k, v in z.items() if float(v) > float(cutoff)}
        return before - len(self._zsets[key])

    def zcard(self, key: str):
        return len(self._zsets.get(key, {}))

    def eval(self, _script: str, _numkeys: int, count_key: str, zset_key: str, user_id: str, ttl: str):
        self.eval_called += 1
        # Simple behavior: always remove user.
        self._counters.pop(count_key, None)
        self._zsets.get(zset_key, {}).pop(int(user_id), None)
        return 0


class OnlineStatsConsumerInternalTests(SimpleTestCase):
    def _build_consumer(self) -> OnlineStatsConsumer:
        consumer = OnlineStatsConsumer()
        consumer.channel_name = "test-channel"
        consumer.channel_layer = AsyncMock()
        consumer.send_json = AsyncMock()
        consumer.accept = AsyncMock()
        consumer.close = AsyncMock()
        return consumer

    def test_broadcast_debounce_skips_when_gate_is_closed(self):
        consumer = self._build_consumer()
        consumer.BROADCAST_DEBOUNCE_SECONDS = 1
        consumer.channel_layer.group_send = AsyncMock()

        # Simulate debounce gate closed.
        original_add = cache.add
        cache.add = lambda *_a, **_k: False
        try:
            asyncio.run(consumer._broadcast_stats_best_effort({"online_count": 1}))
        finally:
            cache.add = original_add

        consumer.channel_layer.group_send.assert_not_awaited()

    def test_broadcast_debounce_falls_back_if_cache_errors(self):
        consumer = self._build_consumer()
        consumer.BROADCAST_DEBOUNCE_SECONDS = 1
        consumer.channel_layer.group_send = AsyncMock()

        original_add = cache.add
        cache.add = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cache down"))
        try:
            asyncio.run(consumer._broadcast_stats_best_effort({"online_count": 1}))
        finally:
            cache.add = original_add

        consumer.channel_layer.group_send.assert_awaited_once()

    def test_get_online_count_sync_caches_and_cleans_up(self):
        consumer = self._build_consumer()
        fake = _FakeRedis()
        consumer._get_redis = lambda: fake

        now_ts = time.time()
        fake.zadd(consumer.ONLINE_USERS_KEY, {1: now_ts})
        fake.zadd(consumer.ONLINE_USERS_KEY, {2: now_ts - consumer.ONLINE_USERS_TTL - 10})

        cache.delete(consumer.ONLINE_COUNT_CACHE_KEY)
        count = consumer._get_online_count_sync()
        assert count == 1

        # Cache hit path
        assert consumer._get_online_count_sync() == 1

    def test_cleanup_expired_users_sync_handles_redis_error(self):
        consumer = self._build_consumer()

        class _BrokenRedis(_FakeRedis):
            def zremrangebyscore(self, key: str, _min: str, cutoff: float):
                raise RedisError("down")

        consumer._get_redis = lambda: _BrokenRedis()
        assert consumer._cleanup_expired_users_sync(time.time()) == 0

    def test_get_stats_handles_total_users_database_error(self):
        consumer = self._build_consumer()
        consumer._get_online_count_sync = lambda: 2
        consumer.get_total_users = AsyncMock(side_effect=DatabaseError("boom"))

        stats = asyncio.run(consumer.get_stats())
        assert stats["online_count"] == 2
        assert stats["total_count"] == 0


@pytest.mark.django_db
def test_get_total_users_uses_cache(django_user_model):
    consumer = OnlineStatsConsumer()

    django_user_model.objects.create_user(username="total_users_1", password="pass")
    django_user_model.objects.create_user(username="staff", password="pass", is_staff=True)

    cache.delete(consumer.TOTAL_COUNT_CACHE_KEY)
    # Call the underlying sync implementation to avoid SQLite/thread
    # locking issues (the async wrapper executes in a separate thread).
    first = consumer.get_total_users.__wrapped__(consumer)
    assert first == 1

    django_user_model.objects.filter(username="total_users_1").delete()
    second = consumer.get_total_users.__wrapped__(consumer)
    assert second == 1
