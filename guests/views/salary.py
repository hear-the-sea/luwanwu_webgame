"""
门客工资视图：支付工资
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from core.exceptions import GameError
from core.utils import sanitize_error_message
from gameplay.services import ensure_manor

from ..models import Guest


@login_required
@require_POST
def pay_salary_view(request, pk: int):
    """支付单个门客工资"""
    from guests.services.salary import pay_guest_salary

    manor = ensure_manor(request.user)
    guest = get_object_or_404(Guest, pk=pk, manor=manor)

    try:
        payment = pay_guest_salary(manor, guest)
        messages.success(
            request,
            f"成功支付 {guest.display_name} 的工资 {payment.amount:,} 银两"
        )
    except (GameError, ValueError) as e:
        messages.error(request, sanitize_error_message(e))

    return redirect("guests:roster")


@login_required
@require_POST
def pay_all_salaries_view(request):
    """一键支付所有门客工资"""
    from guests.services.salary import pay_all_salaries

    manor = ensure_manor(request.user)

    try:
        result = pay_all_salaries(manor)
        messages.success(
            request,
            f"成功支付 {result['paid_count']} 位门客的工资，共计 {result['total_amount']:,} 银两"
        )
    except (GameError, ValueError) as e:
        messages.error(request, sanitize_error_message(e))

    return redirect("guests:roster")
