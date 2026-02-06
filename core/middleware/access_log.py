from __future__ import annotations

import logging
import time

from django.conf import settings

from core.utils.network import get_client_ip


logger = logging.getLogger("access")


class AccessLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "ACCESS_LOG_ENABLED", True) is False:
            return self.get_response(request)

        path = getattr(request, "path", "")
        if settings.STATIC_URL and path.startswith(settings.STATIC_URL):
            return self.get_response(request)
        if settings.MEDIA_URL and path.startswith(settings.MEDIA_URL):
            return self.get_response(request)

        start = time.monotonic()
        response = None
        exc = None
        try:
            response = self.get_response(request)
            return response
        except Exception as e:  # pragma: no cover
            exc = e
            raise
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            status_code = getattr(response, "status_code", 500)
            user = getattr(request, "user", None)
            user_id = user.pk if user and getattr(user, "is_authenticated", False) else None
            ip = get_client_ip(request, trust_proxy=getattr(settings, "ACCESS_LOG_TRUST_PROXY", False))
            request_id = getattr(request, "id", "-")
            logger.info(
                "method=%s path=%s status=%s duration_ms=%s user_id=%s ip=%s request_id=%s%s",
                request.method,
                path,
                status_code,
                duration_ms,
                user_id,
                ip,
                request_id,
                f" exc={type(exc).__name__}" if exc else "",
            )
