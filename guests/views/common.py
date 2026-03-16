from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from core.utils import json_error
from core.utils.validation import sanitize_error_message


def unexpected_action_error_response(
    request: HttpRequest,
    exc: Exception,
    *,
    is_ajax: bool,
    redirect_to: str,
) -> HttpResponse:
    error_message = sanitize_error_message(exc)
    if is_ajax:
        return json_error(error_message, status=500, include_message=True)
    messages.error(request, error_message)
    return redirect(redirect_to)
