"""
帮会贡献视图：捐献、排名、资源日志
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from core.utils import safe_int, sanitize_error_message
from core.utils.rate_limit import rate_limit_redirect
from gameplay.models import Manor

from ..constants import CONTRIBUTION_RATES, DAILY_DONATION_LIMITS
from ..decorators import require_guild_member
from ..services import contribution as contribution_service
from .helpers import build_guild_member_context, execute_guild_action, load_donation_logs, load_resource_logs


@login_required
@require_guild_member
@rate_limit_redirect("guild_donate", limit=10, window_seconds=60)
def donate_resource(request):
    """捐赠资源"""
    member = request.guild_member

    if request.method == "POST":
        resource_type = request.POST.get("resource_type")
        amount = safe_int(request.POST.get("amount", 0), default=0, min_val=0)

        outcome = execute_guild_action(
            request,
            action=lambda: contribution_service.donate_resource(member, resource_type, amount),
            success_message="捐赠成功！您获得了相应的贡献度",
            error_message_formatter=sanitize_error_message,
        )
        if outcome.succeeded:
            return redirect("guilds:detail", guild_id=member.guild.id)

    manor = get_object_or_404(Manor, user=request.user)
    context = build_guild_member_context(
        member,
        manor=manor,
        contribution_rates=CONTRIBUTION_RATES,
        daily_limits=DAILY_DONATION_LIMITS,
    )

    return render(request, "guilds/donate.html", context)


@login_required
@require_guild_member
def contribution_ranking(request):
    """贡献排行榜"""
    member = request.guild_member
    guild = member.guild

    ranking_type = request.GET.get("type", "total")  # total 或 weekly
    page = safe_int(request.GET.get("page", 1), default=1, min_val=1)
    page_size = 20

    # 获取所有排名数据
    all_rankings = contribution_service.get_contribution_ranking(guild, ranking_type, limit=None)

    # 使用 Django 分页器
    from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

    paginator = Paginator(all_rankings, page_size)

    try:
        rankings = paginator.page(page)
    except PageNotAnInteger:
        rankings = paginator.page(1)
    except EmptyPage:
        rankings = paginator.page(paginator.num_pages)

    my_rank = contribution_service.get_my_contribution_rank(member, ranking_type)

    context = build_guild_member_context(
        member,
        rankings=rankings,
        my_rank=my_rank,
        ranking_type=ranking_type,
        page=page,
    )

    return render(request, "guilds/contribution_ranking.html", context)


@login_required
@require_guild_member
def resource_status(request):
    """资源状态"""
    member = request.guild_member

    context = build_guild_member_context(member)

    return render(request, "guilds/resources.html", context)


@login_required
@require_guild_member
def donation_logs(request):
    """捐赠日志"""
    member = request.guild_member
    context = build_guild_member_context(
        member,
        logs=load_donation_logs(member.guild, limit=50),
    )

    return render(request, "guilds/donation_logs.html", context)


@login_required
@require_guild_member
def resource_logs(request):
    """资源日志"""
    member = request.guild_member
    context = build_guild_member_context(
        member,
        logs=load_resource_logs(member.guild, limit=50),
    )

    return render(request, "guilds/resource_logs.html", context)
