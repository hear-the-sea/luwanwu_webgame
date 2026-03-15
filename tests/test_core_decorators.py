from __future__ import annotations

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse
from django.test import RequestFactory

from core.decorators import _add_success_message, get_next_url


def test_get_next_url_rejects_unsafe_default_external_url():
    request = RequestFactory().get("/some-page")

    url = get_next_url(request, default="https://evil.example/phish")
    assert url == "/"


def test_get_next_url_accepts_safe_default_path():
    request = RequestFactory().get("/some-page")

    url = get_next_url(request, default="/manor/dashboard")
    assert url == "/manor/dashboard"


def test_get_next_url_supports_non_namespaced_default_route_name():
    request = RequestFactory().get("/some-page")

    url = get_next_url(request, default="home")
    assert url == "/"


def test_get_next_url_supports_non_namespaced_result_route_name():
    request = RequestFactory().get("/some-page")

    url = get_next_url(request, default="/fallback", result="home")
    assert url == "/"


def test_add_success_message_callable_programming_error_bubbles_up():
    request = RequestFactory().get("/some-page")
    setattr(request, "session", {})
    setattr(request, "_messages", FallbackStorage(request))

    with pytest.raises(RuntimeError, match="boom"):
        _add_success_message(
            request,
            lambda _result: (_ for _ in ()).throw(RuntimeError("boom")),
            HttpResponse("ok"),
        )
