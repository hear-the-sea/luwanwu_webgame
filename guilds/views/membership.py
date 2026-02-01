"""
帮会成员管理视图：申请、审批、职位、解散
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST

from core.utils.rate_limit import rate_limit_redirect
from ..decorators import require_guild_member, require_guild_manager, require_guild_leader
from ..models import Guild, GuildMember, GuildApplication
from ..services import guild as guild_service
from ..services import member as member_service


@login_required
@rate_limit_redirect("guild_apply", limit=5, window_seconds=60)
def apply_to_guild(request, guild_id):
    """申请加入帮会"""
    guild = get_object_or_404(Guild, id=guild_id, is_active=True)

    if request.method == 'POST':
        message = request.POST.get('message', '').strip()

        try:
            member_service.apply_to_guild(
                user=request.user,
                guild=guild,
                message=message
            )
            messages.success(request, '已提交申请，请等待审批')
            return redirect('guilds:detail', guild_id=guild.id)
        except ValueError as e:
            messages.error(request, str(e))

    context = {
        'guild': guild,
    }

    return render(request, 'guilds/apply.html', context)


@login_required
@require_guild_manager
def application_list(request):
    """申请列表"""
    member = request.guild_member

    # 获取待审批的申请
    applications = GuildApplication.objects.filter(
        guild=member.guild,
        status='pending'
    ).select_related('applicant').order_by('-created_at')

    context = {
        'applications': applications,
        'guild': member.guild,
    }

    return render(request, 'guilds/applications.html', context)


@login_required
@require_guild_manager
@require_POST
@rate_limit_redirect("guild_approve", limit=20, window_seconds=60)
def approve_application(request, app_id):
    """通过申请"""
    member = request.guild_member

    application = get_object_or_404(GuildApplication, id=app_id, guild=member.guild)

    try:
        member_service.approve_application(application, request.user)
        messages.success(request, f'已通过{application.applicant.username}的申请')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:applications')


@login_required
@require_guild_manager
@require_POST
@rate_limit_redirect("guild_reject", limit=20, window_seconds=60)
def reject_application(request, app_id):
    """拒绝申请"""
    member = request.guild_member

    application = get_object_or_404(GuildApplication, id=app_id, guild=member.guild)
    note = request.POST.get('note', '')

    try:
        member_service.reject_application(application, request.user, note)
        messages.success(request, f'已拒绝{application.applicant.username}的申请')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:applications')


@login_required
@require_guild_member
def member_list(request):
    """成员列表"""
    member = request.guild_member
    guild = member.guild

    # 获取成员列表
    leader = guild.get_leader()
    members = (
        guild.members.filter(is_active=True)
        .select_related("user__manor")
        .order_by("-position", "-total_contribution")
    )

    leader_count = 1 if leader else 0
    admin_count = guild.get_admins().count()
    normal_member_count = max(0, guild.current_member_count - leader_count - admin_count)

    context = {
        'guild': guild,
        'members': members,
        'member': member,
        "leader": leader,
        "leader_count": leader_count,
        "admin_count": admin_count,
        "normal_member_count": normal_member_count,
    }

    return render(request, 'guilds/members.html', context)


@login_required
@require_guild_manager
@require_POST
@rate_limit_redirect("guild_kick", limit=10, window_seconds=60)
def kick_member(request, member_id):
    """辞退成员"""
    # 安全修复：在查询时就过滤帮会，防止信息泄露
    target_member = get_object_or_404(
        GuildMember, id=member_id, guild_id=request.guild_member.guild_id
    )

    try:
        member_service.kick_member(target_member, request.user)
        messages.success(request, f'已辞退{target_member.user.username}')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:members')


@login_required
@require_guild_leader
@require_POST
@rate_limit_redirect("guild_appoint", limit=10, window_seconds=60)
def appoint_admin(request, member_id):
    """任命管理员"""
    # 安全修复：在查询时就过滤帮会，防止信息泄露
    target_member = get_object_or_404(
        GuildMember, id=member_id, guild_id=request.guild_member.guild_id
    )

    try:
        member_service.appoint_admin(target_member, request.user)
        messages.success(request, f'已任命{target_member.user.username}为管理员')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:members')


@login_required
@require_guild_leader
@require_POST
@rate_limit_redirect("guild_demote", limit=10, window_seconds=60)
def demote_admin(request, member_id):
    """罢免管理员"""
    # 安全修复：在查询时就过滤帮会，防止信息泄露
    target_member = get_object_or_404(
        GuildMember, id=member_id, guild_id=request.guild_member.guild_id
    )

    try:
        member_service.demote_admin(target_member, request.user)
        messages.success(request, f'已罢免{target_member.user.username}的管理员职位')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:members')


@login_required
@require_guild_leader  # 安全修复：只有帮主才能转让，改用 require_guild_leader
@require_POST
@rate_limit_redirect("guild_transfer", limit=5, window_seconds=60)
def transfer_leadership(request, member_id):
    """转让帮主"""
    current_leader = request.guild_member
    # 安全修复：在查询时就过滤帮会，防止跨帮会转让
    new_leader = get_object_or_404(
        GuildMember, id=member_id, guild_id=current_leader.guild_id
    )

    try:
        member_service.transfer_leadership(current_leader, new_leader)
        messages.success(request, f'已将帮主之位传给{new_leader.user.username}')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:members')


@login_required
@require_guild_member
@require_POST
@rate_limit_redirect("guild_leave", limit=5, window_seconds=60)
def leave_guild(request):
    """退出帮会"""
    member = request.guild_member

    try:
        member_service.leave_guild(member)
        messages.success(request, '已退出帮会')
        return redirect('guilds:hall')
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('guilds:detail', guild_id=member.guild.id)


@login_required
@require_guild_member
@require_POST
@rate_limit_redirect("guild_upgrade", limit=5, window_seconds=60)
def upgrade_guild(request):
    """升级帮会"""
    member = request.guild_member

    try:
        guild_service.upgrade_guild(member.guild, request.user)
        member.guild.refresh_from_db(fields=["level"])
        messages.success(request, f'帮会升级成功！当前等级：{member.guild.level}')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:detail', guild_id=member.guild.id)


@login_required
@require_guild_member
@require_POST
@rate_limit_redirect("guild_disband", limit=2, window_seconds=300)
def disband_guild(request):
    """解散帮会"""
    member = request.guild_member
    guild = member.guild

    # 验证确认
    confirm_name = request.POST.get('confirm_name', '')
    if confirm_name != guild.name:
        messages.error(request, '请输入正确的帮会名称以确认解散')
        return redirect('guilds:detail', guild_id=guild.id)

    try:
        guild_service.disband_guild(guild, request.user)
        messages.success(request, '帮会已解散')
        return redirect('guilds:hall')
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('guilds:detail', guild_id=guild.id)
