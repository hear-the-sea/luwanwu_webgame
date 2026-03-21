from django.test import RequestFactory

from core.exceptions import GameError
from core.utils.validation import parse_json_object, safe_positive_int, safe_redirect_url, sanitize_error_message


def test_safe_positive_int_accepts_positive_values():
    assert safe_positive_int("12") == 12
    assert safe_positive_int(3) == 3


def test_safe_positive_int_rejects_non_positive_or_invalid_values():
    assert safe_positive_int(0) is None
    assert safe_positive_int(-1) is None
    assert safe_positive_int("abc") is None
    assert safe_positive_int(None) is None
    assert safe_positive_int("abc", default=7) == 7


def test_parse_json_object_requires_object_shape():
    assert parse_json_object(b'{"a": 1}') == {"a": 1}
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('["x"]') is None


def test_parse_json_object_handles_invalid_and_empty_payload():
    assert parse_json_object(b"\xff") is None
    assert parse_json_object(b"") is None
    assert parse_json_object(b"", empty_as_object=True) == {}


def test_safe_redirect_url_normalizes_encoded_fragment():
    request = RequestFactory().get("/manor/")
    assert safe_redirect_url(request, "/manor/%23building-77", "/manor/") == "/manor/#building-77"


def test_safe_redirect_url_normalizes_double_encoded_fragment():
    request = RequestFactory().get("/manor/")
    assert safe_redirect_url(request, "/manor/%2523building-77", "/manor/") == "/manor/#building-77"


def test_safe_redirect_url_rejects_external_url_after_decode():
    request = RequestFactory().get("/manor/")
    unsafe = "%2F%2Fevil.example/%23building-77"
    assert safe_redirect_url(request, unsafe, "/manor/") == "/manor/"


def test_safe_redirect_url_rejects_external_url_after_double_decode():
    request = RequestFactory().get("/manor/")
    unsafe = "%252F%252Fevil.example%252F%2523building-77"
    assert safe_redirect_url(request, unsafe, "/manor/") == "/manor/"


def test_sanitize_error_message_returns_business_message_for_game_error():
    assert sanitize_error_message(GameError("blocked")) == "blocked"


def test_sanitize_error_message_hides_value_error_message():
    assert sanitize_error_message(ValueError("leak")) == "操作失败，请稍后重试"
