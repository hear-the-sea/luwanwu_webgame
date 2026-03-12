"""
帮会科技视图
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core.utils.rate_limit import rate_limit_redirect

from ..constants import TECH_NAMES
from ..decorators import require_guild_member
from ..services import technology as technology_service
from .helpers import build_guild_member_context, execute_guild_action, load_ordered_technologies


@login_required
@require_guild_member
def technology_list(request):
    """科技列表"""
    member = request.guild_member
    context = build_guild_member_context(
        member,
        technologies=load_ordered_technologies(member.guild),
        tech_names=TECH_NAMES,
    )

    return render(request, "guilds/technology.html", context)


@login_required
@require_guild_member
@require_POST
@rate_limit_redirect("guild_tech_upgrade", limit=10, window_seconds=60)
def upgrade_technology(request, tech_key):
    """升级科技"""
    member = request.guild_member

    execute_guild_action(
        request,
        action=lambda: technology_service.upgrade_technology(member.guild, tech_key, request.user),
        success_message=lambda _result: f"{TECH_NAMES.get(tech_key, tech_key)}升级成功！",
    )

    return redirect("guilds:technology")
