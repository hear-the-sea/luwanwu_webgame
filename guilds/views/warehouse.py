"""
帮会仓库视图
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from core.utils import safe_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect
from ..decorators import require_guild_member
from ..services import warehouse as warehouse_service


@login_required
@require_guild_member
def warehouse(request):
    """帮会仓库"""
    member = request.guild_member
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
@require_guild_member
@require_POST
@rate_limit_redirect("guild_exchange_item", limit=20, window_seconds=60)
def exchange_item(request, item_key):
    """兑换物品"""
    member = request.guild_member
    quantity = safe_int(request.POST.get('quantity', 1), default=1, min_val=1)

    try:
        warehouse_service.exchange_item(member, item_key, quantity)
        messages.success(request, '兑换成功！')
    except ValueError as e:
        messages.error(request, sanitize_error_message(e))

    return redirect('guilds:warehouse')


@login_required
@require_guild_member
def exchange_logs(request):
    """兑换日志"""
    member = request.guild_member
    guild = member.guild

    # 获取兑换日志
    logs = warehouse_service.get_exchange_logs(guild, 50)

    context = {
        'guild': guild,
        'logs': logs,
    }

    return render(request, 'guilds/exchange_logs.html', context)
