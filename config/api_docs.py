from __future__ import annotations

from django.conf import settings
from django.http import Http404
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny, IsAuthenticated


class _SettingsAwareApiDocsMixin:
    def dispatch(self, request, *args, **kwargs):
        if not settings.ENABLE_API_DOCS:
            raise Http404()
        return super().dispatch(request, *args, **kwargs)

    def get_permissions(self):
        permission_class = IsAuthenticated if settings.API_DOCS_REQUIRE_AUTH else AllowAny
        return [permission_class()]


class SettingsAwareSpectacularAPIView(_SettingsAwareApiDocsMixin, SpectacularAPIView):
    pass


class SettingsAwareSpectacularSwaggerView(_SettingsAwareApiDocsMixin, SpectacularSwaggerView):
    pass


class SettingsAwareSpectacularRedocView(_SettingsAwareApiDocsMixin, SpectacularRedocView):
    pass
