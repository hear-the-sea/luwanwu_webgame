from __future__ import annotations

import json

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import DatabaseError
from django.http import HttpResponse
from django.test import RequestFactory

from core.decorators import (
    _add_success_message,
    flash_unexpected_view_error,
    get_next_url,
    handle_game_errors,
    unexpected_error_response,
)
from core.exceptions import GameError


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


def test_flash_unexpected_view_error_database_error_degrades_with_message():
    request = RequestFactory().get("/some-page")
    setattr(request, "session", {})
    setattr(request, "_messages", FallbackStorage(request))

    flash_unexpected_view_error(
        request,
        DatabaseError("db down"),
        log_message="db failed",
    )

    messages = [str(message) for message in request._messages]
    assert any("操作失败，请稍后重试" in message for message in messages)


def test_flash_unexpected_view_error_programming_error_bubbles_up():
    request = RequestFactory().get("/some-page")
    setattr(request, "session", {})
    setattr(request, "_messages", FallbackStorage(request))

    with pytest.raises(RuntimeError, match="boom"):
        flash_unexpected_view_error(
            request,
            RuntimeError("boom"),
            log_message="runtime failed",
        )


def test_unexpected_error_response_database_error_returns_generic_json():
    request = RequestFactory().post("/some-page")

    response = unexpected_error_response(
        request,
        DatabaseError("db down"),
        is_ajax=True,
        redirect_url="/fallback",
        log_message="db failed",
    )

    assert response.status_code == 500
    assert json.loads(response.content)["error"] == "操作失败，请稍后重试"


def test_unexpected_error_response_programming_error_bubbles_up():
    request = RequestFactory().post("/some-page")

    with pytest.raises(RuntimeError, match="boom"):
        unexpected_error_response(
            request,
            RuntimeError("boom"),
            is_ajax=True,
            redirect_url="/fallback",
            log_message="runtime failed",
        )


def test_handle_game_errors_does_not_swallow_raw_value_error():
    @handle_game_errors(redirect_url="/fallback")
    def _view(_request):
        raise ValueError("legacy")

    request = RequestFactory().post("/some-page", HTTP_ACCEPT="application/json")
    with pytest.raises(ValueError, match="legacy"):
        _view(request)


def test_handle_game_errors_still_maps_game_error_to_400_json():
    @handle_game_errors(redirect_url="/fallback")
    def _view(_request):
        raise GameError("blocked")

    request = RequestFactory().post("/some-page", HTTP_ACCEPT="application/json")
    response = _view(request)

    assert response.status_code == 400
    assert json.loads(response.content)["error"] == "blocked"
