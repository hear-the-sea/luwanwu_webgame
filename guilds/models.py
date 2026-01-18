from django.db import models
from django.db.models import Count, Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.validators import MinLengthValidator, MaxLengthValidator

User = get_user_model()


class GuildManager(models.Manager):
    """Guild 自定义管理器，提供性能优化查询方法"""

    def with_member_count(self):
        """
        预加载活跃成员数（优化 N+1 查询）

        返回带有 _member_count 注解的 QuerySet。
        注意：使用此方法后，current_member_count property 会自动使用预加载的值。

        示例：
            guilds = Guild.objects.with_member_count().filter(is_active=True)[:20]
            for guild in guilds:
                print(guild.current_member_count)  # 无额外查询
        """
        return self.annotate(
            _member_count=Count('members', filter=Q(members__is_active=True))
        )


class Guild(models.Model):
    """帮会主体"""

    # 基础信息
    name = models.CharField(
        max_length=50,
        unique=True,
        validators=[MinLengthValidator(2), MaxLengthValidator(12)],
        verbose_name="帮会名称",
        help_text="2-12个字符"
    )
    description = models.TextField(
        max_length=200,
        blank=True,
        verbose_name="帮会简介"
    )
    emblem = models.CharField(
        max_length=50,
        default='default',
        verbose_name="帮会徽章",
        help_text="徽章图标key"
    )

    # 创建信息
    founder = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='founded_guilds',
        verbose_name="创建者"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    # 等级与容量
    level = models.PositiveIntegerField(
        default=1,
        verbose_name="帮会等级"
    )

    # 资源池
    silver = models.PositiveIntegerField(
        default=0,
        verbose_name="银两"
    )
    grain = models.PositiveIntegerField(
        default=0,
        verbose_name="粮食"
    )
    gold_bar = models.PositiveIntegerField(
        default=0,
        verbose_name="金条"
    )

    # 状态
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否活跃"
    )
    auto_accept = models.BooleanField(
        default=False,
        verbose_name="自动接受申请"
    )

    # 自定义管理器
    objects = GuildManager()

    class Meta:
        db_table = 'guilds'
        verbose_name = '帮会'
        verbose_name_plural = '帮会'
        ordering = ['-level', '-created_at']

    def __str__(self):
        return f"{self.name} (Lv.{self.level})"

    @property
    def member_capacity(self):
        """成员容量: 10 + (等级-1) * 2"""
        return 10 + (self.level - 1) * 2

    @property
    def current_member_count(self):
        """
        当前成员数

        优化说明：
        - 如果使用 Guild.objects.with_member_count() 查询，会使用预加载的值
        - 否则会执行一次 count() 查询（用于单个对象或未预加载的情况）
        """
        # 优先使用预加载的注解值
        if hasattr(self, '_member_count'):
            return self._member_count
        # 降级为直接查询
        return self.members.filter(is_active=True).count()

    @property
    def is_full(self):
        """是否已满员"""
        return self.current_member_count >= self.member_capacity

    def get_leader(self):
        """获取帮主"""
        return self.members.filter(
            is_active=True,
            position='leader'
        ).select_related('user__manor').first()

    def get_admins(self):
        """获取管理员列表"""
        return self.members.filter(
            is_active=True,
            position='admin'
        ).select_related('user__manor')

    def can_appoint_admin(self):
        """是否可以任命管理员"""
        return self.get_admins().count() < 2


class GuildMember(models.Model):
    """帮会成员"""

    POSITION_CHOICES = [
        ('leader', '帮主'),
        ('admin', '管理员'),
        ('member', '成员'),
    ]

    guild = models.ForeignKey(
        Guild,
        on_delete=models.CASCADE,
        related_name='members',
        verbose_name="所属帮会"
    )
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='guild_membership',
        verbose_name="玩家"
    )
    position = models.CharField(
        max_length=10,
        choices=POSITION_CHOICES,
        default='member',
        verbose_name="职位"
    )

    # 贡献统计
    total_contribution = models.PositiveIntegerField(
        default=0,
        verbose_name="总贡献",
        help_text="历史累计贡献（包括已消费的）"
    )
    current_contribution = models.PositiveIntegerField(
        default=0,
        verbose_name="当前贡献",
        help_text="可用于兑换的贡献"
    )
    weekly_contribution = models.PositiveIntegerField(
        default=0,
        verbose_name="本周贡献",
        help_text="每周一0点重置"
    )
    weekly_reset_at = models.DateField(
        default=timezone.now,
        verbose_name="本周重置时间"
    )

    # 时间记录
    joined_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="加入时间"
    )
    last_active_at = models.DateTimeField(
        auto_now=True,
        verbose_name="最后活跃时间"
    )

    # 状态
    is_active = models.BooleanField(
        default=True,
        verbose_name="是否在帮"
    )
    left_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="离开时间"
    )

    # 捐赠限制（每日）
    daily_donation_silver = models.PositiveIntegerField(
        default=0,
        verbose_name="今日捐赠银两"
    )
    daily_donation_grain = models.PositiveIntegerField(
        default=0,
        verbose_name="今日捐赠粮食"
    )
    daily_donation_reset_at = models.DateField(
        default=timezone.now,
        verbose_name="每日捐赠重置时间"
    )

    # 兑换限制（每日）
    daily_exchange_count = models.PositiveIntegerField(
        default=0,
        verbose_name="今日兑换次数"
    )
    daily_exchange_reset_at = models.DateField(
        default=timezone.now,
        verbose_name="每日兑换重置时间"
    )

    class Meta:
        db_table = 'guild_members'
        verbose_name = '帮会成员'
        verbose_name_plural = '帮会成员'
        unique_together = [['guild', 'user']]
        ordering = ['-position', '-total_contribution']
        indexes = [
            models.Index(fields=['guild', 'is_active'], name='guildmember_guild_active_idx'),
            models.Index(fields=['guild', 'position', 'is_active'], name='guildmember_guild_pos_idx'),
        ]

    def __str__(self):
        return f"{self.user.username} @ {self.guild.name} ({self.get_position_display()})"

    @property
    def is_leader(self):
        return self.position == 'leader'

    @property
    def is_admin(self):
        return self.position == 'admin'

    @property
    def can_manage(self):
        """是否有管理权限"""
        return self.position in ['leader', 'admin']

    def reset_weekly_contribution(self):
        """重置本周贡献"""
        self.weekly_contribution = 0
        self.weekly_reset_at = timezone.now().date()
        self.save(update_fields=['weekly_contribution', 'weekly_reset_at'])

    def reset_daily_limits(self):
        """重置每日限制"""
        today = timezone.now().date()
        updated = False

        if self.daily_donation_reset_at < today:
            self.daily_donation_silver = 0
            self.daily_donation_grain = 0
            self.daily_donation_reset_at = today
            updated = True

        if self.daily_exchange_reset_at < today:
            self.daily_exchange_count = 0
            self.daily_exchange_reset_at = today
            updated = True

        if updated:
            self.save()


class GuildTechnology(models.Model):
    """帮会科技"""

    CATEGORY_CHOICES = [
        ('production', '生产类'),
        ('combat', '战斗类'),
        ('welfare', '福利类'),
    ]

    guild = models.ForeignKey(
        Guild,
        on_delete=models.CASCADE,
        related_name='technologies',
        verbose_name="所属帮会"
    )
    tech_key = models.CharField(
        max_length=50,
        verbose_name="科技标识",
        help_text="如: equipment_forge, military_study"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='production',
        verbose_name="科技分类"
    )
    level = models.PositiveIntegerField(
        default=0,
        verbose_name="科技等级"
    )
    max_level = models.PositiveIntegerField(
        default=5,
        verbose_name="最高等级"
    )

    # 最后产出时间（仅生产类科技）
    last_production_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="最后产出时间"
    )

    class Meta:
        db_table = 'guild_technologies'
        verbose_name = '帮会科技'
        verbose_name_plural = '帮会科技'
        unique_together = [['guild', 'tech_key']]

    def __str__(self):
        return f"{self.guild.name} - {self.tech_key} Lv.{self.level}"

    @property
    def can_upgrade(self):
        """是否可升级"""
        return self.level < self.max_level


class GuildWarehouse(models.Model):
    """帮会仓库"""

    guild = models.ForeignKey(
        Guild,
        on_delete=models.CASCADE,
        related_name='warehouse_items',
        verbose_name="所属帮会"
    )
    item_key = models.CharField(
        max_length=100,
        verbose_name="物品key",
        help_text="对应ItemTemplate的key"
    )
    quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="数量"
    )
    contribution_cost = models.PositiveIntegerField(
        default=0,
        verbose_name="兑换成本（贡献度）"
    )

    # 统计
    total_produced = models.PositiveIntegerField(
        default=0,
        verbose_name="总产出数量"
    )
    total_exchanged = models.PositiveIntegerField(
        default=0,
        verbose_name="总兑换数量"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间"
    )

    class Meta:
        db_table = 'guild_warehouse'
        verbose_name = '帮会仓库'
        verbose_name_plural = '帮会仓库'
        unique_together = [['guild', 'item_key']]
        indexes = [
            models.Index(fields=['guild', '-contribution_cost'], name='guildwh_guild_contrib_idx'),
        ]

    def __str__(self):
        return f"{self.guild.name} - {self.item_key} x{self.quantity}"

    @property
    def is_available(self):
        """是否有库存"""
        return self.quantity > 0


class GuildExchangeLog(models.Model):
    """兑换日志"""

    guild = models.ForeignKey(
        Guild,
        on_delete=models.CASCADE,
        related_name='exchange_logs',
        verbose_name="所属帮会"
    )
    member = models.ForeignKey(
        GuildMember,
        on_delete=models.CASCADE,
        related_name='exchange_logs',
        verbose_name="兑换成员"
    )
    item_key = models.CharField(
        max_length=100,
        verbose_name="物品key"
    )
    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name="兑换数量"
    )
    contribution_cost = models.PositiveIntegerField(
        verbose_name="消耗贡献"
    )
    exchanged_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="兑换时间"
    )

    class Meta:
        db_table = 'guild_exchange_logs'
        verbose_name = '兑换日志'
        verbose_name_plural = '兑换日志'
        ordering = ['-exchanged_at']

    def __str__(self):
        return f"{self.member.user.username} - {self.item_key} x{self.quantity}"


class GuildApplication(models.Model):
    """入帮申请"""

    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('cancelled', '已取消'),
    ]

    guild = models.ForeignKey(
        Guild,
        on_delete=models.CASCADE,
        related_name='applications',
        verbose_name="目标帮会"
    )
    applicant = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='guild_applications',
        verbose_name="申请人"
    )
    message = models.TextField(
        max_length=200,
        blank=True,
        verbose_name="申请留言"
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="状态"
    )

    # 审批信息
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_applications',
        verbose_name="审批人"
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="审批时间"
    )
    review_note = models.TextField(
        max_length=200,
        blank=True,
        verbose_name="审批备注"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="申请时间"
    )

    class Meta:
        db_table = 'guild_applications'
        verbose_name = '入帮申请'
        verbose_name_plural = '入帮申请'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['guild', 'status', '-created_at'], name='gapp_guild_sts_cr_idx'),
        ]

    def __str__(self):
        return f"{self.applicant.username} -> {self.guild.name} ({self.get_status_display()})"


class GuildAnnouncement(models.Model):
    """帮会公告"""

    TYPE_CHOICES = [
        ('system', '系统公告'),
        ('leader', '帮主公告'),
    ]

    guild = models.ForeignKey(
        Guild,
        on_delete=models.CASCADE,
        related_name='announcements',
        verbose_name="所属帮会"
    )
    type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default='system',
        verbose_name="公告类型"
    )
    content = models.TextField(
        max_length=500,
        verbose_name="公告内容"
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="发布人"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="发布时间"
    )

    class Meta:
        db_table = 'guild_announcements'
        verbose_name = '帮会公告'
        verbose_name_plural = '帮会公告'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.guild.name} - {self.get_type_display()} @ {self.created_at}"


class GuildDonationLog(models.Model):
    """捐赠日志"""

    RESOURCE_CHOICES = [
        ('silver', '银两'),
        ('grain', '粮食'),
    ]

    guild = models.ForeignKey(
        Guild,
        on_delete=models.CASCADE,
        related_name='donation_logs',
        verbose_name="所属帮会"
    )
    member = models.ForeignKey(
        GuildMember,
        on_delete=models.CASCADE,
        related_name='donation_logs',
        verbose_name="捐赠成员"
    )
    resource_type = models.CharField(
        max_length=10,
        choices=RESOURCE_CHOICES,
        verbose_name="资源类型"
    )
    amount = models.PositiveIntegerField(
        verbose_name="捐赠数量"
    )
    contribution_gained = models.PositiveIntegerField(
        verbose_name="获得贡献"
    )
    donated_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="捐赠时间"
    )

    class Meta:
        db_table = 'guild_donation_logs'
        verbose_name = '捐赠日志'
        verbose_name_plural = '捐赠日志'
        ordering = ['-donated_at']

    def __str__(self):
        return f"{self.member.user.username} - {self.get_resource_type_display()} x{self.amount}"


class GuildResourceLog(models.Model):
    """帮会资源流水"""

    ACTION_CHOICES = [
        ('donation', '成员捐赠'),
        ('tech_upgrade', '科技升级'),
        ('guild_upgrade', '帮会升级'),
        ('production', '科技产出'),
    ]

    guild = models.ForeignKey(
        Guild,
        on_delete=models.CASCADE,
        related_name='resource_logs',
        verbose_name="所属帮会"
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        verbose_name="操作类型"
    )
    silver_change = models.IntegerField(
        default=0,
        verbose_name="银两变化"
    )
    grain_change = models.IntegerField(
        default=0,
        verbose_name="粮食变化"
    )
    gold_bar_change = models.IntegerField(
        default=0,
        verbose_name="金条变化"
    )
    related_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="相关玩家"
    )
    note = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="备注"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="记录时间"
    )

    class Meta:
        db_table = 'guild_resource_logs'
        verbose_name = '帮会资源流水'
        verbose_name_plural = '帮会资源流水'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.guild.name} - {self.get_action_display()} @ {self.created_at}"
