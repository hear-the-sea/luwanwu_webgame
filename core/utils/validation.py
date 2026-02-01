"""
输入校验工具模块

提供安全的用户输入解析和验证函数。
"""
from __future__ import annotations

from typing import Any, List, Optional, TypeVar

from django.http import HttpRequest
from django.utils.http import url_has_allowed_host_and_scheme

from core.exceptions import GameError

T = TypeVar("T")

# 允许的排序字段白名单（防止 SQL 注入）
ALLOWED_ORDERING_FIELDS = {
    # guilds
    "-level", "level", "-created_at", "created_at", "name", "-name",
    "-total_contribution", "total_contribution",
    # trade
    "-listed_at", "listed_at", "-price", "price", "-expires_at", "expires_at",
    # common
    "-id", "id", "-updated_at", "updated_at",
}


def safe_int(value: Any, default: Optional[int] = 0, min_val: Optional[int] = None, max_val: Optional[int] = None) -> Optional[int]:
    """
    安全地将值转换为整数。

    Args:
        value: 要转换的值
        default: 转换失败时的默认值（可以为 None）
        min_val: 最小值限制
        max_val: 最大值限制

    Returns:
        转换后的整数，或默认值
    """
    try:
        # Bug修复：使用 `is not None` 替代真值判断，避免 value=0 被错误处理
        result = int(value) if value is not None else default
    except (ValueError, TypeError):
        result = default

    if result is not None:
        if min_val is not None:
            result = max(min_val, result)
        if max_val is not None:
            result = min(max_val, result)

    return result


def safe_float(value: Any, default: Optional[float] = 0.0, min_val: Optional[float] = None, max_val: Optional[float] = None) -> Optional[float]:
    """
    安全地将值转换为浮点数。

    Args:
        value: 要转换的值
        default: 转换失败时的默认值（可以为 None）
        min_val: 最小值限制
        max_val: 最大值限制

    Returns:
        转换后的浮点数，或默认值
    """
    try:
        # Bug修复：使用 `is not None` 替代真值判断，避免 value=0 被错误处理
        result = float(value) if value is not None else default
    except (ValueError, TypeError):
        result = default

    if result is not None:
        if min_val is not None:
            result = max(min_val, result)
        if max_val is not None:
            result = min(max_val, result)

    return result


def safe_int_list(values: List[str], default: Optional[List[int]] = None) -> List[int]:
    """
    安全地将字符串列表转换为整数列表。

    跳过无法转换的值。

    Args:
        values: 字符串列表
        default: 转换失败或空列表时的默认值

    Returns:
        整数列表
    """
    if default is None:
        default = []

    if not values:
        return default

    result = []
    for v in values:
        try:
            result.append(int(v))
        except (ValueError, TypeError):
            continue

    return result if result else default


def safe_ordering(value: str, default: str, allowed: Optional[set] = None) -> str:
    """
    校验排序字段，防止 SQL 注入。

    Args:
        value: 用户提供的排序字段
        default: 默认排序字段
        allowed: 允许的排序字段集合

    Returns:
        安全的排序字段
    """
    if allowed is None:
        allowed = ALLOWED_ORDERING_FIELDS

    if value and value in allowed:
        return value
    return default


def sanitize_error_message(error: Exception) -> str:
    """
    清理错误消息，避免泄露敏感信息。

    对于 GameError 或 ValueError，返回其消息（通常是业务逻辑错误）。
    对于其他异常，返回通用消息。

    Args:
        error: 异常对象

    Returns:
        安全的错误消息
    """
    if isinstance(error, GameError):
        return error.message
    if isinstance(error, ValueError):
        return str(error)
    return "操作失败，请稍后重试"


def safe_redirect_url(request: HttpRequest, url: Optional[str], default: str) -> str:
    """
    验证重定向 URL 是否安全（防止开放重定向漏洞）。

    Args:
        request: HTTP 请求对象
        url: 用户提供的重定向 URL
        default: 默认重定向 URL（必须是安全的内部路径）

    Returns:
        安全的重定向 URL
    """
    if url and url_has_allowed_host_and_scheme(
        url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return url
    return default
