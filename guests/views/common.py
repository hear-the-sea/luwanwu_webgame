from __future__ import annotations

from django.http import HttpRequest, HttpResponse

from core.utils.view_error_mapping import action_error_response


def unexpected_action_error_response(
    request: HttpRequest,
    exc: Exception,
    *,
    is_ajax: bool,
    redirect_to: str,
) -> HttpResponse:
    return action_error_response(
        request,
        exc,
        is_ajax=is_ajax,
        redirect_to=redirect_to,
        include_message=True,
    )
