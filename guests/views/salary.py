"""
门客工资视图：支付工资
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from core.decorators import handle_game_errors
from core.utils.view_error_mapping import flash_view_error

from ..models import Guest

logger = logging.getLogger(__name__)


@login_required
@require_POST
@handle_game_errors(redirect_url="guests:roster")
def pay_salary_view(request, pk: int):
    """
    支付单个门客工资

    使用统一装饰器处理错误，代码更简洁
    """
    from gameplay.services.manor.core import get_manor
    from guests.services.salary import pay_guest_salary

    manor = None
    try:
        manor = get_manor(request.user)
        guest = get_object_or_404(Guest, pk=pk, manor=manor)
        payment = pay_guest_salary(manor, guest)
    except Http404:
        raise
    except DatabaseError as exc:
        flash_view_error(
            request,
            exc,
            log_message="Unexpected guest salary payment view error: manor_id=%s user_id=%s guest_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
                pk,
            ),
            logger_instance=logger,
        )
        return "guests:roster"
    messages.success(request, f"成功支付 {guest.display_name} 的工资 {payment.amount:,} 银两")

    return "guests:roster"


@login_required
@require_POST
@handle_game_errors(redirect_url="guests:roster")
def pay_all_salaries_view(request):
    """
    一键支付所有门客工资

    使用统一装饰器处理错误
    """
    from gameplay.services.manor.core import get_manor
    from guests.services.salary import pay_all_salaries

    manor = None
    try:
        manor = get_manor(request.user)
        result = pay_all_salaries(manor)
    except DatabaseError as exc:
        flash_view_error(
            request,
            exc,
            log_message="Unexpected bulk guest salary payment view error: manor_id=%s user_id=%s",
            log_args=(
                getattr(manor, "id", None),
                getattr(request.user, "id", None),
            ),
            logger_instance=logger,
        )
        return "guests:roster"
    messages.success(request, f"成功支付 {result['paid_count']} 位门客的工资，共计 {result['total_amount']:,} 银两")

    return "guests:roster"
