"""
帮会贡献视图：捐献、排名、资源日志
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from core.utils import safe_int, sanitize_error_message
from ..constants import CONTRIBUTION_RATES, DAILY_DONATION_LIMITS
from ..decorators import require_guild_member
from ..services import contribution as contribution_service
from gameplay.models import Manor


@login_required
@require_guild_member
def donate_resource(request):
    """捐赠资源"""
    member = request.guild_member

    if request.method == 'POST':
        resource_type = request.POST.get('resource_type')
        amount = safe_int(request.POST.get('amount', 0), default=0, min_val=0)

        try:
            contribution_service.donate_resource(member, resource_type, amount)
            messages.success(request, '捐赠成功！您获得了相应的贡献度')
            return redirect('guilds:detail', guild_id=member.guild.id)
        except ValueError as e:
            messages.error(request, sanitize_error_message(e))

    manor = get_object_or_404(Manor, user=request.user)
    context = {
        'guild': member.guild,
        'member': member,
        'manor': manor,
        'contribution_rates': CONTRIBUTION_RATES,
        'daily_limits': DAILY_DONATION_LIMITS,
    }

    return render(request, 'guilds/donate.html', context)


@login_required
@require_guild_member
def contribution_ranking(request):
    """贡献排行榜"""
    member = request.guild_member
    guild = member.guild

    ranking_type = request.GET.get('type', 'total')  # total 或 weekly
    page = safe_int(request.GET.get('page', 1), default=1, min_val=1)
    page_size = 20

    # 获取所有排名数据
    all_rankings = contribution_service.get_contribution_ranking(guild, ranking_type, limit=None)

    # 使用 Django 分页器
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    paginator = Paginator(all_rankings, page_size)

    try:
        rankings = paginator.page(page)
    except PageNotAnInteger:
        rankings = paginator.page(1)
    except EmptyPage:
        rankings = paginator.page(paginator.num_pages)

    my_rank = contribution_service.get_my_contribution_rank(member, ranking_type)

    context = {
        'guild': guild,
        'member': member,
        'rankings': rankings,
        'my_rank': my_rank,
        'ranking_type': ranking_type,
        'page': page,
    }

    return render(request, 'guilds/contribution_ranking.html', context)


@login_required
@require_guild_member
def resource_status(request):
    """资源状态"""
    member = request.guild_member
    guild = member.guild

    context = {
        'guild': guild,
        'member': member,
    }

    return render(request, 'guilds/resources.html', context)


@login_required
@require_guild_member
def donation_logs(request):
    """捐赠日志"""
    member = request.guild_member
    guild = member.guild

    # 获取捐赠日志
    logs = guild.donation_logs.all().select_related('member__user__manor')[:50]

    context = {
        'guild': guild,
        'logs': logs,
    }

    return render(request, 'guilds/donation_logs.html', context)


@login_required
@require_guild_member
def resource_logs(request):
    """资源日志"""
    member = request.guild_member
    guild = member.guild

    # 获取资源流水
    logs = guild.resource_logs.all().select_related("related_user")[:50]

    context = {
        'guild': guild,
        'logs': logs,
    }

    return render(request, 'guilds/resource_logs.html', context)
