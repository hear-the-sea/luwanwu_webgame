import pytest
from django.http import JsonResponse
from django.test import RequestFactory

from core.utils import rate_limit as rate_limit_module
from core.utils.rate_limit import rate_limit_json


@pytest.mark.django_db
def test_rate_limit_json_skips_get_by_default(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test",
        }
    }

    rf = RequestFactory()
    request = rf.get("/fake")

    call_count = {"n": 0}

    @rate_limit_json("t", limit=1, window_seconds=60)
    def view(req):
        call_count["n"] += 1
        return JsonResponse({"ok": True})

    view(request)
    view(request)
    assert call_count["n"] == 2


@pytest.mark.django_db
def test_rate_limit_json_can_include_get(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test2",
        }
    }

    rf = RequestFactory()
    request = rf.get("/fake")

    @rate_limit_json("t2", limit=1, window_seconds=60, include_safe_methods=True)
    def view(req):
        return JsonResponse({"ok": True})

    resp1 = view(request)
    resp2 = view(request)

    assert resp1.status_code == 200
    assert resp2.status_code == 429


@pytest.mark.django_db
def test_rate_limit_json_blank_key_func_falls_back(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test3",
        }
    }

    rf = RequestFactory()
    request = rf.post("/fake")

    @rate_limit_json("t3", limit=1, window_seconds=60, key_func=lambda _req: "   ")
    def view(req):
        return JsonResponse({"ok": True})

    resp1 = view(request)
    resp2 = view(request)
    assert resp1.status_code == 200
    assert resp2.status_code == 429


@pytest.mark.django_db
def test_rate_limit_json_key_func_error_falls_back(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test4",
        }
    }

    rf = RequestFactory()
    request = rf.post("/fake")

    def _bad_key(_request):
        raise RuntimeError("boom")

    @rate_limit_json("t4", limit=1, window_seconds=60, key_func=_bad_key)
    def view(req):
        return JsonResponse({"ok": True})

    resp1 = view(request)
    resp2 = view(request)
    assert resp1.status_code == 200
    assert resp2.status_code == 429


@pytest.mark.django_db
def test_rate_limit_json_hashes_long_or_unsafe_identifier(monkeypatch):
    captured: dict[str, str] = {}

    def fake_add(key, value, timeout=None):
        captured["key"] = key
        return True

    monkeypatch.setattr(rate_limit_module.cache, "add", fake_add)

    rf = RequestFactory()
    request = rf.post("/fake")

    @rate_limit_json("t5", limit=1, window_seconds=60, key_func=lambda _req: "中文\n" + ("x" * 400))
    def view(req):
        return JsonResponse({"ok": True})

    response = view(request)
    assert response.status_code == 200
    assert captured["key"].startswith("rl:t5:h:")
    assert len(captured["key"]) <= rate_limit_module._MEMCACHE_KEY_LIMIT


@pytest.mark.django_db
def test_rate_limit_json_hashes_when_scope_too_long(monkeypatch):
    captured: dict[str, str] = {}

    def fake_add(key, value, timeout=None):
        captured["key"] = key
        return True

    monkeypatch.setattr(rate_limit_module.cache, "add", fake_add)

    rf = RequestFactory()
    request = rf.post("/fake")
    scope = "s" * 400

    @rate_limit_json(scope, limit=1, window_seconds=60, key_func=lambda _req: "user:1")
    def view(req):
        return JsonResponse({"ok": True})

    response = view(request)
    assert response.status_code == 200
    assert ":h:" in captured["key"]
    assert len(captured["key"]) <= rate_limit_module._MEMCACHE_KEY_LIMIT


@pytest.mark.django_db
def test_rate_limit_json_programming_error_bubbles_up(monkeypatch):
    rf = RequestFactory()
    request = rf.post("/fake")

    monkeypatch.setattr(
        rate_limit_module.cache,
        "add",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken cache contract")),
    )

    @rate_limit_json("t6", limit=1, window_seconds=60)
    def view(req):
        return JsonResponse({"ok": True})

    with pytest.raises(AssertionError, match="broken cache contract"):
        view(request)


@pytest.mark.django_db
def test_rate_limit_json_runtime_marker_error_bubbles_up(monkeypatch):
    rf = RequestFactory()
    request = rf.post("/fake")

    monkeypatch.setattr(
        rate_limit_module.cache,
        "add",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cache down")),
    )

    @rate_limit_json("t7", limit=1, window_seconds=60)
    def view(req):
        return JsonResponse({"ok": True})

    with pytest.raises(RuntimeError, match="cache down"):
        view(request)
