from __future__ import annotations

import traceback

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from core.exceptions import GameError
from core.utils.view_error_mapping import classify_view_error, flash_view_error, json_error_response_for_exception


def _build_request():
    request = RequestFactory().get("/view-error")
    setattr(request, "session", {})
    setattr(request, "_messages", FallbackStorage(request))
    return request


def _raise_runtime():
    raise RuntimeError("boom")


def _reraised_by_flash(request):
    try:
        _raise_runtime()
    except RuntimeError as exc:
        flash_view_error(request, exc, log_message="runtime failed")


def _reraised_by_json():
    try:
        _raise_runtime()
    except RuntimeError as exc:
        json_error_response_for_exception(exc, log_message="runtime failed")


def test_flash_view_error_preserves_original_traceback():
    with pytest.raises(RuntimeError) as exc_info:
        _reraised_by_flash(_build_request())

    frames = traceback.extract_tb(exc_info.value.__traceback__)
    assert "_raise_original_exception" not in [frame.name for frame in frames]
    assert frames[-1].name == "_raise_runtime"


def test_json_error_response_for_exception_preserves_original_traceback():
    with pytest.raises(RuntimeError) as exc_info:
        _reraised_by_json()

    frames = traceback.extract_tb(exc_info.value.__traceback__)
    assert "_raise_original_exception" not in [frame.name for frame in frames]
    assert frames[-1].name == "_raise_runtime"


def test_classify_view_error_treats_value_error_as_unexpected_by_default():
    assert classify_view_error(ValueError("boom")) == "unexpected"


def test_classify_view_error_treats_runtime_marker_as_unexpected():
    assert classify_view_error(RuntimeError("database backend unavailable")) == "unexpected"


def test_classify_view_error_can_explicitly_allow_legacy_value_errors():
    assert classify_view_error(ValueError("boom"), known_exceptions=(GameError, ValueError)) == "known"


def test_classify_view_error_treats_game_error_as_known_by_default():
    assert classify_view_error(GameError("boom")) == "known"
