from __future__ import annotations

import logging
import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

logger = logging.getLogger(__name__)

# Initialize Django ASGI application early to ensure app registry is ready
django_asgi_app = get_asgi_application()

# Lazy import websocket routing to avoid loading Django before settings are set
try:
    from websocket import routing as websocket_routing
except Exception as exc:  # pragma: no cover - fallback if apps not ready
    # Import failures can surface as ImportError, AppRegistryNotReady (a subclass
    # of RuntimeError), or OSError depending on Django's initialisation order.
    # Re-raise unexpected errors (e.g. TypeError, ValueError) immediately.
    if not isinstance(exc, (ImportError, OSError, RuntimeError)):
        raise
    if settings.DEBUG:
        logger.exception("Failed to import websocket routing in DEBUG mode; WebSocket endpoints disabled: %s", exc)
        websocket_routing = None  # type: ignore[assignment]
    else:
        logger.exception("Failed to import websocket routing; refusing to start in production: %s", exc)
        raise

websocket_urlpatterns = []
if websocket_routing and getattr(websocket_routing, "websocket_urlpatterns", None):
    websocket_urlpatterns.extend(websocket_routing.websocket_urlpatterns)

# HTTP Application Configuration
# -------------------------------
# In production, static files should be served by a dedicated web server (nginx, CDN)
# or using WhiteNoise middleware. ASGIStaticFilesHandler is only for development.
http_app = django_asgi_app
if settings.DEBUG:
    # Development mode: serve static files via ASGI for convenience
    http_app = ASGIStaticFilesHandler(django_asgi_app)

# WebSocket Security
# ------------------
# AllowedHostsOriginValidator prevents cross-origin WebSocket hijacking attacks
# by validating the Origin header against ALLOWED_HOSTS setting
application = ProtocolTypeRouter(
    {
        "http": http_app,
        "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
    }
)
