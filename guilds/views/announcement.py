"""
帮会公告视图
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from core.utils.rate_limit import rate_limit_redirect
from ..decorators import require_guild_member, require_guild_leader
from ..services import guild as guild_service


@login_required
@require_guild_member
def announcement_list(request):
    """公告列表"""
    member = request.guild_member
    guild = member.guild

    # 获取公告列表
    announcements = guild.announcements.select_related("author__manor").all()[:30]

    context = {
        'guild': guild,
        'member': member,
        'announcements': announcements,
    }

    return render(request, 'guilds/announcements.html', context)


@login_required
@require_guild_leader
@require_POST
@rate_limit_redirect("guild_announcement", limit=5, window_seconds=60)
def create_announcement(request):
    """创建公告（仅帮主）"""
    member = request.guild_member
    content = request.POST.get('content', '').strip()

    if not content:
        messages.error(request, '公告内容不能为空')
        return redirect('guilds:announcements')

    guild_service.create_announcement(
        member.guild,
        'leader',
        content,
        request.user
    )

    messages.success(request, '公告发布成功')
    return redirect('guilds:announcements')
