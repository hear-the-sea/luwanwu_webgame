import json

from core.utils import json_error, json_success


def test_json_success_builds_standard_payload_with_status_and_extra():
    response = json_success(status=201, message="ok", item_id=12)
    assert response.status_code == 201
    payload = json.loads(response.content)
    assert payload["success"] is True
    assert payload["message"] == "ok"
    assert payload["item_id"] == 12


def test_json_error_builds_standard_payload_with_status_and_extra():
    response = json_error("bad request", status=422, code="INVALID_PARAM")
    assert response.status_code == 422
    payload = json.loads(response.content)
    assert payload["success"] is False
    assert payload["error"] == "bad request"
    assert payload["code"] == "INVALID_PARAM"


def test_json_error_can_include_legacy_message_field():
    response = json_error("bad request", status=400, include_message=True)
    payload = json.loads(response.content)
    assert payload["success"] is False
    assert payload["error"] == "bad request"
    assert payload["message"] == "bad request"


def test_json_error_allows_manual_message_override():
    response = json_error("bad request", status=400, message="bad request")
    payload = json.loads(response.content)
    assert payload["success"] is False
    assert payload["error"] == "bad request"
    assert payload["message"] == "bad request"
