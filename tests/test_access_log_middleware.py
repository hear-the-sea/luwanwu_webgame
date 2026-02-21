from __future__ import annotations

import logging

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from core.middleware.access_log import AccessLogMiddleware


def test_access_log_sanitizes_control_characters(caplog):
    request = RequestFactory().get("/safe")
    request.path = "/foo\nbar"
    request.id = "req\r\n123"

    middleware = AccessLogMiddleware(lambda _req: HttpResponse("ok"))
    with caplog.at_level(logging.INFO, logger="access"):
        response = middleware(request)

    assert response.status_code == 200
    record = caplog.records[-1]
    message = record.getMessage()
    assert "path=/foo bar" in message
    assert "request_id=req  123" in message
    assert "status=200" in message


def test_access_log_includes_exception_name_when_response_raises(caplog):
    request = RequestFactory().get("/oops")

    def _raise(_req):
        raise ValueError("boom")

    middleware = AccessLogMiddleware(_raise)
    with pytest.raises(ValueError):
        with caplog.at_level(logging.INFO, logger="access"):
            middleware(request)

    message = caplog.records[-1].getMessage()
    assert "status=500" in message
    assert "exc=ValueError" in message
