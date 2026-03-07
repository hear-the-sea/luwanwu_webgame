"""
建筑升级视图
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from core.decorators import flash_unexpected_view_error
from core.exceptions import GameError
from core.utils import safe_redirect_url, sanitize_error_message
from gameplay.models import Building
from gameplay.services import refresh_manor_state, start_upgrade

logger = logging.getLogger(__name__)


@method_decorator(require_POST, name="dispatch")
class UpgradeBuildingView(LoginRequiredMixin, TemplateView):
    """建筑升级视图"""

    http_method_names = ["post"]
    success_url = reverse_lazy("gameplay:dashboard")

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        redirect_url = safe_redirect_url(
            request,
            (request.POST.get("next") or "").strip(),
            str(self.success_url),
        )
        building = get_object_or_404(
            Building.objects.select_related("manor", "manor__user"),
            pk=kwargs["pk"],
            manor__user=request.user,
        )
        try:
            refresh_manor_state(building.manor)
            start_upgrade(building)
            eta = building.upgrade_complete_at.strftime("%H:%M:%S") if building.upgrade_complete_at else ""
            messages.success(request, f"{building.building_type.name} 开始升级，完成时间 {eta}")
        except (GameError, ValueError) as exc:
            messages.error(request, sanitize_error_message(exc))
        except Exception as exc:
            flash_unexpected_view_error(
                request,
                exc,
                log_message="Unexpected building upgrade view error: manor_id=%s user_id=%s building_id=%s",
                log_args=(
                    getattr(building.manor, "id", None),
                    getattr(request.user, "id", None),
                    getattr(building, "id", None),
                ),
                logger_instance=logger,
            )
        return redirect(redirect_url)
