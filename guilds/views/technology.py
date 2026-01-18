"""
帮会科技视图
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from core.utils.rate_limit import rate_limit_redirect
from ..constants import TECH_NAMES
from ..decorators import require_guild_member
from ..services import technology as technology_service


@login_required
@require_guild_member
def technology_list(request):
    """科技列表"""
    member = request.guild_member
    guild = member.guild

    # 获取科技列表
    technologies = guild.technologies.all().order_by('category', 'tech_key')

    context = {
        'guild': guild,
        'member': member,
        'technologies': technologies,
        'tech_names': TECH_NAMES,
    }

    return render(request, 'guilds/technology.html', context)


@login_required
@require_guild_member
@require_POST
@rate_limit_redirect("guild_tech_upgrade", limit=10, window_seconds=60)
def upgrade_technology(request, tech_key):
    """升级科技"""
    member = request.guild_member
    guild = member.guild

    try:
        technology_service.upgrade_technology(guild, tech_key, request.user)
        tech_name = TECH_NAMES.get(tech_key, tech_key)
        messages.success(request, f'{tech_name}升级成功！')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:technology')
