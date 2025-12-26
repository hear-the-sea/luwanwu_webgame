"""
帮会公告视图
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from ..services import guild as guild_service

@login_required
def announcement_list(request):
    """公告列表"""
    user = request.user

    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        messages.error(request, '您不在帮会中')
        return redirect('guilds:hall')

    member = user.guild_membership
    guild = member.guild

    # 获取公告列表
    announcements = guild.announcements.all()[:30]

    context = {
        'guild': guild,
        'member': member,
        'announcements': announcements,
    }

    return render(request, 'guilds/announcements.html', context)


@login_required
@require_POST
def create_announcement(request):
    """创建公告"""
    user = request.user

    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        messages.error(request, '您不在帮会中')
        return redirect('guilds:hall')

    member = user.guild_membership

    if not member.is_leader:
        messages.error(request, '只有帮主可以发布公告')
        return redirect('guilds:announcements')

    content = request.POST.get('content', '').strip()

    if not content:
        messages.error(request, '公告内容不能为空')
        return redirect('guilds:announcements')

    guild_service.create_announcement(
        member.guild,
        'leader',
        content,
        user
    )

    messages.success(request, '公告发布成功')
    return redirect('guilds:announcements')

