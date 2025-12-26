# guilds/services/member.py

from django.db import transaction
from django.utils import timezone
from ..models import Guild, GuildMember, GuildApplication
from gameplay.models import Manor
from gameplay.services.messages import create_message
from .guild import create_announcement


def _get_active_membership(guild: Guild, user, error_msg: str = "您不是该帮会成员") -> GuildMember:
    """
    获取用户在指定帮会的有效成员记录

    Args:
        guild: 帮会对象
        user: 用户对象
        error_msg: 找不到成员时的错误消息

    Returns:
        GuildMember对象

    Raises:
        ValueError: 用户不是该帮会的活跃成员
    """
    try:
        return GuildMember.objects.get(guild=guild, user=user, is_active=True)
    except GuildMember.DoesNotExist:
        raise ValueError(error_msg)


def apply_to_guild(user, guild, message=''):
    """
    申请加入帮会

    Args:
        user: 申请人User对象
        guild: Guild对象
        message: 申请留言

    Returns:
        GuildApplication对象

    Raises:
        ValueError: 验证失败
    """
    # 验证用户是否已加入帮会
    if hasattr(user, 'guild_membership') and user.guild_membership.is_active:
        raise ValueError("您已加入帮会")

    # 验证帮会是否已满员
    if guild.is_full:
        raise ValueError("帮会已满员")

    # 验证是否已有待审批的申请
    existing = GuildApplication.objects.filter(
        guild=guild,
        applicant=user,
        status='pending'
    ).exists()
    if existing:
        raise ValueError("您已有待审批的申请")

    # 创建申请
    application = GuildApplication.objects.create(
        guild=guild,
        applicant=user,
        message=message,
        status='pending',
    )

    # 如果设置了自动接受，直接通过
    if guild.auto_accept:
        approve_application(application, None, auto=True)

    return application


def approve_application(application, reviewer, auto=False):
    """
    通过申请

    Args:
        application: GuildApplication对象
        reviewer: 审批人User对象（auto=True时可为None）
        auto: 是否自动审批

    Raises:
        ValueError: 验证失败
    """
    if application.status != 'pending':
        raise ValueError("申请已被处理")

    guild = application.guild

    # 验证帮会是否已满员
    if guild.is_full:
        raise ValueError("帮会已满员")

    # 验证申请人是否已加入其他帮会
    existing_membership = GuildMember.objects.filter(
        user=application.applicant, is_active=True
    ).first()
    if existing_membership:
        raise ValueError("申请人已加入其他帮会")

    # 验证权限（非自动审批时）
    if not auto:
        membership = _get_active_membership(guild, reviewer, "您没有审批权限")
        if not membership.can_manage:
            raise ValueError("您没有审批权限")

    with transaction.atomic():
        # 更新申请状态
        application.status = 'approved'
        application.reviewed_by = reviewer
        application.reviewed_at = timezone.now()
        application.save()

        # 创建或更新成员记录
        # 由于GuildMember.user是OneToOneField，需要处理已存在的记录
        try:
            member = GuildMember.objects.get(user=application.applicant)
            # 如果用户之前有记录（退帮后重新加入），更新记录
            member.guild = guild
            member.position = 'member'
            member.is_active = True
            member.joined_at = timezone.now()
            member.left_at = None
            member.save()
        except GuildMember.DoesNotExist:
            # 如果是新成员，创建记录
            GuildMember.objects.create(
                guild=guild,
                user=application.applicant,
                position='member',
            )

        # 发送系统消息给申请人
        applicant_manor = Manor.objects.get(user=application.applicant)
        create_message(
            manor=applicant_manor,
            kind='system',
            title='入帮申请通过',
            body=f"您的入帮申请已通过，欢迎加入【{guild.name}】！",
        )

        # 发布帮会公告
        create_announcement(
            guild,
            'system',
            f"欢迎新成员{applicant_manor.display_name}加入帮会！",
        )


def reject_application(application, reviewer, note=''):
    """
    拒绝申请

    Args:
        application: GuildApplication对象
        reviewer: 审批人User对象
        note: 拒绝原因

    Raises:
        ValueError: 验证失败
    """
    if application.status != 'pending':
        raise ValueError("申请已被处理")

    # 验证权限
    membership = _get_active_membership(application.guild, reviewer, "您没有审批权限")
    if not membership.can_manage:
        raise ValueError("您没有审批权限")

    with transaction.atomic():
        # 更新申请状态
        application.status = 'rejected'
        application.reviewed_by = reviewer
        application.reviewed_at = timezone.now()
        application.review_note = note
        application.save()

        # 发送系统消息给申请人
        create_message(
            manor=Manor.objects.get(user=application.applicant),
            kind='system',
            title='入帮申请被拒绝',
            body=f"您的入帮申请被拒绝。\n拒绝原因：{note if note else '无'}",
        )


def leave_guild(member):
    """
    退出帮会

    Args:
        member: GuildMember对象

    Raises:
        ValueError: 验证失败
    """
    if not member.is_active:
        raise ValueError("您不在帮会中")

    if member.is_leader:
        raise ValueError("帮主无法直接退出，请先转让帮主或解散帮会")

    guild = member.guild
    member_manor = Manor.objects.get(user=member.user)
    display_name = member_manor.display_name

    with transaction.atomic():
        # 删除成员记录（因为 user 是 OneToOneField，必须删除才能加入其他帮会）
        member.delete()

        # 发布公告
        create_announcement(
            guild,
            'system',
            f"成员{display_name}离开了帮会。",
        )


def kick_member(target_member, operator):
    """
    辞退成员

    Args:
        target_member: 被辞退的GuildMember对象
        operator: 操作者User对象

    Raises:
        ValueError: 验证失败
    """
    # 验证权限
    operator_member = _get_active_membership(target_member.guild, operator, "您没有辞退权限")
    if not operator_member.can_manage:
        raise ValueError("您没有辞退权限")

    # 不能辞退帮主和管理员
    if target_member.position in ['leader', 'admin']:
        raise ValueError("无法辞退帮主或管理员")

    # 不能辞退自己
    if target_member.user == operator:
        raise ValueError("无法辞退自己")

    guild = target_member.guild
    target_user = target_member.user
    target_manor = Manor.objects.get(user=target_user)
    display_name = target_manor.display_name

    with transaction.atomic():
        # 删除成员记录（因为 user 是 OneToOneField，必须删除才能加入其他帮会）
        target_member.delete()

        # 发送系统消息
        create_message(
            manor=target_manor,
            kind='system',
            title='被移出帮会',
            body=f"您已被移出帮会【{guild.name}】。",
        )

        # 发布公告
        create_announcement(
            guild,
            'system',
            f"成员{display_name}被移出帮会。",
        )


def appoint_admin(target_member, operator):
    """
    任命管理员

    Args:
        target_member: GuildMember对象
        operator: 操作者User对象

    Raises:
        ValueError: 验证失败
    """
    # 验证权限（只有帮主可任命）
    operator_member = _get_active_membership(target_member.guild, operator, "只有帮主可以任命管理员")
    if not operator_member.is_leader:
        raise ValueError("只有帮主可以任命管理员")

    # 验证管理员数量
    if not target_member.guild.can_appoint_admin():
        raise ValueError("管理员数量已达上限（2人）")

    # 验证目标成员
    if target_member.position != 'member':
        raise ValueError("该成员已是管理人员")

    # 获取庄园名称
    operator_manor = Manor.objects.get(user=operator)
    target_manor = Manor.objects.get(user=target_member.user)

    with transaction.atomic():
        # 任命为管理员
        target_member.position = 'admin'
        target_member.save(update_fields=['position'])

        # 发送系统消息
        create_message(
            manor=target_manor,
            kind='system',
            title='职位变更',
            body=f"您已被任命为帮会【{target_member.guild.name}】的管理员！",
        )

        # 发布公告
        create_announcement(
            target_member.guild,
            'system',
            f"{operator_manor.display_name}任命{target_manor.display_name}为管理员。",
        )


def demote_admin(target_member, operator):
    """
    罢免管理员

    Args:
        target_member: GuildMember对象
        operator: 操作者User对象

    Raises:
        ValueError: 验证失败
    """
    # 验证权限（只有帮主可罢免）
    operator_member = _get_active_membership(target_member.guild, operator, "只有帮主可以罢免管理员")
    if not operator_member.is_leader:
        raise ValueError("只有帮主可以罢免管理员")

    # 验证目标成员
    if target_member.position != 'admin':
        raise ValueError("该成员不是管理员")

    # 获取庄园名称
    target_manor = Manor.objects.get(user=target_member.user)

    with transaction.atomic():
        # 降为普通成员
        target_member.position = 'member'
        target_member.save(update_fields=['position'])

        # 发送系统消息
        create_message(
            manor=target_manor,
            kind='system',
            title='职位变更',
            body="您已被罢免管理员职位，降为普通成员。",
        )

        # 发布公告
        create_announcement(
            target_member.guild,
            'system',
            f"{target_manor.display_name}卸任管理员职位。",
        )


def transfer_leadership(current_leader_member, new_leader_member):
    """
    转让帮主

    Args:
        current_leader_member: 当前帮主GuildMember对象
        new_leader_member: 新帮主GuildMember对象

    Raises:
        ValueError: 验证失败
    """
    # 验证当前用户是帮主
    if not current_leader_member.is_leader:
        raise ValueError("您不是帮主")

    # 验证新帮主是同帮会成员
    if new_leader_member.guild != current_leader_member.guild:
        raise ValueError("只能转让给本帮会成员")

    # 验证新帮主是活跃成员
    if not new_leader_member.is_active:
        raise ValueError("该成员已离开帮会")

    # 获取庄园名称
    current_leader_manor = Manor.objects.get(user=current_leader_member.user)
    new_leader_manor = Manor.objects.get(user=new_leader_member.user)

    with transaction.atomic():
        # 原帮主降为普通成员
        current_leader_member.position = 'member'
        current_leader_member.save(update_fields=['position'])

        # 新帮主上任
        new_leader_member.position = 'leader'
        new_leader_member.save(update_fields=['position'])

        # 发送系统消息
        create_message(
            manor=new_leader_manor,
            kind='system',
            title='职位变更',
            body=f"您已成为帮会【{new_leader_member.guild.name}】的新任帮主！",
        )

        # 发布公告
        create_announcement(
            new_leader_member.guild,
            'system',
            f"{current_leader_manor.display_name}将帮主之位传给了{new_leader_manor.display_name}！",
        )


def get_member_rankings(guild, ranking_type='total'):
    """
    获取成员排行榜

    Args:
        guild: Guild对象
        ranking_type: 'total'(总贡献) 或 'weekly'(本周贡献)

    Returns:
        QuerySet
    """
    members = guild.members.filter(is_active=True).select_related('user')

    if ranking_type == 'weekly':
        return members.order_by('-weekly_contribution', '-total_contribution')[:10]
    else:
        return members.order_by('-total_contribution', '-joined_at')[:10]
