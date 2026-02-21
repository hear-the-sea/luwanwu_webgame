"""
帮会仓库视图
"""

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.utils import safe_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect

from ..decorators import require_guild_member
from ..services import warehouse as warehouse_service

# item_key 格式验证正则（只允许小写字母、数字、下划线）
ITEM_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")


@login_required
@require_guild_member
def warehouse(request):
    """帮会仓库"""
    member = request.guild_member
    guild = member.guild

    # 获取分页参数
    page = safe_int(request.GET.get("page", 1), default=1, min_val=1)

    # 获取仓库物品列表（分页）
    warehouse_data = warehouse_service.get_warehouse_items(guild, page=page, per_page=50)

    context = {
        "guild": guild,
        "member": member,
        "warehouse_items": warehouse_data["items"],
        "pagination": warehouse_data,
    }

    return render(request, "guilds/warehouse.html", context)


@login_required
@require_guild_member
@require_POST
@rate_limit_redirect("guild_exchange_item", limit=20, window_seconds=60)
def exchange_item(request, item_key):
    """兑换物品"""
    # 验证 item_key 格式（防止注入攻击）
    if not item_key or not ITEM_KEY_PATTERN.match(item_key):
        messages.error(request, "无效的物品标识")
        return redirect("guilds:warehouse")

    member = request.guild_member
    quantity = safe_int(request.POST.get("quantity", 1), default=1, min_val=1, max_val=100)

    try:
        warehouse_service.exchange_item(member, item_key, quantity)
        messages.success(request, "兑换成功！")
    except ValueError as e:
        messages.error(request, sanitize_error_message(e))

    return redirect("guilds:warehouse")


@login_required
@require_guild_member
def exchange_logs(request):
    """兑换日志"""
    member = request.guild_member
    guild = member.guild

    # 获取兑换日志
    logs = warehouse_service.get_exchange_logs(guild, 50)

    context = {
        "guild": guild,
        "logs": logs,
    }

    return render(request, "guilds/exchange_logs.html", context)
