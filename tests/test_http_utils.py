from django.test import RequestFactory

from core.utils import accepts_json, is_ajax_request, is_json_request


def test_is_ajax_request_checks_header_value():
    rf = RequestFactory()
    ajax_request = rf.get("/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    normal_request = rf.get("/")

    assert is_ajax_request(ajax_request) is True
    assert is_ajax_request(normal_request) is False


def test_accepts_json_checks_accept_header_case_insensitive():
    rf = RequestFactory()
    json_request = rf.get("/", HTTP_ACCEPT="Application/JSON, text/plain")
    html_request = rf.get("/", HTTP_ACCEPT="text/html")

    assert accepts_json(json_request) is True
    assert accepts_json(html_request) is False


def test_is_json_request_accepts_ajax_or_accept_header():
    rf = RequestFactory()
    accept_json_request = rf.get("/", HTTP_ACCEPT="application/json")
    ajax_request = rf.get("/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    normal_request = rf.get("/")

    assert is_json_request(accept_json_request) is True
    assert is_json_request(ajax_request) is True
    assert is_json_request(normal_request) is False
