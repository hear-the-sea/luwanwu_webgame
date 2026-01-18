"""
帮会视图装饰器
"""

from functools import wraps
from typing import Callable

from django.contrib import messages
from django.shortcuts import redirect


def require_guild_member(view_func: Callable) -> Callable:
    """
    装饰器：要求用户必须是活跃帮会成员

    在视图函数中，可通过 request.guild_member 获取成员对象

    用法:
        @login_required
        @require_guild_member
        def my_view(request):
            member = request.guild_member
            guild = member.guild
            ...
    """
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
            messages.error(request, '您不在帮会中')
            return redirect('guilds:hall')
        # 将成员对象附加到 request 上，方便视图使用
        request.guild_member = user.guild_membership
        return view_func(request, *args, **kwargs)
    return wrapped


def require_guild_manager(view_func: Callable) -> Callable:
    """
    装饰器：要求用户必须是帮会管理员或帮主

    在视图函数中，可通过 request.guild_member 获取成员对象

    用法:
        @login_required
        @require_guild_manager
        def my_view(request):
            member = request.guild_member  # 保证有管理权限
            ...
    """
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
            messages.error(request, '您不在帮会中')
            return redirect('guilds:hall')
        member = user.guild_membership
        if not member.can_manage:
            messages.error(request, '您没有管理权限')
            return redirect('guilds:detail', guild_id=member.guild.id)
        request.guild_member = member
        return view_func(request, *args, **kwargs)
    return wrapped


def require_guild_leader(view_func: Callable) -> Callable:
    """
    装饰器：要求用户必须是帮主

    在视图函数中，可通过 request.guild_member 获取成员对象

    用法:
        @login_required
        @require_guild_leader
        def my_view(request):
            member = request.guild_member  # 保证是帮主
            ...
    """
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
            messages.error(request, '您不在帮会中')
            return redirect('guilds:hall')
        member = user.guild_membership
        if not member.is_leader:
            messages.error(request, '只有帮主可以执行此操作')
            return redirect('guilds:detail', guild_id=member.guild.id)
        request.guild_member = member
        return view_func(request, *args, **kwargs)
    return wrapped
