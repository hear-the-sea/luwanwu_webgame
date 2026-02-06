from __future__ import annotations

import logging
from functools import wraps
from typing import Callable

from django.core.cache import cache
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from redis.exceptions import RedisError

from core.utils.network import get_client_ip

logger = logging.getLogger(__name__)


def _cache_error_response(is_json: bool, error_message: str, request: HttpRequest, redirect_url: str | None = None):
    if is_json:
        return JsonResponse(
            {"success": False, "error": "系统繁忙，请稍后再试"},
            status=503,
        )

    messages.error(request, error_message)
    if redirect_url:
        return redirect(redirect_url)

    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("/")


def _default_identifier(request: HttpRequest) -> str:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return f"user:{user.pk}"
    ip = get_client_ip(request, trust_proxy=True)
    return f"ip:{ip}"


def rate_limit_json(
    scope: str,
    *,
    limit: int,
    window_seconds: int,
    key_func: Callable[[HttpRequest], str] | None = None,
    error_message: str = "请求过于频繁，请稍后再试",
) -> Callable:
    """
    Lightweight, cache-backed rate limiting for JSON views.

    This is intended for non-DRF endpoints (plain Django views).
    Fails closed (503) if cache is unavailable to keep critical operations safe.
    """
    if limit <= 0:
        raise ValueError("limit must be > 0")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be > 0")

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapped(request: HttpRequest, *args, **kwargs):
            if request.method in {"GET", "HEAD", "OPTIONS"}:
                return view_func(request, *args, **kwargs)
            user = getattr(request, "user", None)
            if user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
                return view_func(request, *args, **kwargs)

            identifier = (key_func(request) if key_func else _default_identifier(request)).strip()
            cache_key = f"rl:{scope}:{identifier}"

            try:
                if cache.add(cache_key, 1, timeout=window_seconds):
                    count = 1
                else:
                    count = int(cache.incr(cache_key))
            except ValueError:
                cache.set(cache_key, 1, timeout=window_seconds)
                count = 1
            except RedisError:
                logger.error("Rate limit Redis unavailable", exc_info=True)
                return _cache_error_response(True, error_message, request)
            except ConnectionError:
                logger.error("Rate limit cache connection unavailable", exc_info=True)
                return _cache_error_response(True, error_message, request)
            except Exception:
                logger.error("Rate limit cache unexpected error", exc_info=True)
                return _cache_error_response(True, error_message, request)

            if count > limit:
                return JsonResponse({"success": False, "error": error_message}, status=429)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def rate_limit_redirect(
    scope: str,
    *,
    limit: int,
    window_seconds: int,
    error_message: str = "操作过于频繁，请稍后再试",
    redirect_url: str | None = None,
) -> Callable:
    """
    Lightweight, cache-backed rate limiting for redirect-based views.

    Returns a safe redirect with error message if cache is unavailable.
    """
    if limit <= 0:
        raise ValueError("limit must be > 0")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be > 0")

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapped(request: HttpRequest, *args, **kwargs):
            user = getattr(request, "user", None)
            if user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
                return view_func(request, *args, **kwargs)

            identifier = _default_identifier(request).strip()
            cache_key = f"rl:{scope}:{identifier}"

            try:
                if cache.add(cache_key, 1, timeout=window_seconds):
                    count = 1
                else:
                    count = int(cache.incr(cache_key))
            except ValueError:
                cache.set(cache_key, 1, timeout=window_seconds)
                count = 1
            except RedisError:
                logger.error("Rate limit redirect Redis unavailable", exc_info=True)
                return _cache_error_response(False, error_message, request, redirect_url)
            except ConnectionError:
                logger.error("Rate limit redirect cache connection unavailable", exc_info=True)
                return _cache_error_response(False, error_message, request, redirect_url)
            except Exception:
                logger.error("Rate limit redirect cache unexpected error", exc_info=True)
                return _cache_error_response(False, error_message, request, redirect_url)

            if count > limit:
                messages.error(request, error_message)
                if redirect_url:
                    return redirect(redirect_url)
                # 安全修复：验证 Referer 是否为安全的重定向目标，防止开放重定向漏洞
                referer = request.META.get("HTTP_REFERER", "")
                if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
                    return redirect(referer)
                return redirect("/")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
