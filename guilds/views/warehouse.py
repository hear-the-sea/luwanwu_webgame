"""
帮会仓库视图
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from core.utils import safe_int, sanitize_error_message
from ..services import warehouse as warehouse_service

@login_required
def warehouse(request):
    """帮会仓库"""
    user = request.user

    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        messages.error(request, '您不在帮会中')
        return redirect('guilds:hall')

    member = user.guild_membership
    guild = member.guild

    # 获取仓库物品列表
    warehouse_items = warehouse_service.get_warehouse_items(guild)

    context = {
        'guild': guild,
        'member': member,
        'warehouse_items': warehouse_items,
    }

    return render(request, 'guilds/warehouse.html', context)


@login_required
@require_POST
def exchange_item(request, item_key):
    """兑换物品"""
    user = request.user

    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        messages.error(request, '您不在帮会中')
        return redirect('guilds:hall')

    member = user.guild_membership
    quantity = safe_int(request.POST.get('quantity', 1), default=1, min_val=1)

    try:
        warehouse_service.exchange_item(member, item_key, quantity)
        messages.success(request, '兑换成功！')
    except ValueError as e:
        messages.error(request, sanitize_error_message(e))

    return redirect('guilds:warehouse')


@login_required
def exchange_logs(request):
    """兑换日志"""
    user = request.user

    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        messages.error(request, '您不在帮会中')
        return redirect('guilds:hall')

    member = user.guild_membership
    guild = member.guild

    # 获取兑换日志
    logs = warehouse_service.get_exchange_logs(guild, 50)

    context = {
        'guild': guild,
        'logs': logs,
    }

    return render(request, 'guilds/exchange_logs.html', context)

