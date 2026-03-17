# guilds/services/member.py

import logging

from django.db import transaction
from django.db.utils import IntegrityError
from django.utils import timezone

from gameplay.models import Manor
from gameplay.services.utils.messages import create_message

from ..models import Guild, GuildApplication, GuildMember
from .guild import create_announcement
from .hero_pool import invalidate_member_hero_pool
from .utils import get_active_membership

logger = logging.getLogger(__name__)


def _log_followup_failure(action, **context):
    context_str = " ".join(f"{key}={value}" for key, value in context.items())
    if context_str:
        logger.warning("Guild %s follow-up failed: %s", action, context_str, exc_info=True)
    else:
        logger.warning("Guild %s follow-up failed", action, exc_info=True)


def _run_followup(action, callback, **context):
    try:
        callback()
    except Exception:
        _log_followup_failure(action, **context)


def _get_manor_and_display_name(user_id):
    manor = Manor.objects.filter(user_id=user_id).first()
    if manor is None:
        return None, f"用户{user_id}"
    return manor, manor.display_name


def apply_to_guild(user, guild, message=""):
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
    if hasattr(user, "guild_membership") and user.guild_membership.is_active:
        raise ValueError("您已加入帮会")

    # 验证帮会是否已满员
    if guild.is_full:
        raise ValueError("帮会已满员")

    # 验证是否已有待审批的申请
    existing = GuildApplication.objects.filter(guild=guild, applicant=user, status="pending").exists()
    if existing:
        raise ValueError("您已有待审批的申请")

    # 创建申请
    application = GuildApplication.objects.create(
        guild=guild,
        applicant=user,
        message=message,
        status="pending",
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
    with transaction.atomic():
        # 锁定申请行，避免并发重复处理
        application_locked = (
            GuildApplication.objects.select_for_update().select_related("guild", "applicant").get(pk=application.pk)
        )
        if application_locked.status != "pending":
            raise ValueError("申请已被处理")

        guild = application_locked.guild

        # 锁定帮会行，串行化审批，避免并发超员
        guild_locked = Guild.objects.select_for_update().get(pk=guild.pk)

        # 验证权限（非自动审批时）
        if not auto:
            membership = get_active_membership(guild_locked, reviewer, "您没有审批权限")
            if not membership.can_manage:
                raise ValueError("您没有审批权限")

        # 在锁内检查是否满员
        current_count = GuildMember.objects.filter(guild=guild_locked, is_active=True).count()
        if current_count >= guild_locked.member_capacity:
            raise ValueError("帮会已满员")

        # 验证申请人是否已加入其他帮会
        existing_membership = (
            GuildMember.objects.select_for_update().filter(user=application_locked.applicant, is_active=True).first()
        )
        if existing_membership:
            raise ValueError("申请人已加入其他帮会")

        # 更新申请状态
        application_locked.status = "approved"
        application_locked.reviewed_by = reviewer
        application_locked.reviewed_at = timezone.now()
        application_locked.save(update_fields=["status", "reviewed_by", "reviewed_at"])

        # 创建或更新成员记录
        # 由于GuildMember.user是OneToOneField，需要处理已存在的记录
        member_record = GuildMember.objects.select_for_update().filter(user=application_locked.applicant).first()
        if member_record:
            # 如果用户之前有记录（退帮后重新加入），更新记录
            member_record.guild = guild_locked
            member_record.position = "member"
            member_record.is_active = True
            member_record.joined_at = timezone.now()
            member_record.left_at = None
            member_record.save(update_fields=["guild", "position", "is_active", "joined_at", "left_at"])
        else:
            # 如果是新成员，创建记录（并发下可能触发唯一约束）
            try:
                GuildMember.objects.create(
                    guild=guild_locked,
                    user=application_locked.applicant,
                    position="member",
                )
            except IntegrityError:
                raise ValueError("申请人已加入其他帮会")

        # 发送系统消息给申请人（在事务外获取 Manor 以减少锁持有时间）
        applicant_user_id = application_locked.applicant_id
        guild_name = guild_locked.name

    # 事务外发送消息，减少锁持有时间。通知失败不应回滚已完成的审批流程。
    applicant_manor, display_name = _get_manor_and_display_name(applicant_user_id)
    if applicant_manor is None:
        logger.warning(
            "Guild approve follow-up message skipped because manor missing: applicant_user_id=%s guild=%s",
            applicant_user_id,
            guild_name,
        )
    else:
        _run_followup(
            "approve message",
            lambda: create_message(
                manor=applicant_manor,
                kind="system",
                title="入帮申请通过",
                body=f"您的入帮申请已通过，欢迎加入【{guild_name}】！",
            ),
            applicant_user_id=applicant_user_id,
            guild=guild_name,
        )

    _run_followup(
        "approve announcement",
        lambda: create_announcement(
            guild_locked,
            "system",
            f"欢迎新成员{display_name}加入帮会！",
        ),
        applicant_user_id=applicant_user_id,
        guild=guild_name,
    )


def reject_application(application, reviewer, note=""):
    """
    拒绝申请

    Args:
        application: GuildApplication对象
        reviewer: 审批人User对象
        note: 拒绝原因

    Raises:
        ValueError: 验证失败
    """
    with transaction.atomic():
        application_locked = (
            GuildApplication.objects.select_for_update().select_related("guild", "applicant").get(pk=application.pk)
        )
        if application_locked.status != "pending":
            raise ValueError("申请已被处理")

        # 验证权限（锁内读取，避免跨帮会越权/并发状态异常）
        membership = get_active_membership(application_locked.guild, reviewer, "您没有审批权限")
        if not membership.can_manage:
            raise ValueError("您没有审批权限")

        # 更新申请状态
        application_locked.status = "rejected"
        application_locked.reviewed_by = reviewer
        application_locked.reviewed_at = timezone.now()
        application_locked.review_note = note
        application_locked.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])

        applicant_user_id = application_locked.applicant_id
        guild_name = application_locked.guild.name

    applicant_manor, _ = _get_manor_and_display_name(applicant_user_id)
    if applicant_manor is None:
        logger.warning(
            "Guild reject follow-up message skipped because manor missing: applicant_user_id=%s guild=%s",
            applicant_user_id,
            guild_name,
        )
        return

    _run_followup(
        "reject message",
        lambda: create_message(
            manor=applicant_manor,
            kind="system",
            title="入帮申请被拒绝",
            body=f"您的入帮申请被拒绝。\n拒绝原因：{note if note else '无'}",
        ),
        applicant_user_id=applicant_user_id,
        guild=guild_name,
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
    member_user_id = member.user_id
    guild_name = guild.name

    with transaction.atomic():
        # 安全修复：使用软删除保留历史数据（贡献度、捐赠日志等）
        # 锁定成员记录防止并发问题
        member_locked = GuildMember.objects.select_for_update().get(pk=member.pk)
        if not member_locked.is_active:
            raise ValueError("您不在帮会中")

        member_locked.is_active = False
        member_locked.left_at = timezone.now()
        member_locked.save(update_fields=["is_active", "left_at"])
        invalidate_member_hero_pool(member_locked)

    _, display_name = _get_manor_and_display_name(member_user_id)
    _run_followup(
        "leave announcement",
        lambda: create_announcement(
            guild,
            "system",
            f"成员{display_name}离开了帮会。",
        ),
        member_user_id=member_user_id,
        guild=guild_name,
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
    operator_member = get_active_membership(target_member.guild, operator, "您没有辞退权限")
    if not operator_member.can_manage:
        raise ValueError("您没有辞退权限")

    # 不能辞退帮主和管理员
    if target_member.position in ["leader", "admin"]:
        raise ValueError("无法辞退帮主或管理员")

    # 不能辞退自己
    if target_member.user == operator:
        raise ValueError("无法辞退自己")

    guild = target_member.guild
    target_user = target_member.user
    target_user_id = target_user.id
    guild_name = guild.name

    with transaction.atomic():
        # 安全修复：使用软删除保留历史数据（贡献度、捐赠日志等）
        # 锁定成员记录防止并发问题
        target_locked = GuildMember.objects.select_for_update().get(pk=target_member.pk)
        if not target_locked.is_active:
            raise ValueError("该成员已不在帮会中")

        target_locked.is_active = False
        target_locked.left_at = timezone.now()
        target_locked.save(update_fields=["is_active", "left_at"])
        invalidate_member_hero_pool(target_locked)

    target_manor, display_name = _get_manor_and_display_name(target_user_id)
    if target_manor is None:
        logger.warning(
            "Guild kick follow-up message skipped because manor missing: target_user_id=%s guild=%s",
            target_user_id,
            guild_name,
        )
    else:
        _run_followup(
            "kick message",
            lambda: create_message(
                manor=target_manor,
                kind="system",
                title="被移出帮会",
                body=f"您已被移出帮会【{guild_name}】。",
            ),
            target_user_id=target_user_id,
            guild=guild_name,
        )

    _run_followup(
        "kick announcement",
        lambda: create_announcement(
            guild,
            "system",
            f"成员{display_name}被移出帮会。",
        ),
        target_user_id=target_user_id,
        guild=guild_name,
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
    from guilds.models import Guild, GuildMember

    # 验证权限（只有帮主可任命）
    operator_member = get_active_membership(target_member.guild, operator, "只有帮主可以任命管理员")
    if not operator_member.is_leader:
        raise ValueError("只有帮主可以任命管理员")

    # 验证目标成员
    if target_member.position != "member":
        raise ValueError("该成员已是管理人员")

    guild = target_member.guild
    guild_name = guild.name
    operator_user_id = operator.id
    target_user_id = target_member.user_id

    with transaction.atomic():
        # 锁定帮会后重新检查管理员数量，防止并发超限
        guild_locked = Guild.objects.select_for_update().get(pk=target_member.guild_id)
        admin_count = guild_locked.members.filter(is_active=True, position="admin").count()
        if admin_count >= 2:
            raise ValueError("管理员数量已达上限（2人）")

        # 锁定目标成员并重新验证状态
        target_locked = GuildMember.objects.select_for_update().get(pk=target_member.pk)
        if target_locked.position != "member":
            raise ValueError("该成员已是管理人员")

        # 任命为管理员
        target_locked.position = "admin"
        target_locked.save(update_fields=["position"])

    _, operator_display_name = _get_manor_and_display_name(operator_user_id)
    target_manor, target_display_name = _get_manor_and_display_name(target_user_id)
    if target_manor is None:
        logger.warning(
            "Guild appoint-admin follow-up message skipped because manor missing: target_user_id=%s guild=%s",
            target_user_id,
            guild_name,
        )
    else:
        _run_followup(
            "appoint-admin message",
            lambda: create_message(
                manor=target_manor,
                kind="system",
                title="职位变更",
                body=f"您已被任命为帮会【{guild_name}】的管理员！",
            ),
            target_user_id=target_user_id,
            guild=guild_name,
        )

    _run_followup(
        "appoint-admin announcement",
        lambda: create_announcement(
            guild,
            "system",
            f"{operator_display_name}任命{target_display_name}为管理员。",
        ),
        operator_user_id=operator_user_id,
        target_user_id=target_user_id,
        guild=guild_name,
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
    operator_member = get_active_membership(target_member.guild, operator, "只有帮主可以罢免管理员")
    if not operator_member.is_leader:
        raise ValueError("只有帮主可以罢免管理员")

    # 验证目标成员
    if target_member.position != "admin":
        raise ValueError("该成员不是管理员")

    guild = target_member.guild
    guild_name = guild.name
    target_user_id = target_member.user_id

    with transaction.atomic():
        # 降为普通成员
        target_member.position = "member"
        target_member.save(update_fields=["position"])

    target_manor, target_display_name = _get_manor_and_display_name(target_user_id)
    if target_manor is None:
        logger.warning(
            "Guild demote-admin follow-up message skipped because manor missing: target_user_id=%s guild=%s",
            target_user_id,
            guild_name,
        )
    else:
        _run_followup(
            "demote-admin message",
            lambda: create_message(
                manor=target_manor,
                kind="system",
                title="职位变更",
                body="您已被罢免管理员职位，降为普通成员。",
            ),
            target_user_id=target_user_id,
            guild=guild_name,
        )

    _run_followup(
        "demote-admin announcement",
        lambda: create_announcement(
            guild,
            "system",
            f"{target_display_name}卸任管理员职位。",
        ),
        target_user_id=target_user_id,
        guild=guild_name,
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
    from guilds.models import GuildMember

    # 验证当前用户是帮主
    if not current_leader_member.is_leader:
        raise ValueError("您不是帮主")

    # 验证新帮主是同帮会成员
    if new_leader_member.guild_id != current_leader_member.guild_id:
        raise ValueError("只能转让给本帮会成员")

    # 验证新帮主是活跃成员
    if not new_leader_member.is_active:
        raise ValueError("该成员已离开帮会")

    guild = current_leader_member.guild
    guild_name = guild.name
    current_leader_user_id = current_leader_member.user_id
    new_leader_user_id = new_leader_member.user_id

    with transaction.atomic():
        # 使用 select_for_update 锁定两个成员记录，防止并发问题
        current_locked = GuildMember.objects.select_for_update().get(pk=current_leader_member.pk)
        new_locked = GuildMember.objects.select_for_update().get(pk=new_leader_member.pk)

        # 重新验证状态（防止并发修改）
        if not current_locked.is_leader:
            raise ValueError("您不是帮主")
        if not new_locked.is_active:
            raise ValueError("该成员已离开帮会")

        # 原帮主降为普通成员
        current_locked.position = "member"
        current_locked.save(update_fields=["position"])

        # 新帮主上任
        new_locked.position = "leader"
        new_locked.save(update_fields=["position"])

    _, current_leader_display_name = _get_manor_and_display_name(current_leader_user_id)
    new_leader_manor, new_leader_display_name = _get_manor_and_display_name(new_leader_user_id)
    if new_leader_manor is None:
        logger.warning(
            "Guild transfer-leadership follow-up message skipped because manor missing: new_leader_user_id=%s guild=%s",
            new_leader_user_id,
            guild_name,
        )
    else:
        _run_followup(
            "transfer-leadership message",
            lambda: create_message(
                manor=new_leader_manor,
                kind="system",
                title="职位变更",
                body=f"您已成为帮会【{guild_name}】的新任帮主！",
            ),
            new_leader_user_id=new_leader_user_id,
            guild=guild_name,
        )

    _run_followup(
        "transfer-leadership announcement",
        lambda: create_announcement(
            guild,
            "system",
            f"{current_leader_display_name}将帮主之位传给了{new_leader_display_name}！",
        ),
        current_leader_user_id=current_leader_user_id,
        new_leader_user_id=new_leader_user_id,
        guild=guild_name,
    )


def get_member_rankings(guild, ranking_type="total"):
    """
    获取成员排行榜

    Args:
        guild: Guild对象
        ranking_type: 'total'(总贡献) 或 'weekly'(本周贡献)

    Returns:
        QuerySet
    """
    members = guild.members.filter(is_active=True).select_related("user", "user__manor")

    if ranking_type == "weekly":
        return members.order_by("-weekly_contribution", "-total_contribution")[:10]
    else:
        return members.order_by("-total_contribution", "-joined_at")[:10]
