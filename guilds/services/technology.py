# guilds/services/technology.py

from django.db import transaction
from django.db.models import F

from gameplay.models import Manor

from ..models import Guild, GuildMember, GuildResourceLog, GuildTechnology
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

# 科技升级成本配置
TECH_UPGRADE_COSTS = {
    # 生产类科技（成本较低）
    'equipment_forge': {'silver': 5000, 'grain': 2000, 'gold_bar': 1},
    'experience_refine': {'silver': 5000, 'grain': 2000, 'gold_bar': 1},
    'resource_supply': {'silver': 4000, 'grain': 3000, 'gold_bar': 1},

    # 战斗类科技（成本中等）
    'military_study': {'silver': 8000, 'grain': 3000, 'gold_bar': 2},
    'troop_tactics': {'silver': 8000, 'grain': 3000, 'gold_bar': 2},

    # 福利类科技（成本较高）
    'resource_boost': {'silver': 10000, 'grain': 5000, 'gold_bar': 3},
    'march_speed': {'silver': 10000, 'grain': 5000, 'gold_bar': 3},
}

# 科技名称映射
TECH_NAMES = {
    'equipment_forge': '装备锻造',
    'experience_refine': '经验炼制',
    'resource_supply': '资源补给',
    'military_study': '兵法研习',
    'troop_tactics': '强兵战术',
    'resource_boost': '资源增产',
    'march_speed': '行军加速',
}


def calculate_tech_upgrade_cost(tech_key, current_level):
    """
    计算科技升级成本

    Args:
        tech_key: 科技标识
        current_level: 当前等级

    Returns:
        dict: {'silver': xxx, 'grain': xxx, 'gold_bar': xxx}
    """
    base = TECH_UPGRADE_COSTS.get(tech_key, {'silver': 5000, 'grain': 2000, 'gold_bar': 1})
    multiplier = 2 ** current_level  # 指数增长

    return {
        'silver': base['silver'] * multiplier,
        'grain': base['grain'] * multiplier,
        'gold_bar': base['gold_bar'] * multiplier,
    }


def upgrade_technology(guild, tech_key, operator):
    """
    升级帮会科技

    Args:
        guild: Guild对象
        tech_key: 科技标识
        operator: 操作者User对象

    Raises:
        ValueError: 验证失败
    """
    # 验证权限
    membership = _get_active_membership(guild, operator, "只有帮主和管理员可以升级科技")
    if not membership.can_manage:
        raise ValueError("只有帮主和管理员可以升级科技")

    # 获取科技
    try:
        tech = GuildTechnology.objects.get(guild=guild, tech_key=tech_key)
    except GuildTechnology.DoesNotExist:
        raise ValueError("科技不存在")

    # 验证是否可升级
    if not tech.can_upgrade:
        raise ValueError("科技已达最高等级")

    # 计算升级成本
    cost = calculate_tech_upgrade_cost(tech_key, tech.level)

    # 验证帮会资源
    if guild.silver < cost['silver']:
        raise ValueError(f"帮会银两不足，需要{cost['silver']}")
    if guild.grain < cost['grain']:
        raise ValueError(f"帮会粮食不足，需要{cost['grain']}")
    if guild.gold_bar < cost['gold_bar']:
        raise ValueError(f"帮会金条不足，需要{cost['gold_bar']}")

    # 并发安全的事务处理
    with transaction.atomic():
        # 步骤1：锁定帮会和科技，防止并发升级
        guild_locked = Guild.objects.select_for_update().get(pk=guild.pk)
        tech_locked = GuildTechnology.objects.select_for_update().get(pk=tech.pk)

        # 步骤2：在锁内重新验证条件，防止并发穿透
        if not tech_locked.can_upgrade:
            raise ValueError("科技已达最高等级")

        if guild_locked.silver < cost['silver']:
            raise ValueError(f"帮会银两不足，需要{cost['silver']}")
        if guild_locked.grain < cost['grain']:
            raise ValueError(f"帮会粮食不足，需要{cost['grain']}")
        if guild_locked.gold_bar < cost['gold_bar']:
            raise ValueError(f"帮会金条不足，需要{cost['gold_bar']}")

        # 步骤3：使用F()表达式原子性地扣除帮会资源
        Guild.objects.filter(pk=guild_locked.pk).update(
            silver=F("silver") - cost['silver'],
            grain=F("grain") - cost['grain'],
            gold_bar=F("gold_bar") - cost['gold_bar'],
        )

        # 步骤4：使用F()表达式原子性地升级科技
        GuildTechnology.objects.filter(pk=tech_locked.pk).update(level=F("level") + 1)

        # 刷新对象以获取更新后的值（用于日志和公告）
        tech_locked.refresh_from_db(fields=["level"])

        # 步骤5：记录资源流水
        GuildResourceLog.objects.create(
            guild=guild_locked,
            action='tech_upgrade',
            silver_change=-cost['silver'],
            grain_change=-cost['grain'],
            gold_bar_change=-cost['gold_bar'],
            related_user=operator,
            note=f"升级{TECH_NAMES.get(tech_key, tech_key)}至{tech_locked.level}级",
        )

        # 步骤6：获取操作者庄园名称并发布公告
        operator_manor = Manor.objects.get(user=operator)
        create_announcement(
            guild_locked,
            'system',
            f"{operator_manor.display_name}将{TECH_NAMES.get(tech_key, tech_key)}升至{tech_locked.level}级！",
        )


def get_guild_tech_level(guild, tech_key):
    """
    获取帮会科技等级

    Args:
        guild: Guild对象
        tech_key: 科技标识

    Returns:
        int: 科技等级
    """
    try:
        tech = GuildTechnology.objects.get(guild=guild, tech_key=tech_key)
        return tech.level
    except GuildTechnology.DoesNotExist:
        return 0


def get_tech_bonus(guild, bonus_type):
    """
    获取科技加成

    Args:
        guild: Guild对象
        bonus_type: 加成类型

    Returns:
        float: 加成系数（如0.1表示10%加成）
    """
    bonus = 0.0

    if bonus_type == 'guest_force':
        # 兵法研习 - 武力加成
        level = get_guild_tech_level(guild, 'military_study')
        if level >= 1:
            bonus += 0.02 * min(level, 2)  # Lv1-2: 每级+2%
        if level >= 3:
            bonus += 0.02 * (level - 2)  # Lv3+: 每级+2%

    elif bonus_type == 'guest_intellect':
        # 兵法研习 - 智力加成
        level = get_guild_tech_level(guild, 'military_study')
        if level >= 3:
            bonus += 0.02 * (level - 2)  # Lv3+: 每级+2%

    elif bonus_type == 'guest_defense':
        # 兵法研习 - 防御加成
        level = get_guild_tech_level(guild, 'military_study')
        if level >= 5:
            bonus += 0.02  # Lv5: +2%

    elif bonus_type == 'troop_attack':
        # 强兵战术 - 兵种攻击加成
        level = get_guild_tech_level(guild, 'troop_tactics')
        bonus += 0.03 * level  # 每级+3%

    elif bonus_type == 'troop_defense':
        # 强兵战术 - 兵种防御加成
        level = get_guild_tech_level(guild, 'troop_tactics')
        if level >= 3:
            bonus += 0.03 * (level - 2)  # Lv3+: 每级+3%

    elif bonus_type == 'troop_hp':
        # 强兵战术 - 兵种生命加成
        level = get_guild_tech_level(guild, 'troop_tactics')
        if level >= 5:
            bonus += 0.05  # Lv5: +5%

    elif bonus_type == 'resource_production':
        # 资源增产 - 资源产出加成
        level = get_guild_tech_level(guild, 'resource_boost')
        bonus += 0.05 * level  # 每级+5%

    elif bonus_type == 'march_speed':
        # 行军加速 - 行军时间减少
        level = get_guild_tech_level(guild, 'march_speed')
        bonus += 0.05 * level  # 每级-5%

    return bonus


def apply_guild_bonus_to_guest(guest):
    """
    应用帮会科技加成到门客

    Args:
        guest: Guest对象

    Returns:
        dict: 加成后的属性
    """
    # 检查玩家是否在帮会中
    user = guest.manor.user
    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        return {
            'force': guest.force,
            'intellect': guest.intellect,
            'defense': guest.defense,
        }

    guild = user.guild_membership.guild

    # 应用加成
    force_bonus = get_tech_bonus(guild, 'guest_force')
    intellect_bonus = get_tech_bonus(guild, 'guest_intellect')
    defense_bonus = get_tech_bonus(guild, 'guest_defense')

    return {
        'force': int(guest.force * (1 + force_bonus)),
        'intellect': int(guest.intellect * (1 + intellect_bonus)),
        'defense': int(guest.defense * (1 + defense_bonus)),
    }


def apply_guild_bonus_to_troop(troop_stats, user):
    """
    应用帮会科技加成到兵种

    Args:
        troop_stats: dict - 兵种属性字典
        user: User对象

    Returns:
        dict: 加成后的兵种属性
    """
    # 检查玩家是否在帮会中
    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        return troop_stats

    guild = user.guild_membership.guild

    # 应用加成
    attack_bonus = get_tech_bonus(guild, 'troop_attack')
    defense_bonus = get_tech_bonus(guild, 'troop_defense')
    hp_bonus = get_tech_bonus(guild, 'troop_hp')

    return {
        'attack': int(troop_stats.get('attack', 0) * (1 + attack_bonus)),
        'defense': int(troop_stats.get('defense', 0) * (1 + defense_bonus)),
        'hp': int(troop_stats.get('hp', 0) * (1 + hp_bonus)),
    }
