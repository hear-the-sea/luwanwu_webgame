# guilds/services/contribution.py

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from gameplay.models import Manor, ResourceEvent
from gameplay.services.resources import spend_resources_locked

from ..constants import CONTRIBUTION_RATES, DAILY_DONATION_LIMITS, MIN_DONATION_AMOUNT
from ..models import Guild, GuildDonationLog, GuildMember, GuildResourceLog


def donate_resource(member, resource_type, amount):
    """
    捐赠资源获得贡献（并发安全版本）

    使用数据库行锁和F()表达式确保并发安全：
    - 锁定Manor防止资源透支
    - 锁定Guild防止资源覆盖
    - 锁定GuildMember防止贡献度覆盖和每日上限绕过

    锁定顺序：Manor -> Guild -> GuildMember，避免死锁

    Args:
        member: GuildMember对象
        resource_type: 'silver' 或 'grain'
        amount: 捐赠数量

    Raises:
        ValueError: 验证失败
    """
    # 验证资源类型
    if resource_type not in CONTRIBUTION_RATES:
        raise ValueError(f"不支持捐赠{resource_type}")

    # 验证捐赠数量
    if amount < MIN_DONATION_AMOUNT:
        raise ValueError(f"单次捐赠最少{MIN_DONATION_AMOUNT}单位")

    # 获取今日日期，用于重置每日统计
    today = timezone.now().date()

    # 并发安全的事务处理
    with transaction.atomic():
        # 锁定顺序：Manor -> Guild -> GuildMember，避免与资源消费等路径产生死锁
        manor = Manor.objects.select_for_update().get(user=member.user)

        # 步骤1：锁定帮会（用于增加资源）
        guild_locked = Guild.objects.select_for_update().get(pk=member.guild_id)

        # 步骤2：锁定成员并验证每日捐赠上限
        member_locked = GuildMember.objects.select_for_update().get(pk=member.pk)

        # 在锁内重置每日统计，避免并发绕过上限
        current_daily_silver = member_locked.daily_donation_silver
        current_daily_grain = member_locked.daily_donation_grain

        # 如果日期已过，重置每日计数
        if member_locked.daily_donation_reset_at is None or member_locked.daily_donation_reset_at < today:
            current_daily_silver = 0
            current_daily_grain = 0

        # 验证每日捐赠上限
        if resource_type == 'silver':
            if current_daily_silver + amount > DAILY_DONATION_LIMITS['silver']:
                raise ValueError(
                    f"今日银两捐赠已达上限（{DAILY_DONATION_LIMITS['silver']}）"
                )
            new_daily_silver = current_daily_silver + amount
            new_daily_grain = current_daily_grain
        else:  # grain
            if current_daily_grain + amount > DAILY_DONATION_LIMITS['grain']:
                raise ValueError(
                    f"今日粮食捐赠已达上限（{DAILY_DONATION_LIMITS['grain']}）"
                )
            new_daily_silver = current_daily_silver
            new_daily_grain = current_daily_grain + amount

        # 计算获得的贡献
        contribution = amount * CONTRIBUTION_RATES[resource_type]

        # 步骤3：使用统一的资源消费函数扣除玩家资源（已包含并发安全检查）
        spend_resources_locked(
            manor,
            {resource_type: amount},
            note="帮会捐献",
            reason=ResourceEvent.Reason.GUILD_DONATION
        )

        # 步骤4：使用F()表达式原子性地增加帮会资源
        Guild.objects.filter(pk=guild_locked.pk).update(
            **{resource_type: F(resource_type) + amount}
        )

        # 步骤5：使用F()表达式原子性地更新成员贡献和每日统计
        # 注意：每日计数不能用F()表达式，因为需要在重置后再累加
        GuildMember.objects.filter(pk=member_locked.pk).update(
            total_contribution=F('total_contribution') + contribution,
            current_contribution=F('current_contribution') + contribution,
            weekly_contribution=F('weekly_contribution') + contribution,
            daily_donation_silver=new_daily_silver,
            daily_donation_grain=new_daily_grain,
            daily_donation_reset_at=today,
        )

        # 步骤6：记录捐赠日志
        GuildDonationLog.objects.create(
            guild=guild_locked,
            member=member_locked,
            resource_type=resource_type,
            amount=amount,
            contribution_gained=contribution,
        )

        # 步骤7：记录资源流水
        GuildResourceLog.objects.create(
            guild=guild_locked,
            action='donation',
            silver_change=amount if resource_type == 'silver' else 0,
            grain_change=amount if resource_type == 'grain' else 0,
            related_user=member_locked.user,
            note=f"捐赠{amount}{resource_type}，获得{contribution}贡献",
        )


def reset_weekly_contributions():
    """重置所有帮会成员的本周贡献（每周一执行）"""
    from datetime import date
    today = date.today()

    members = GuildMember.objects.filter(
        is_active=True,
        weekly_reset_at__lt=today
    )

    for member in members:
        member.reset_weekly_contribution()


def get_contribution_ranking(guild, ranking_type='total', limit=10):
    """
    获取贡献排行榜

    Args:
        guild: Guild对象
        ranking_type: 'total'(总贡献) 或 'weekly'(本周贡献)
        limit: 返回数量，None表示返回所有

    Returns:
        QuerySet
    """
    members = guild.members.filter(is_active=True).select_related('user')

    if ranking_type == 'weekly':
        members = members.order_by('-weekly_contribution', '-total_contribution')
    else:
        members = members.order_by('-total_contribution', '-weekly_contribution')

    if limit is not None:
        return members[:limit]
    return members


def get_my_contribution_rank(member, ranking_type='total'):
    """
    获取我的贡献排名

    Args:
        member: GuildMember对象
        ranking_type: 'total'(总贡献) 或 'weekly'(本周贡献)

    Returns:
        dict: {'rank': 排名, 'contribution': 贡献值}
    """
    guild = member.guild
    members = guild.members.filter(is_active=True)

    if ranking_type == 'weekly':
        higher_ranked = members.filter(
            weekly_contribution__gt=member.weekly_contribution
        ).count()
        contribution = member.weekly_contribution
    else:
        higher_ranked = members.filter(
            total_contribution__gt=member.total_contribution
        ).count()
        contribution = member.total_contribution

    return {
        'rank': higher_ranked + 1,
        'contribution': contribution
    }
