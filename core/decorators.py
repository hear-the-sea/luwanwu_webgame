"""
Django 视图装饰器

提供统一的错误处理和重定向逻辑。
"""

from __future__ import annotations

import logging
import re
from functools import wraps
from typing import Callable, Optional

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse, NoReverseMatch

from core.exceptions import GameError
from core.utils.validation import sanitize_error_message, safe_redirect_url

logger = logging.getLogger(__name__)


def get_next_url(request: HttpRequest, default: Optional[str] = None, result: Optional[str] = None) -> str:
    """
    获取安全的重定向 URL。

    优先级：result（视图返回值）> POST.next > GET.next > HTTP_REFERER > default

    Args:
        request: HTTP 请求对象
        default: 默认重定向 URL（可以是 URL 名称，如 "gameplay:dashboard"）
        result: 视图函数返回的 URL 字符串

    Returns:
        安全的重定向 URL

    注意：
        - result 必须是安全的 URL 名称或路径，不应直接使用用户输入
        - 如果 result 无法通过安全验证，会回退到 default
    """
    # 如果视图返回了 URL 字符串，优先使用
    if result:
        safe_result = safe_redirect_url(request, result, "")
        if safe_result:
            return safe_result
        # 如果 result 不是有效 URL，尝试作为 URL 名称解析
        # 安全修复：使用更严格的 URL 名称格式验证
        result_str = str(result)
        # Django URL 名称格式：namespace:view_name 或 view_name（只含字母、数字、下划线、连字符、冒号）
        if re.match(r'^[a-zA-Z0-9_:-]+$', result_str) and ":" in result_str:
            try:
                return reverse(result_str)
            except NoReverseMatch:
                logger.warning(f"无法解析视图返回的 URL: {result}")
        # result 不安全，回退到 default
        logger.warning(f"视图返回不安全的 URL: {result}，回退到 default")

    # 从 POST 或 GET 获取 next 参数
    next_param = request.POST.get("next") or request.GET.get("next")

    # 如果有 next 参数，验证其安全性
    if next_param:
        safe_next = safe_redirect_url(request, next_param, "")
        if safe_next:
            return safe_next

    # 尝试使用 HTTP_REFERER
    referer = request.META.get("HTTP_REFERER")
    if referer:
        safe_referer = safe_redirect_url(request, referer, "")
        if safe_referer:
            return safe_referer

    # 使用默认值
    if default:
        # 如果默认值是 URL 名称（如 "gameplay:dashboard"），则解析它
        if ":" in str(default):
            try:
                return reverse(default)
            except Exception:
                logger.warning(f"无法解析 redirect_url: {default}")
        # 默认值本身应该是安全的（由开发者控制）
        return str(default)

    # 最后回退到首页
    return "/"


def is_htmx_request(request: HttpRequest) -> bool:
    """
    检测是否为 HTMX 请求。
    """
    return request.headers.get("HX-Request") == "true"


def is_ajax_request(request: HttpRequest) -> bool:
    """
    检测是否为传统 AJAX 请求（XMLHttpRequest）。

    注意：不包含 HTMX，HTMX 使用 is_htmx_request() 检测
    """
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def expects_json(request: HttpRequest) -> bool:
    """
    检测客户端是否期望 JSON 响应。
    """
    accept = request.headers.get("Accept", "")
    return "application/json" in accept


def handle_game_errors(
    redirect_url: str | None = None,
    success_message: str | Callable[..., str] | None = None,
):
    """
    统一处理游戏错误的装饰器。

    自动捕获 GameError 和 ValueError，并添加错误消息。
    支持 AJAX/HTMX 请求，自动返回 JSON 响应。

    Args:
        redirect_url: 默认重定向 URL（可以是 URL 名称，如 "gameplay:dashboard"）
                      如果视图返回字符串 URL，会优先使用
        success_message: 成功消息（字符串或可调用对象）

    Usage:
        @login_required
        @require_POST
        @handle_game_errors(redirect_url="gameplay:dashboard")
        def my_view(request, pk):
            guest = get_guest_with_template(ensure_manor(request.user), pk)
            train_guest(guest, levels=1)
            messages.success(request, f"{guest.display_name} 开始训练")
            return redirect("guests:detail", pk=guest.pk)

        # 或返回 URL 字符串，让装饰器处理重定向
        @login_required
        @require_POST
        @handle_game_errors(redirect_url="gameplay:dashboard")
        def my_view(request, pk):
            guest = get_guest_with_template(ensure_manor(request.user), pk)
            train_guest(guest, levels=1)
            # 返回 URL 字符串，装饰器会处理重定向
            return "guests:detail"

    注意：
        - 装饰器应该在 @login_required 和 @require_POST 之后
        - 如果视图使用 @transaction.atomic，装饰器应放在它之前（外层）
        - success_message 为可调用对象时，会接收视图函数的返回值作为参数
    """
    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            try:
                result = view_func(request, *args, **kwargs)

                # 如果是字符串，视为重定向 URL
                if isinstance(result, str):
                    # 添加成功消息
                    if success_message:
                        if callable(success_message):
                            try:
                                msg = success_message(result)
                            except Exception:
                                msg = "操作成功"
                        else:
                            msg = success_message
                        messages.success(request, msg)

                    # 使用返回的 URL 作为重定向目标
                    next_url = get_next_url(request, redirect_url, result=result)
                    return redirect(next_url)

                # 如果返回 None，使用默认重定向
                if result is None:
                    if success_message:
                        if callable(success_message):
                            try:
                                msg = success_message(result)
                            except Exception:
                                msg = "操作成功"
                        else:
                            msg = success_message
                        messages.success(request, msg)

                    next_url = get_next_url(request, redirect_url)
                    return redirect(next_url)

                # 如果已经是 HttpResponse，直接返回
                return result

            except (GameError, ValueError) as exc:
                error_msg = sanitize_error_message(exc)

                # 记录 ValueError 日志（可能是程序错误）
                # 降低日志级别为 debug，避免表单验证错误刷屏
                if isinstance(exc, ValueError):
                    logger.debug(
                        f"ValueError in {view_func.__name__}: {exc}",
                        exc_info=False,  # 不需要堆栈，因为这是预期的用户输入错误
                        extra={"request": request},
                    )

                # HTMX 请求：返回重定向响应（HTMX 会自动处理）
                if is_htmx_request(request):
                    next_url = get_next_url(request, redirect_url)
                    return redirect(next_url)

                # 传统 AJAX/JSON 请求返回 JSON 响应
                if is_ajax_request(request) or expects_json(request):
                    return JsonResponse(
                        {"success": False, "message": error_msg},
                        status=400,
                    )

                # 普通请求：添加错误消息并重定向
                messages.error(request, error_msg)
                next_url = get_next_url(request, redirect_url)
                return redirect(next_url)

        return wrapper
    return decorator


def atomic_handle_game_errors(
    redirect_url: str | None = None,
    success_message: str | Callable[..., str] | None = None,
):
    """
    组合装饰器：自动在事务中执行，并处理游戏错误。

    这是 `@transaction.atomic` 和 `@handle_game_errors` 的组合。

    注意：
        - 装饰器顺序很重要：atomic 在内层，错误处理在外层
        - 这样异常会先触发事务回滚，再被错误处理捕获

    Usage:
        @login_required
        @require_POST
        @atomic_handle_game_errors(redirect_url="gameplay:dashboard")
        def my_view(request, pk):
            # 自动在事务中执行
            guest = get_guest_with_template(ensure_manor(request.user), pk)
            train_guest(guest, levels=1)
            # ...
    """
    def decorator(view_func: Callable) -> Callable:
        # 先应用事务装饰器（内层）- 让异常先触发回滚
        atomic_view = transaction.atomic(view_func)
        # 再应用错误处理装饰器（外层）- 捕获异常并转换成响应
        return handle_game_errors(
            redirect_url=redirect_url,
            success_message=success_message,
        )(atomic_view)

    return decorator
