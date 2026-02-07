import pytest
from django.http import JsonResponse
from django.test import RequestFactory

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
