from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import DatabaseError
from django.test import RequestFactory
from django_redis.exceptions import ConnectionInterrupted

from core.middleware.online_presence import OnlinePresenceMiddleware
from gameplay.context_processors import notifications
from gameplay.services.manor.core import ensure_manor

pytestmark = pytest.mark.django_db


class _FakeRedis:
    def __init__(self):
        self._zsets: dict[str, dict[int, float]] = {}

    def zadd(self, key: str, mapping: dict[int, float]):
        self._zsets.setdefault(key, {}).update({int(member): float(score) for member, score in mapping.items()})
        return True

    def expire(self, key: str, timeout: int):
        return True

    def zremrangebyscore(self, key: str, _min: str, cutoff: float):
        zset = self._zsets.get(key, {})
        before = len(zset)
        self._zsets[key] = {member: score for member, score in zset.items() if float(score) > float(cutoff)}
        return before - len(self._zsets[key])

    def zcard(self, key: str):
        return len(self._zsets.get(key, {}))

    def zunionstore(self, dest: str, keys, aggregate=None):
        del aggregate
        union: dict[int, float] = {}
        for key in keys:
            for member, score in self._zsets.get(key, {}).items():
                union[int(member)] = max(union.get(int(member), float("-inf")), float(score))
        self._zsets[dest] = union
        return len(union)


def test_notifications_anonymous_tolerates_explicit_cache_and_redis_infrastructure_failures(monkeypatch):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    monkeypatch.setattr(
        "gameplay.selectors.stats.cache.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache read failed")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.cache.set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache write failed")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.get_redis_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("redis down")),
    )

    context = notifications(request)
    assert context["message_unread_count"] == 0
    assert context["online_user_count"] >= 0
    assert context["total_user_count"] >= 0


def test_notifications_anonymous_runtime_marker_cache_error_bubbles_up(monkeypatch):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    monkeypatch.setattr(
        "gameplay.selectors.stats.cache.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache read failed")),
    )

    with pytest.raises(RuntimeError, match="cache read failed"):
        notifications(request)


def test_notifications_anonymous_runtime_marker_cache_set_error_bubbles_up(monkeypatch):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    def fake_cache_get(key, default=None):
        if key in {"stats:total_users_count", "stats:online_users_count"}:
            return None
        return default

    monkeypatch.setattr("gameplay.selectors.stats.cache.get", fake_cache_get)
    monkeypatch.setattr(
        "gameplay.selectors.stats.cache.set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache write failed")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.User.objects.filter",
        lambda **_kwargs: type("FakeQuerySet", (), {"count": lambda self: 7})(),
    )
    monkeypatch.setattr("gameplay.selectors.stats._load_online_user_count_from_redis", lambda: 3)

    with pytest.raises(RuntimeError, match="cache write failed"):
        notifications(request)


def test_notifications_anonymous_handles_corrupted_cached_online_value(monkeypatch):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    def fake_cache_get(key, default=None):
        if key == "stats:total_users_count":
            return 7
        if key == "stats:online_users_count":
            return "invalid-int"
        return default

    monkeypatch.setattr("gameplay.selectors.stats.cache.get", fake_cache_get)

    context = notifications(request)
    assert context["total_user_count"] == 7
    assert context["online_user_count"] == 0


def test_notifications_authenticated_http_touch_refreshes_online_count(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_touch_user", password="pass")
    request = RequestFactory().get("/")
    request.user = user

    fake_redis = _FakeRedis()
    monkeypatch.setattr("gameplay.selectors.stats.get_redis_connection", lambda *_args, **_kwargs: fake_redis)
    monkeypatch.setattr(
        "gameplay.services.online_presence.get_redis_connection_if_supported",
        lambda *_args, **_kwargs: fake_redis,
    )
    monkeypatch.setattr("gameplay.context_processors._populate_authenticated_context", lambda *_args, **_kwargs: None)

    cache.set("stats:online_users_count", 0, timeout=60)
    OnlinePresenceMiddleware(lambda _request: None)(request)

    context = notifications(request)

    assert context["online_user_count"] == 1


def test_online_presence_middleware_tolerates_connection_interrupted(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_touch_fail_user", password="pass")
    request = RequestFactory().get("/")
    request.user = user

    monkeypatch.setattr("gameplay.services.online_presence.cache.add", lambda *_args, **_kwargs: True)
    deleted_keys: list[str] = []
    monkeypatch.setattr("gameplay.services.online_presence.cache.delete", lambda key: deleted_keys.append(key))

    class _BrokenRedis:
        def zadd(self, *_args, **_kwargs):
            raise ConnectionInterrupted("redis down")

    monkeypatch.setattr("gameplay.services.online_presence.get_redis_connection_if_supported", lambda: _BrokenRedis())

    OnlinePresenceMiddleware(lambda _request: None)(request)

    assert any(key.startswith("stats:online_users:touch:") for key in deleted_keys)


def test_online_presence_middleware_runtime_marker_redis_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_touch_runtime_user", password="pass")
    request = RequestFactory().get("/")
    request.user = user

    monkeypatch.setattr("gameplay.services.online_presence.cache.add", lambda *_args, **_kwargs: True)
    deleted_keys: list[str] = []
    monkeypatch.setattr("gameplay.services.online_presence.cache.delete", lambda key: deleted_keys.append(key))

    class _BrokenRedis:
        def zadd(self, *_args, **_kwargs):
            raise RuntimeError("redis down")

    monkeypatch.setattr("gameplay.services.online_presence.get_redis_connection_if_supported", lambda: _BrokenRedis())

    with pytest.raises(RuntimeError, match="redis down"):
        OnlinePresenceMiddleware(lambda _request: None)(request)

    assert any(key.startswith("stats:online_users:touch:") for key in deleted_keys)


def test_online_presence_middleware_cache_delete_programming_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_touch_delete_programming_user", password="pass")
    request = RequestFactory().get("/")
    request.user = user

    monkeypatch.setattr("gameplay.services.online_presence.cache.add", lambda *_args, **_kwargs: True)

    class _BrokenRedis:
        def zadd(self, *_args, **_kwargs):
            raise ConnectionInterrupted("redis down")

    monkeypatch.setattr("gameplay.services.online_presence.get_redis_connection_if_supported", lambda: _BrokenRedis())
    monkeypatch.setattr(
        "gameplay.services.online_presence.cache.delete",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken presence cache delete contract")),
    )

    with pytest.raises(AssertionError, match="broken presence cache delete contract"):
        OnlinePresenceMiddleware(lambda _request: None)(request)


def test_notifications_authenticated_falls_back_when_sidebar_cache_payload_invalid(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_user", password="pass")
    manor = ensure_manor(user)
    request = RequestFactory().get("/")
    request.user = user

    def fake_cache_get(key, default=None):
        if key == "stats:total_users_count":
            return 5
        if key == "stats:online_users_count":
            return 2
        if key == f"sidebar:rank:{manor.id}":
            return None
        return default

    monkeypatch.setattr("gameplay.selectors.stats.cache.get", fake_cache_get)
    monkeypatch.setattr("gameplay.selectors.stats.cache.set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("gameplay.selectors.sidebar.cache.get", fake_cache_get)
    monkeypatch.setattr("gameplay.selectors.sidebar.cache.set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("gameplay.context_processors.unread_message_count", lambda _manor: 4)
    monkeypatch.setattr("gameplay.services.ranking.get_player_rank", lambda _manor: 9)

    context = notifications(request)
    assert context["message_unread_count"] == 4
    assert context["sidebar_rank"] == 9


def test_notifications_authenticated_partial_sidebar_failures_do_not_hide_other_sections(
    monkeypatch, django_user_model
):
    user = django_user_model.objects.create_user(username="ctx_partial_user", password="pass")
    request = RequestFactory().get("/")
    request.user = user

    def fake_cache_get(key, default=None):
        if key == "stats:total_users_count":
            return 5
        if key == "stats:online_users_count":
            return 2
        return default

    monkeypatch.setattr("gameplay.selectors.stats.cache.get", fake_cache_get)
    monkeypatch.setattr("gameplay.selectors.stats.cache.set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("gameplay.selectors.sidebar.cache.get", fake_cache_get)
    monkeypatch.setattr("gameplay.selectors.sidebar.cache.set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "gameplay.context_processors.unread_message_count",
        lambda _manor: (_ for _ in ()).throw(DatabaseError("message db boom")),
    )
    monkeypatch.setattr(
        "gameplay.services.raid.get_protection_status",
        lambda _manor: {"is_protected": True, "type_display": "护盾", "remaining_display": "10m"},
    )
    monkeypatch.setattr(
        "gameplay.services.ranking.get_player_rank",
        lambda _manor: (_ for _ in ()).throw(DatabaseError("rank db boom")),
    )

    context = notifications(request)
    assert context["message_unread_count"] == 0
    assert context["header_protection_status"] == {
        "is_protected": True,
        "type_display": "护盾",
        "remaining_display": "10m",
    }
    assert "sidebar_rank" not in context


def test_notifications_authenticated_programming_error_in_unread_count_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_unread_runtime_user", password="pass")
    request = RequestFactory().get("/")
    request.user = user

    monkeypatch.setattr("gameplay.selectors.stats.cache.get", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "gameplay.context_processors.unread_message_count",
        lambda _manor: (_ for _ in ()).throw(RuntimeError("message boom")),
    )

    with pytest.raises(RuntimeError, match="message boom"):
        notifications(request)


def test_notifications_authenticated_programming_error_in_rank_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_rank_runtime_user", password="pass")
    request = RequestFactory().get("/")
    request.user = user

    def fake_cache_get(key, default=None):
        if key in {"stats:total_users_count", "stats:online_users_count"}:
            return 0
        if key.startswith("sidebar:rank:"):
            return None
        return default

    monkeypatch.setattr("gameplay.selectors.stats.cache.get", fake_cache_get)
    monkeypatch.setattr("gameplay.selectors.sidebar.cache.get", fake_cache_get)
    monkeypatch.setattr("gameplay.context_processors.unread_message_count", lambda _manor: 1)
    monkeypatch.setattr(
        "gameplay.services.raid.get_protection_status",
        lambda _manor: {"is_protected": False, "type_display": "", "remaining_display": ""},
    )
    monkeypatch.setattr(
        "gameplay.services.ranking.get_player_rank",
        lambda _manor: (_ for _ in ()).throw(RuntimeError("rank boom")),
    )

    with pytest.raises(RuntimeError, match="rank boom"):
        notifications(request)


def test_notifications_authenticated_runtime_marker_sidebar_cache_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_rank_cache_runtime_user", password="pass")
    manor = ensure_manor(user)
    request = RequestFactory().get("/")
    request.user = user

    def fake_stats_cache_get(key, default=None):
        if key in {"stats:total_users_count", "stats:online_users_count"}:
            return 0
        return default

    monkeypatch.setattr("gameplay.selectors.stats.cache.get", fake_stats_cache_get)
    monkeypatch.setattr("gameplay.context_processors.unread_message_count", lambda _manor: 1)
    monkeypatch.setattr(
        "gameplay.services.raid.get_protection_status",
        lambda _manor: {"is_protected": False, "type_display": "", "remaining_display": ""},
    )
    monkeypatch.setattr(
        "gameplay.selectors.sidebar.cache.get",
        lambda key, default=None: (
            (_ for _ in ()).throw(RuntimeError("cache read failed")) if key == f"sidebar:rank:{manor.id}" else default
        ),
    )

    with pytest.raises(RuntimeError, match="cache read failed"):
        notifications(request)


def test_notifications_authenticated_runtime_marker_sidebar_cache_set_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_rank_cache_set_runtime_user", password="pass")
    manor = ensure_manor(user)
    request = RequestFactory().get("/")
    request.user = user

    def fake_stats_cache_get(key, default=None):
        if key in {"stats:total_users_count", "stats:online_users_count"}:
            return 0
        return default

    def fake_sidebar_cache_get(key, default=None):
        if key == f"sidebar:rank:{manor.id}":
            return None
        return default

    monkeypatch.setattr("gameplay.selectors.stats.cache.get", fake_stats_cache_get)
    monkeypatch.setattr("gameplay.context_processors.unread_message_count", lambda _manor: 1)
    monkeypatch.setattr(
        "gameplay.services.raid.get_protection_status",
        lambda _manor: {"is_protected": False, "type_display": "", "remaining_display": ""},
    )
    monkeypatch.setattr("gameplay.selectors.sidebar.cache.get", fake_sidebar_cache_get)
    monkeypatch.setattr(
        "gameplay.selectors.sidebar.cache.set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache write failed")),
    )
    monkeypatch.setattr("gameplay.services.ranking.get_player_rank", lambda _manor: 9)

    with pytest.raises(RuntimeError, match="cache write failed"):
        notifications(request)


def test_notifications_non_home_pages_skip_home_sidebar_queries(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="ctx_non_home_user", password="pass")
    request = RequestFactory().get("/manor/warehouse/")
    request.user = user

    monkeypatch.setattr(
        "gameplay.selectors.stats.get_redis_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("redis down")),
    )
    monkeypatch.setattr("gameplay.context_processors.unread_message_count", lambda _manor: 2)
    monkeypatch.setattr(
        "gameplay.services.ranking.get_player_rank",
        lambda _manor: (_ for _ in ()).throw(AssertionError("sidebar rank should not be loaded")),
    )

    context = notifications(request)
    assert context["message_unread_count"] == 2
    assert "sidebar_rank" not in context
    assert "sidebar_prestige" not in context


def test_notifications_ajax_requests_skip_global_stats_queries(monkeypatch):
    request = RequestFactory().get("/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    request.user = AnonymousUser()

    monkeypatch.setattr(
        "gameplay.selectors.stats.load_total_user_count",
        lambda: (_ for _ in ()).throw(AssertionError("global stats should be skipped for ajax")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.load_online_user_count",
        lambda: (_ for _ in ()).throw(AssertionError("online stats should be skipped for ajax")),
    )

    context = notifications(request)

    assert context["total_user_count"] == 0
    assert context["online_user_count"] == 0


def test_notifications_total_user_count_uses_local_fallback_when_cache_reads_fail(monkeypatch):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    gameplay_selectors_stats = __import__("gameplay.selectors.stats", fromlist=["load_total_user_count"])
    gameplay_selectors_stats._LOCAL_STATS_CACHE.clear()

    count_calls = {"count": 0}

    monkeypatch.setattr(
        "gameplay.selectors.stats.cache.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache read failed")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.cache.set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache write failed")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.User.objects.filter",
        lambda **_kwargs: type(
            "FakeQuerySet",
            (),
            {"count": lambda self: count_calls.__setitem__("count", count_calls["count"] + 1) or 11},
        )(),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.load_online_user_count",
        lambda: 0,
    )

    first = notifications(request)
    second = notifications(request)

    assert first["total_user_count"] == 11
    assert second["total_user_count"] == 11
    assert count_calls["count"] == 1


def test_notifications_online_user_count_uses_local_fallback_when_cache_and_redis_fail(monkeypatch):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    gameplay_selectors_stats = __import__("gameplay.selectors.stats", fromlist=["load_online_user_count"])
    gameplay_selectors_stats._LOCAL_STATS_CACHE.clear()

    count_calls = {"count": 0}

    monkeypatch.setattr(
        "gameplay.selectors.stats.cache.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache read failed")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.cache.set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("cache write failed")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.get_redis_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("redis down")),
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats.load_total_user_count",
        lambda: 0,
    )
    monkeypatch.setattr(
        "gameplay.selectors.stats._load_online_user_count_from_db",
        lambda: count_calls.__setitem__("count", count_calls["count"] + 1) or 3,
    )

    first = notifications(request)
    second = notifications(request)

    assert first["online_user_count"] == 3
    assert second["online_user_count"] == 3
    assert count_calls["count"] == 1


def test_notifications_online_user_count_runtime_marker_redis_error_bubbles_up(monkeypatch):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    monkeypatch.setattr("gameplay.selectors.stats.load_total_user_count", lambda: 0)
    monkeypatch.setattr("gameplay.selectors.stats.cache.get", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "gameplay.selectors.stats.get_redis_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("redis down")),
    )

    with pytest.raises(RuntimeError, match="redis down"):
        notifications(request)
