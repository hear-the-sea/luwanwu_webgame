from django.test import RequestFactory

from core.decorators import expects_json, is_ajax_request


def test_core_decorators_is_ajax_request_uses_xml_http_request_header():
    rf = RequestFactory()
    ajax_request = rf.get("/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    normal_request = rf.get("/")

    assert is_ajax_request(ajax_request) is True
    assert is_ajax_request(normal_request) is False


def test_core_decorators_expects_json_is_case_insensitive():
    rf = RequestFactory()
    json_request = rf.get("/", HTTP_ACCEPT="Application/JSON")
    normal_request = rf.get("/", HTTP_ACCEPT="text/html")

    assert expects_json(json_request) is True
    assert expects_json(normal_request) is False
