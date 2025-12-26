# guilds/services/guild.py

import re

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from gameplay.models import Manor

from ..models import Guild, GuildAnnouncement, GuildMember, GuildTechnology


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


# 配置常量
GUILD_CREATION_COST = {'gold_bar': 2}
GUILD_UPGRADE_BASE_COST = 5  # 金条

# 帮会名称校验常量
GUILD_NAME_MIN_LENGTH = 2
GUILD_NAME_MAX_LENGTH = 16
# 允许：中文、英文、数字、下划线
GUILD_NAME_PATTERN = re.compile(r'^[\u4e00-\u9fa5a-zA-Z0-9_]+$')


def validate_guild_name(name: str) -> None:
    """
    校验帮会名称

    Args:
        name: 帮会名称

    Raises:
        ValueError: 校验失败时抛出
    """
    if not name or not name.strip():
        raise ValueError("帮会名称不能为空")

    name = name.strip()

    if len(name) < GUILD_NAME_MIN_LENGTH:
        raise ValueError(f"帮会名称至少需要{GUILD_NAME_MIN_LENGTH}个字符")

    if len(name) > GUILD_NAME_MAX_LENGTH:
        raise ValueError(f"帮会名称最多{GUILD_NAME_MAX_LENGTH}个字符")

    if not GUILD_NAME_PATTERN.match(name):
        raise ValueError("帮会名称只能包含中文、英文、数字和下划线")


def create_guild(user, name, description='', emblem='default'):
    """
    创建帮会

    Args:
        user: 创建者User对象
        name: 帮会名称
        description: 帮会简介
        emblem: 帮会徽章key

    Returns:
        Guild对象

    Raises:
        ValueError: 验证失败
    """
    from gameplay.models import InventoryItem, ItemTemplate

    # 验证用户是否已加入帮会（检查是否有活跃的成员记录）
    existing_membership = GuildMember.objects.filter(user=user, is_active=True).first()
    if existing_membership:
        raise ValueError("您已加入帮会，无法创建新帮会")

    # 清理可能存在的非活跃成员记录（解决 OneToOneField 唯一约束问题）
    GuildMember.objects.filter(user=user, is_active=False).delete()

    # 校验帮会名称格式
    name = name.strip() if name else ""
    validate_guild_name(name)

    # 验证帮会名称唯一性
    if Guild.objects.filter(name=name, is_active=True).exists():
        raise ValueError("帮会名称已存在")

    # 验证金条（从仓库）
    manor = Manor.objects.get(user=user)
    required_gold_bars = GUILD_CREATION_COST['gold_bar']

    try:
        gold_bar_template = ItemTemplate.objects.get(key='gold_bar')
        gold_bar_item = InventoryItem.objects.filter(
            manor=manor,
            template=gold_bar_template,
            storage_location='warehouse'
        ).first()

        if not gold_bar_item or gold_bar_item.quantity < required_gold_bars:
            raise ValueError(f"金条不足，需要{required_gold_bars}金条")
    except ItemTemplate.DoesNotExist:
        raise ValueError("金条物品不存在，请联系管理员")

    with transaction.atomic():
        # 消耗金条
        gold_bar_item.quantity -= required_gold_bars
        if gold_bar_item.quantity <= 0:
            gold_bar_item.delete()
        else:
            gold_bar_item.save(update_fields=['quantity'])

        # 创建帮会
        guild = Guild.objects.create(
            name=name,
            description=description,
            emblem=emblem,
            founder=user,
            level=1,
        )

        # 创建者自动成为帮主
        GuildMember.objects.create(
            guild=guild,
            user=user,
            position='leader',
        )

        # 初始化帮会科技（等级0）
        initialize_guild_technologies(guild)

        # 发布系统公告
        create_announcement(
            guild,
            'system',
            f"帮会成立！帮主{manor.display_name}创建了{name}！",
        )

    return guild


def upgrade_guild(guild, operator):
    """
    升级帮会

    Args:
        guild: Guild对象
        operator: 操作者User对象

    Raises:
        ValueError: 验证失败
    """
    # 验证权限
    membership = _get_active_membership(guild, operator, "只有帮主可以升级帮会")
    if not membership.is_leader:
        raise ValueError("只有帮主可以升级帮会")

    # 验证等级
    if guild.level >= 10:
        raise ValueError("帮会已达最高等级")

    # 计算升级成本
    cost = calculate_guild_upgrade_cost(guild.level)

    # 验证帮会资源
    if guild.gold_bar < cost:
        raise ValueError(f"帮会金条不足，需要{cost}金条")

    # 并发安全的事务处理
    with transaction.atomic():
        # 步骤1：锁定帮会，防止并发升级
        guild_locked = Guild.objects.select_for_update().get(pk=guild.pk)

        # 步骤2：在锁内重新验证条件，防止并发穿透
        if guild_locked.level >= 10:
            raise ValueError("帮会已达最高等级")

        if guild_locked.gold_bar < cost:
            raise ValueError(f"帮会金条不足，需要{cost}金条")

        # 步骤3：使用F()表达式原子性地扣除金条并提升等级
        Guild.objects.filter(pk=guild_locked.pk).update(
            gold_bar=F("gold_bar") - cost, level=F("level") + 1
        )

        # 刷新对象以获取更新后的值（用于日志和公告）
        guild_locked.refresh_from_db(fields=["level", "gold_bar"])

        # 步骤4：记录资源流水
        from ..models import GuildResourceLog

        GuildResourceLog.objects.create(
            guild=guild_locked,
            action='upgrade_guild',
            gold_bar_change=-cost,
            related_user=operator,
            note=f"帮会升级至{guild_locked.level}级",
        )

        # 步骤5：获取操作者庄园名称并发布公告
        operator_manor = Manor.objects.get(user=operator)
        create_announcement(
            guild_locked,
            'system',
            f"{operator_manor.display_name}将帮会提升至{guild_locked.level}级！成员上限增加至{guild_locked.member_capacity}人。",
        )


def calculate_guild_upgrade_cost(current_level):
    """计算帮会升级成本"""
    if current_level >= 10:
        return None
    return GUILD_UPGRADE_BASE_COST * (2 ** (current_level - 1))


def initialize_guild_technologies(guild):
    """初始化帮会科技"""
    tech_configs = [
        # 生产类
        ('equipment_forge', 'production', 5),
        ('experience_refine', 'production', 5),
        ('resource_supply', 'production', 5),
        # 战斗类
        ('military_study', 'combat', 5),
        ('troop_tactics', 'combat', 5),
        # 福利类
        ('resource_boost', 'welfare', 5),
        ('march_speed', 'welfare', 5),
    ]

    technologies_to_create = [
        GuildTechnology(
            guild=guild,
            tech_key=tech_key,
            category=category,
            level=0,
            max_level=max_level,
        )
        for tech_key, category, max_level in tech_configs
    ]
    GuildTechnology.objects.bulk_create(technologies_to_create)


def disband_guild(guild, operator):
    """
    解散帮会

    Args:
        guild: Guild对象
        operator: 操作者User对象

    Raises:
        ValueError: 验证失败
    """
    # 验证权限
    membership = _get_active_membership(guild, operator, "只有帮主可以解散帮会")
    if not membership.is_leader:
        raise ValueError("只有帮主可以解散帮会")

    # 预加载成员 user_id 和对应的 manor（避免事务中的 N+1 查询）
    member_user_ids = list(
        guild.members.filter(is_active=True).values_list('user_id', flat=True)
    )
    user_to_manor = {
        m.user_id: m
        for m in Manor.objects.filter(user_id__in=member_user_ids)
    }
    guild_name = guild.name  # 缓存名称，事务外使用

    with transaction.atomic():
        # 标记帮会为不活跃
        guild.is_active = False
        guild.save(update_fields=['is_active'])

        # 标记所有成员为离开
        guild.members.filter(is_active=True).update(
            is_active=False,
            left_at=timezone.now(),
        )

    # 发送解散通知（移到事务外，避免长事务）
    from gameplay.services.messages import bulk_create_messages

    messages_data = []
    for user_id in member_user_ids:
        manor = user_to_manor.get(user_id)
        if manor:
            messages_data.append({
                "manor": manor,
                "kind": "system",
                "title": "帮会解散通知",
                "body": f"您所在的帮会【{guild_name}】已被帮主解散。",
            })

    if messages_data:
        bulk_create_messages(messages_data)


def get_guild_list(ordering='-level', search=None, page=1, page_size=20):
    """
    获取帮会列表

    Args:
        ordering: 排序字段
        search: 搜索关键词
        page: 页码
        page_size: 每页数量

    Returns:
        QuerySet (带 _member_count 注解，优化 N+1)
    """
    # 使用自定义管理器预加载成员数（优化模板中的 N+1）
    queryset = Guild.objects.with_member_count().filter(is_active=True)

    if search:
        queryset = queryset.filter(name__icontains=search)

    # 如果按成员数排序，使用预加载的 _member_count
    if ordering in ['-current_member_count', 'current_member_count']:
        if ordering == '-current_member_count':
            queryset = queryset.order_by('-_member_count')
        else:
            queryset = queryset.order_by('_member_count')
    else:
        queryset = queryset.order_by(ordering)

    # 简单分页
    start = (page - 1) * page_size
    end = start + page_size

    return queryset[start:end]


def create_announcement(guild, type, content, author=None):
    """
    创建帮会公告

    Args:
        guild: Guild对象
        type: 'system' 或 'leader'
        content: 公告内容
        author: 发布人User对象（leader类型必须）
    """
    GuildAnnouncement.objects.create(
        guild=guild,
        type=type,
        content=content,
        author=author,
    )

    # 保留最近10条公告
    old_announcements = guild.announcements.all()[10:]
    if old_announcements:
        announcement_ids = [a.id for a in old_announcements]
        GuildAnnouncement.objects.filter(id__in=announcement_ids).delete()
