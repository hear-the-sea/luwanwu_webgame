"""
帮会科技视图
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from ..services import technology as technology_service

@login_required
def technology_list(request):
    """科技列表"""
    user = request.user

    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        messages.error(request, '您不在帮会中')
        return redirect('guilds:hall')

    member = user.guild_membership
    guild = member.guild

    # 获取科技列表
    technologies = guild.technologies.all().order_by('category', 'tech_key')

    context = {
        'guild': guild,
        'member': member,
        'technologies': technologies,
        'tech_names': technology_service.TECH_NAMES,
    }

    return render(request, 'guilds/technology.html', context)


@login_required
@require_POST
def upgrade_technology(request, tech_key):
    """升级科技"""
    user = request.user

    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        messages.error(request, '您不在帮会中')
        return redirect('guilds:hall')

    member = user.guild_membership
    guild = member.guild

    try:
        technology_service.upgrade_technology(guild, tech_key, user)
        tech_name = technology_service.TECH_NAMES.get(tech_key, tech_key)
        messages.success(request, f'{tech_name}升级成功！')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:technology')

