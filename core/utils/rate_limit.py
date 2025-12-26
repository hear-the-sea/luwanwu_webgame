from __future__ import annotations

from functools import wraps
from typing import Callable

from django.core.cache import cache
from django.http import HttpRequest, JsonResponse


def _default_identifier(request: HttpRequest) -> str:
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return f"user:{user.pk}"
    ip = request.META.get("REMOTE_ADDR", "unknown")
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
    Fails open if cache is unavailable to avoid taking the whole feature down.
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
            except Exception:
                return view_func(request, *args, **kwargs)

            if count > limit:
                return JsonResponse({"success": False, "error": error_message}, status=429)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator

