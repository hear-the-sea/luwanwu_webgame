from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from core.views.health import health_live, health_ready
from gameplay.views import HomeView

urlpatterns = [
    path("health/live", health_live, name="health_live"),
    path("health/live/", health_live),
    path("health/ready", health_ready, name="health_ready"),
    path("health/ready/", health_ready),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("manor/", include(("gameplay.urls", "gameplay"), namespace="gameplay")),
    path("guests/", include(("guests.urls", "guests"), namespace="guests")),
    path("battle/", include(("battle.urls", "battle"), namespace="battle")),
    path("trade/", include(("trade.urls", "trade"), namespace="trade")),
    path("guilds/", include(("guilds.urls", "guilds"), namespace="guilds")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path(
        "",
        HomeView.as_view(),
        name="home",
    ),
]

# 开发环境：战斗调试器仅在 DEBUG 下注册路由
if settings.ENABLE_BATTLE_DEBUGGER:
    urlpatterns += [
        path(
            "debugger/",
            include(("battle_debugger.urls", "battle_debugger"), namespace="battle_debugger"),
        ),
    ]

# 开发环境下提供媒体文件访问
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
