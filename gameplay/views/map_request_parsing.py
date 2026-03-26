from __future__ import annotations

from typing import Any

from django.http import HttpRequest, JsonResponse

from core.utils import parse_json_object, safe_positive_int


def request_json_object_or_error(
    request: HttpRequest, *, json_error_fn
) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    data = parse_json_object(request.body)
    if data is None:
        return None, json_error_fn("无效的请求数据")
    return data, None


def target_manor_or_error(
    data: dict[str, Any],
    *,
    manor_model,
    json_error_fn,
) -> tuple[Any | None, JsonResponse | None]:
    target_id = safe_positive_int(data.get("target_id"), default=None)
    if target_id is None:
        return None, json_error_fn("目标庄园参数无效")
    try:
        return manor_model.objects.get(pk=target_id), None
    except manor_model.DoesNotExist:
        return None, json_error_fn("目标庄园不存在", status=404)


def request_target_manor_or_error(
    request: HttpRequest,
    *,
    manor_model,
    json_error_fn,
) -> tuple[dict[str, Any] | None, Any | None, JsonResponse | None]:
    data, error = request_json_object_or_error(request, json_error_fn=json_error_fn)
    if error is not None:
        return None, None, error
    if data is None:
        return None, None, json_error_fn("无效的请求数据")
    target_manor, error = target_manor_or_error(data, manor_model=manor_model, json_error_fn=json_error_fn)
    if error is not None:
        return None, None, error
    if target_manor is None:
        return data, None, json_error_fn("目标庄园不存在", status=404)
    return data, target_manor, None
