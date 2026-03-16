"""
请求追踪中间件

为每个请求生成唯一的 request_id，用于日志追踪和问题排查。
"""

from __future__ import annotations

import contextvars
import re
import uuid
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin

_REQUEST_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_MAX_REQUEST_ID_LENGTH = 64
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def get_current_request_id() -> str:
    """获取当前请求的 ID（如果有）"""
    return _REQUEST_ID_VAR.get()


def _is_valid_request_id(value: str | None) -> bool:
    if not value:
        return False
    candidate = value.strip()
    if not candidate or len(candidate) > _MAX_REQUEST_ID_LENGTH:
        return False
    if "\n" in candidate or "\r" in candidate or "\x00" in candidate:
        return False
    return bool(_REQUEST_ID_RE.match(candidate))


class RequestIDMiddleware(MiddlewareMixin):
    """
    请求ID中间件，为每个请求生成唯一标识。

    功能：
    1. 为每个请求生成唯一的 request_id（UUID4）
    2. 将 request_id 添加到request对象，可在视图中访问
    3. 将 request_id 添加到响应头 X-Request-ID
    4. 将 request_id 存储在thread-local storage，供日志使用
    """

    def process_request(self, request: HttpRequest) -> None:
        """处理传入的请求，生成或复用 request_id"""
        # 优先从请求头中获取（支持分布式追踪）
        incoming_id: str | None = request.META.get("HTTP_X_REQUEST_ID")

        # 如果没有或非法则生成新的
        if _is_valid_request_id(incoming_id) and incoming_id is not None:
            request_id: str = incoming_id
        else:
            request_id = str(uuid.uuid4())

        # 添加到request对象
        request.id = request_id  # type: ignore[attr-defined]

        # 存储到 ContextVar（兼容 sync/async）
        request._request_id_token = _REQUEST_ID_VAR.set(request_id)  # type: ignore[attr-defined]

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """处理响应，将 request_id 添加到响应头"""
        if hasattr(request, "id"):
            response["X-Request-ID"] = request.id  # type: ignore[attr-defined]

        # 清理 ContextVar，避免串请求
        token: Any = getattr(request, "_request_id_token", None)
        if token is not None:
            try:
                _REQUEST_ID_VAR.reset(token)
            except ValueError:
                # Token was created in a different context (e.g., async/sync switch)
                # This is safe to ignore as the context will be cleaned up automatically
                pass
            finally:
                try:
                    delattr(request, "_request_id_token")
                except AttributeError:
                    pass

        return response

    def process_exception(self, request: HttpRequest, exception: Exception) -> None:
        """处理异常时也要清理 ContextVar"""
        token: Any = getattr(request, "_request_id_token", None)
        if token is not None:
            try:
                _REQUEST_ID_VAR.reset(token)
            except ValueError:
                # Token was created in a different context
                pass
            finally:
                try:
                    delattr(request, "_request_id_token")
                except AttributeError:
                    pass
