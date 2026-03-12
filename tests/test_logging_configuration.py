from __future__ import annotations

from config.settings.logging_conf import LOGGING


def test_console_handler_uses_request_id_filter():
    console_handler = LOGGING["handlers"]["console"]

    assert "request_id" in LOGGING["filters"]
    assert "exclude_access" in LOGGING["filters"]
    assert console_handler["filters"] == ["request_id", "exclude_access"]
    assert "%(request_id)s" in LOGGING["formatters"]["verbose"]["format"]


def test_access_logger_uses_dedicated_handler_without_request_id_formatter():
    access_logger = LOGGING["loggers"]["access"]
    access_handler = LOGGING["handlers"]["access_console"]

    assert access_logger["handlers"] == ["access_console"]
    assert access_logger["propagate"] is True
    assert access_handler["formatter"] == "access"
    assert "%(request_id)s" not in LOGGING["formatters"]["access"]["format"]
