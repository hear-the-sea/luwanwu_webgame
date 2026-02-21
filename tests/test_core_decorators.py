from __future__ import annotations

from django.test import RequestFactory

from core.decorators import get_next_url


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
