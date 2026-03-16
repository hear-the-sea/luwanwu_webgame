from __future__ import annotations

import json

from redis.exceptions import RedisError

from websocket.consumers import WorldChatConsumer
from websocket.consumers.world_chat import WorldChatInfrastructureError


class _FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._ops: list[tuple] = []

    def lpush(self, key: str, value: str):
        self._ops.append(("lpush", key, value))
        return self

    def ltrim(self, key: str, start: int, end: int):
        self._ops.append(("ltrim", key, start, end))
        return self

    def expire(self, key: str, ttl: int):
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self):
        for op in self._ops:
            name = op[0]
            if name == "lpush":
                _, key, value = op
                self._redis.lpush(key, value)
            elif name == "ltrim":
                _, key, start, end = op
                self._redis.ltrim(key, start, end)
            elif name == "expire":
                # TTL not simulated.
                continue
        return []


class _FakeRedis:
    def __init__(self):
        self._lists: dict[str, list[str]] = {}
        self._counters: dict[str, int] = {}

    def lrange(self, key: str, start: int, end: int):
        items = list(self._lists.get(key, []))
        if not items:
            return []

        if end < 0:
            end = len(items) + end
        end = min(end, len(items) - 1)
        if start < 0:
            start = 0
        if start > end:
            return []
        return items[start : end + 1]

    def lindex(self, key: str, index: int):
        items = self._lists.get(key, [])
        if not items:
            return None
        return items[index]

    def rpop(self, key: str):
        items = self._lists.get(key, [])
        if not items:
            return None
        return items.pop()

    def lpush(self, key: str, value: str):
        self._lists.setdefault(key, []).insert(0, value)
        return len(self._lists[key])

    def ltrim(self, key: str, start: int, end: int):
        items = self._lists.get(key, [])
        if not items:
            return True
        if end < 0:
            end = len(items) + end
        end = min(end, len(items) - 1)
        self._lists[key] = items[start : end + 1]
        return True

    def expire(self, key: str, ttl: int):
        return True

    def pipeline(self):
        return _FakePipeline(self)

    def incr(self, key: str):
        self._counters[key] = int(self._counters.get(key, 0)) + 1
        return self._counters[key]


def _build_consumer(fake_redis: _FakeRedis) -> WorldChatConsumer:
    consumer = WorldChatConsumer()
    consumer._get_redis = lambda: fake_redis
    consumer.user_id = 1
    consumer.display_name = "u"
    return consumer


def test_world_chat_get_history_sync_returns_empty_on_redis_error(monkeypatch):
    class _BrokenRedis(_FakeRedis):
        def lrange(self, key: str, start: int, end: int):  # noqa: D401
            raise RedisError("down")

    consumer = _build_consumer(_BrokenRedis())

    assert consumer._get_history_sync() == []
    assert consumer._history_degraded is True


def test_world_chat_get_history_sync_skips_old_and_malformed_entries(monkeypatch):
    fake = _FakeRedis()
    consumer = _build_consumer(fake)
    consumer.HISTORY_ON_CONNECT = 10
    consumer.HISTORY_LIMIT = 10
    consumer.HISTORY_MESSAGE_TTL_SECONDS = 900

    # Fix time so cutoff_ms is deterministic.
    monkeypatch.setattr("websocket.consumers.time.time", lambda: 2000.0)
    cutoff_ms = int((2000.0 - 900) * 1000)

    recent = {"type": "message", "ts": cutoff_ms + 1000, "text": "new"}
    old = {"type": "message", "ts": cutoff_ms - 1000, "text": "old"}

    fake._lists[consumer.HISTORY_KEY] = [
        json.dumps(recent).encode("utf-8"),
        b"{bad json",
        json.dumps(old),
    ]

    messages = consumer._get_history_sync()

    assert messages == [recent]
    assert consumer._history_degraded is False
    # The internal trim should drop malformed/old tail entries.
    assert len(fake._lists[consumer.HISTORY_KEY]) == 1


def test_world_chat_append_history_sync_pushes_and_trims(monkeypatch):
    fake = _FakeRedis()
    consumer = _build_consumer(fake)
    consumer.HISTORY_LIMIT = 2
    consumer.HISTORY_MESSAGE_TTL_SECONDS = 900
    monkeypatch.setattr("websocket.consumers.time.time", lambda: 2000.0)

    cutoff_ms = int((2000.0 - 900) * 1000)
    msg1 = {"type": "message", "ts": cutoff_ms + 1, "text": "a"}
    msg2 = {"type": "message", "ts": cutoff_ms + 2, "text": "b"}
    msg3 = {"type": "message", "ts": cutoff_ms + 3, "text": "c"}

    consumer._append_history_sync(msg1)
    consumer._append_history_sync(msg2)
    consumer._append_history_sync(msg3)

    assert len(fake._lists[consumer.HISTORY_KEY]) == 2
    # Newest first (LPUSH)
    assert json.loads(fake._lists[consumer.HISTORY_KEY][0])["text"] == "c"


def test_world_chat_rate_limit_sync_handles_no_user_id():
    consumer = _build_consumer(_FakeRedis())
    allowed, retry_after = consumer._rate_limit_sync(None)

    assert allowed is False
    assert retry_after == 3


def test_world_chat_rate_limit_sync_raises_when_redis_errors(monkeypatch):
    class _BrokenRedis(_FakeRedis):
        def incr(self, key: str):
            raise RedisError("down")

    consumer = _build_consumer(_BrokenRedis())
    try:
        consumer._rate_limit_sync(1)
    except WorldChatInfrastructureError as exc:
        assert "rate limit backend unavailable" in str(exc)
    else:  # pragma: no cover - defensive failure path
        raise AssertionError("expected WorldChatInfrastructureError when Redis is unavailable")


def test_world_chat_rate_limit_sync_rejects_after_limit(monkeypatch):
    fake = _FakeRedis()
    consumer = _build_consumer(fake)
    consumer.RATE_LIMIT_WINDOW_SECONDS = 8
    consumer.RATE_LIMIT_MAX_MESSAGES = 2
    monkeypatch.setattr("websocket.consumers.time.time", lambda: 2000.0)

    assert consumer._rate_limit_sync(1) == (True, None)
    assert consumer._rate_limit_sync(1) == (True, None)
    assert consumer._rate_limit_sync(1) == (False, 8)


def test_world_chat_next_id_sync_raises_on_redis_error(monkeypatch):
    class _BrokenRedis(_FakeRedis):
        def incr(self, key: str):
            raise RedisError("down")

    consumer = _build_consumer(_BrokenRedis())
    try:
        consumer._next_id_sync()
    except WorldChatInfrastructureError as exc:
        assert "id backend unavailable" in str(exc)
    else:  # pragma: no cover - defensive failure path
        raise AssertionError("expected WorldChatInfrastructureError when Redis is unavailable")


def test_world_chat_get_display_name_tolerates_cache_errors(monkeypatch):
    consumer = _build_consumer(_FakeRedis())

    def _raise_cache_error(*_args, **_kwargs):
        raise RuntimeError("cache down")

    monkeypatch.setattr("websocket.consumers.world_chat.cache.get", _raise_cache_error)
    monkeypatch.setattr("websocket.consumers.world_chat.cache.set", _raise_cache_error)

    class _FakeUser:
        def __init__(self):
            self.manor = type("_Manor", (), {"display_name": "测试庄园"})()
            self.username = "tester"

        def get_full_name(self):
            return ""

    class _FakeManager:
        def select_related(self, *_args, **_kwargs):
            return self

        def get(self, **_kwargs):
            return _FakeUser()

    class _FakeUserModel:
        DoesNotExist = type("DoesNotExist", (Exception,), {})
        objects = _FakeManager()

    monkeypatch.setattr("websocket.consumers.world_chat.User", _FakeUserModel)

    resolved = consumer._get_display_name.__wrapped__(consumer, 1)
    assert resolved == "测试庄园"
