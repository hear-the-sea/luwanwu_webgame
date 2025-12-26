"""
帮会系统测试
"""

import pytest

from gameplay.models import Manor, ItemTemplate, InventoryItem
from guilds.models import GuildMember
from guilds.services import guild as guild_service
from guilds.services import member as member_service
from guilds.services import contribution as contribution_service


@pytest.fixture
def gold_bar_template(db):
    """确保金条模板存在"""
    template, _ = ItemTemplate.objects.get_or_create(
        key='gold_bar',
        defaults={
            'name': '金条',
            'effect_type': 'none',
        }
    )
    return template


@pytest.fixture
def user_with_gold_bars(django_user_model, gold_bar_template):
    """创建一个拥有金条的用户"""
    user = django_user_model.objects.create_user(username="guild_test_user", password="pass12345")
    from gameplay.services import ensure_manor
    manor = ensure_manor(user)

    # 添加金条到仓库
    InventoryItem.objects.create(
        manor=manor,
        template=gold_bar_template,
        quantity=10,
        storage_location='warehouse'
    )
    return user


@pytest.fixture
def second_user(django_user_model):
    """创建第二个用户用于测试申请加入"""
    user = django_user_model.objects.create_user(username="guild_test_user2", password="pass12345")
    from gameplay.services import ensure_manor
    ensure_manor(user)
    return user


@pytest.mark.django_db
class TestGuildCreation:
    """帮会创建测试"""

    def test_create_guild_success(self, user_with_gold_bars):
        """测试成功创建帮会"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="测试帮会",
            description="这是一个测试帮会"
        )

        assert guild is not None
        assert guild.name == "测试帮会"
        assert guild.level == 1
        assert guild.is_active is True

        # 验证创建者成为帮主
        membership = GuildMember.objects.get(user=user_with_gold_bars, guild=guild)
        assert membership.position == 'leader'
        assert membership.is_active is True

        # 验证科技初始化
        assert guild.technologies.count() == 7

    def test_create_guild_duplicate_name(self, user_with_gold_bars, django_user_model, gold_bar_template):
        """测试重复帮会名称"""
        guild_service.create_guild(
            user=user_with_gold_bars,
            name="唯一帮会",
            description=""
        )

        # 创建第二个用户
        user2 = django_user_model.objects.create_user(username="user2", password="pass12345")
        from gameplay.services import ensure_manor
        manor2 = ensure_manor(user2)

        # 给第二个用户金条
        InventoryItem.objects.create(
            manor=manor2,
            template=gold_bar_template,
            quantity=10,
            storage_location='warehouse'
        )

        with pytest.raises(ValueError, match="帮会名称已存在"):
            guild_service.create_guild(
                user=user2,
                name="唯一帮会",
                description=""
            )

    def test_create_guild_invalid_name(self, user_with_gold_bars):
        """测试无效帮会名称"""
        # 名称太短
        with pytest.raises(ValueError, match="至少需要"):
            guild_service.create_guild(
                user=user_with_gold_bars,
                name="A",
                description=""
            )

        # 名称包含特殊字符
        with pytest.raises(ValueError, match="只能包含"):
            guild_service.create_guild(
                user=user_with_gold_bars,
                name="帮会@#$",
                description=""
            )

    def test_create_guild_insufficient_gold(self, django_user_model, gold_bar_template):
        """测试金条不足"""
        user = django_user_model.objects.create_user(username="poor_user", password="pass12345")
        from gameplay.services import ensure_manor
        ensure_manor(user)

        with pytest.raises(ValueError, match="金条不足"):
            guild_service.create_guild(
                user=user,
                name="穷人帮会",
                description=""
            )


@pytest.mark.django_db
class TestGuildMembership:
    """帮会成员管理测试"""

    def test_apply_and_approve(self, user_with_gold_bars, second_user):
        """测试申请并通过"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="招人帮会",
            description=""
        )

        # 申请加入
        application = member_service.apply_to_guild(second_user, guild, "请收留我")
        assert application.status == 'pending'

        # 批准申请
        member_service.approve_application(application, user_with_gold_bars)
        application.refresh_from_db()

        assert application.status == 'approved'

        # 验证成员已加入
        membership = GuildMember.objects.get(user=second_user, guild=guild)
        assert membership.is_active is True
        assert membership.position == 'member'

    def test_apply_to_full_guild(self, user_with_gold_bars, second_user, django_user_model):
        """测试申请已满员帮会"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="小帮会",
            description=""
        )

        # 创建足够成员让帮会满员（1级帮会容量10人）
        for i in range(9):  # 已有帮主1人，再加9人
            user = django_user_model.objects.create_user(
                username=f"filler_{i}",
                password="pass12345"
            )
            from gameplay.services import ensure_manor
            ensure_manor(user)
            GuildMember.objects.create(guild=guild, user=user, position='member')

        # 申请加入已满帮会
        with pytest.raises(ValueError, match="已满员"):
            member_service.apply_to_guild(second_user, guild, "")

    def test_kick_member(self, user_with_gold_bars, second_user):
        """测试踢出成员"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="踢人帮会",
            description=""
        )

        # 添加成员
        target_member = GuildMember.objects.create(guild=guild, user=second_user, position='member')
        member_id = target_member.id

        # 踢出成员（参数是GuildMember对象，不是guild和user）
        member_service.kick_member(target_member, user_with_gold_bars)

        # 验证成员记录已被删除（kick_member 是删除而不是设置 is_active=False）
        assert not GuildMember.objects.filter(id=member_id).exists()

    def test_leave_guild(self, user_with_gold_bars, second_user):
        """测试主动退出帮会"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="退出帮会",
            description=""
        )

        # 添加成员
        member = GuildMember.objects.create(guild=guild, user=second_user, position='member')
        member_id = member.id

        # 退出帮会（参数是GuildMember对象）
        member_service.leave_guild(member)

        # 验证成员记录已被删除（leave_guild 是删除而不是设置 is_active=False）
        assert not GuildMember.objects.filter(id=member_id).exists()

    def test_leader_cannot_leave(self, user_with_gold_bars):
        """测试帮主不能直接退出"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="帮主帮会",
            description=""
        )

        leader_member = GuildMember.objects.get(user=user_with_gold_bars, guild=guild)

        with pytest.raises(ValueError, match="帮主"):
            member_service.leave_guild(leader_member)


@pytest.mark.django_db
class TestGuildContribution:
    """帮会贡献测试"""

    def test_donate_resource(self, user_with_gold_bars):
        """测试捐赠资源"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="捐赠帮会",
            description=""
        )

        # 给用户一些银两
        manor = Manor.objects.get(user=user_with_gold_bars)
        manor.silver = 100000
        manor.save()

        member = GuildMember.objects.get(user=user_with_gold_bars, guild=guild)
        initial_contribution = member.total_contribution

        # 捐赠银两
        contribution_service.donate_resource(member, 'silver', 10000)

        member.refresh_from_db()
        guild.refresh_from_db()
        manor.refresh_from_db()

        # 验证贡献增加
        assert member.total_contribution > initial_contribution
        # 验证帮会资源增加
        assert guild.silver == 10000
        # 验证个人资源减少
        assert manor.silver == 90000

    def test_donate_exceeds_daily_limit(self, user_with_gold_bars):
        """测试超出每日捐赠限制"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="限制帮会",
            description=""
        )

        manor = Manor.objects.get(user=user_with_gold_bars)
        manor.silver = 10000000  # 足够多的银两
        manor.save()

        member = GuildMember.objects.get(user=user_with_gold_bars, guild=guild)

        # 尝试捐赠超过每日限制
        daily_limit = contribution_service.DAILY_DONATION_LIMITS.get('silver', 100000)

        with pytest.raises(ValueError, match="已达上限"):
            contribution_service.donate_resource(member, 'silver', daily_limit + 1)


@pytest.mark.django_db
class TestGuildUpgrade:
    """帮会升级测试"""

    def test_upgrade_guild(self, user_with_gold_bars):
        """测试升级帮会"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="升级帮会",
            description=""
        )

        # 给帮会足够金条
        guild.gold_bar = 100
        guild.save()

        initial_level = guild.level

        # 升级
        guild_service.upgrade_guild(guild, user_with_gold_bars)
        guild.refresh_from_db()

        assert guild.level == initial_level + 1
        assert guild.gold_bar < 100  # 消耗了金条

    def test_upgrade_max_level(self, user_with_gold_bars):
        """测试升级已满级帮会"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="满级帮会",
            description=""
        )

        guild.level = 10
        guild.gold_bar = 10000
        guild.save()

        with pytest.raises(ValueError, match="最高等级"):
            guild_service.upgrade_guild(guild, user_with_gold_bars)


@pytest.mark.django_db
class TestGuildDisband:
    """帮会解散测试"""

    def test_disband_guild(self, user_with_gold_bars, second_user):
        """测试解散帮会"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="解散帮会",
            description=""
        )

        # 添加成员
        GuildMember.objects.create(guild=guild, user=second_user, position='member')

        # 解散帮会
        guild_service.disband_guild(guild, user_with_gold_bars)
        guild.refresh_from_db()

        assert guild.is_active is False

        # 验证所有成员都被标记为不活跃
        for member in guild.members.all():
            assert member.is_active is False

    def test_non_leader_cannot_disband(self, user_with_gold_bars, second_user):
        """测试非帮主不能解散帮会"""
        guild = guild_service.create_guild(
            user=user_with_gold_bars,
            name="安全帮会",
            description=""
        )

        GuildMember.objects.create(guild=guild, user=second_user, position='member')

        with pytest.raises(ValueError, match="帮主"):
            guild_service.disband_guild(guild, second_user)
