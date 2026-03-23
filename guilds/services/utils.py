"""
帮会服务层通用辅助函数
"""

from core.exceptions import GuildMembershipError

from ..models import Guild, GuildMember


def get_active_membership(guild: Guild, user, error_msg: str = "您不是该帮会成员") -> GuildMember:
    """
    获取用户在指定帮会的有效成员记录

    Args:
        guild: 帮会对象
        user: 用户对象
        error_msg: 找不到成员时的错误消息

    Returns:
        GuildMember对象

    Raises:
        GuildMembershipError: 用户不是该帮会的活跃成员
    """
    try:
        return GuildMember.objects.get(guild=guild, user=user, is_active=True)
    except GuildMember.DoesNotExist:
        raise GuildMembershipError(error_msg)
