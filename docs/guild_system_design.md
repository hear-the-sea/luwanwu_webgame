# 帮会系统开发文档

## 项目信息
- **项目名称**: 春秋乱世庄园主 - 帮会系统
- **版本**: v1.0
- **编写日期**: 2025-12-04
- **状态**: 待开发

---

## 一、需求概述

### 1.1 功能概述
为游戏新增帮会系统，允许玩家创建或加入帮会，通过帮会协作获得额外增益。帮会系统包括：
- 帮会创建与管理
- 成员管理与职位系统
- 贡献度系统
- 帮会科技系统
- 帮会仓库与兑换系统
- 帮会升级系统

### 1.2 核心玩法循环
```
玩家加入帮会 → 捐赠资源获得贡献 → 帮主/管理员升级科技 → 科技产出物品到帮会仓库
→ 玩家消耗贡献兑换物品 → 提升个人战力 → 捐赠更多资源 → 帮会发展壮大
```

### 1.3 设计原则
- **界面风格**: 与现有古风UI保持一致（羊皮纸配色、楷体字体）
- **代码风格**: 遵循项目现有的服务层架构（services模块）
- **数据模型**: 参考现有模型设计（如Manor、Guest等）
- **异步任务**: 使用Celery处理长耗时操作
- **消息通知**: 集成现有Message系统和WebSocket推送

---

## 二、功能详细设计

### 2.1 帮会创建与加入

#### 2.1.1 创建帮会
**前置条件**:
- 玩家未加入任何帮会
- 拥有足够的金条（初始消耗：2金条）

**创建流程**:
1. 玩家进入帮会页面，点击"创建帮会"
2. 填写帮会信息：
   - 帮会名称（2-12个字符，唯一）
   - 帮会简介（最多200字）
   - 帮会徽章（可选，从预设图标中选择）
3. 系统验证：
   - 检查金条是否充足
   - 检查名称是否重复
4. 消耗金条，创建帮会
5. 创建者自动成为帮主
6. 帮会初始等级为1，成员上限10人

**费用配置**:
```python
GUILD_CREATION_COST = {
    'gold_bar': 2  # 可在配置文件中调整
}
```

#### 2.1.2 加入帮会
**加入方式**:
1. **搜索加入**: 搜索帮会名称，查看帮会信息
2. **列表浏览**: 按等级/人数/活跃度排序浏览
3. **申请加入**: 向目标帮会发送申请

**申请流程**:
```
玩家提交申请 → 申请进入待审批列表 → 帮主/管理员审批
→ 通过：玩家加入帮会，收到系统消息
→ 拒绝：玩家收到拒绝通知
```

**自动审批**:
- 帮会可设置"自动接受"模式（无需审批）
- 自动接受时仍受成员上限限制

### 2.2 成员管理与职位系统

#### 2.2.1 职位等级
```
帮主 (Leader) - 1人
  ├─ 所有权限
  ├─ 转让帮主
  └─ 解散帮会

管理员 (Admin) - 最多2人
  ├─ 审批入帮申请
  ├─ 辞退成员
  ├─ 升级帮会科技
  └─ 使用帮会资源

成员 (Member)
  ├─ 捐赠资源
  ├─ 兑换帮会物品
  └─ 查看帮会信息
```

#### 2.2.2 职位操作
**任命管理员**:
- 帮主可任命最多2名管理员
- 被任命者收到系统消息通知

**辞退成员**:
- 帮主/管理员可辞退普通成员
- 辞退时保留该成员已获得的贡献度（用于统计）
- 被辞退成员收到系统消息

**退出帮会**:
- 普通成员可随时退出
- 管理员退出需先卸任
- 帮主退出需先转让帮主或解散帮会

**转让帮主**:
- 帮主可将帮主职位转让给帮会成员
- 需二次确认
- 原帮主降为普通成员

**解散帮会**:
- 仅帮主可解散
- 需输入帮会名称确认
- 解散后所有成员收到通知
- 帮会资源和科技清空

#### 2.2.3 成员列表展示
显示信息：
- 成员名称（玩家用户名）
- 职位（帮主/管理员/成员）
- 贡献度（总贡献、本周贡献）
- 加入时间
- 最后活跃时间
- 操作按钮（任命/辞退）

排序方式：
- 按职位排序（帮主>管理员>成员）
- 按贡献度排序
- 按加入时间排序

### 2.3 帮会升级系统

#### 2.3.1 等级系统
```
帮会等级范围: 1-10级
初始等级: 1级
初始成员上限: 10人
每级成员上限增加: +2人
最高成员上限: 10 + 9*2 = 28人
```

#### 2.3.2 升级成本
**消耗资源**: 金条（指数增长）
```python
# 升级公式
def calculate_guild_upgrade_cost(current_level):
    """
    1→2: 5金条
    2→3: 10金条
    3→4: 20金条
    ...
    9→10: 1280金条
    """
    if current_level >= 10:
        return None  # 已满级
    return 5 * (2 ** (current_level - 1))
```

#### 2.3.3 升级流程
1. 帮主点击"升级帮会"按钮
2. 显示所需金条数量
3. 确认后消耗金条
4. 帮会等级+1，成员上限+2
5. 发送帮会公告："{帮主名称}将帮会提升至{等级}级！"

**权限**: 仅帮主可操作

### 2.4 贡献度系统

#### 2.4.1 获得贡献途径
**资源捐赠**:
```python
# 兑换比例
CONTRIBUTION_RATES = {
    'silver': 1,      # 1银两 = 1贡献
    'grain': 2,       # 1粮食 = 2贡献
    'wood': 0,        # 暂不开放木材捐赠
    'stone': 0,       # 暂不开放石料捐赠
    'iron': 0,        # 暂不开放铁矿捐赠
}
```

**捐赠限制**:
- 每日捐赠上限：银两10万、粮食5万
- 单次捐赠最少：100单位
- 捐赠资源进入帮会资源池

**未来扩展**（本期不实现）:
- 完成帮会任务获得贡献
- 参与帮会活动获得贡献
- 帮会战胜利奖励贡献

#### 2.4.2 贡献统计
每个成员记录：
- **总贡献**: 历史累计贡献（包括已消费的）
- **当前贡献**: 可用于兑换的贡献
- **本周贡献**: 用于排行榜（每周一0点重置）

#### 2.4.3 贡献排行榜
显示内容：
- 本周贡献排行（前10名）
- 总贡献排行（前10名）
- 显示玩家自己的排名

### 2.5 帮会科技系统

#### 2.5.1 科技分类
```python
GUILD_TECH_CATEGORIES = {
    'production': '生产类科技',
    'combat': '战斗类科技',
    'welfare': '福利类科技',
}
```

#### 2.5.2 科技列表（初始规划）
**生产类**:
1. **装备锻造**: 每级产出装备到帮会仓库
   - Lv1: 每日产出2件绿色装备
   - Lv2: 每日产出3件绿色装备
   - Lv3: 每日产出2件蓝色装备
   - Lv4: 每日产出3件蓝色装备
   - Lv5: 每日产出1件紫色装备

2. **经验炼制**: 产出经验道具
   - Lv1: 每日产出3个小型经验丹
   - Lv2: 每日产出5个小型经验丹
   - Lv3: 每日产出2个中型经验丹
   - Lv4: 每日产出3个中型经验丹
   - Lv5: 每日产出1个大型经验丹

3. **资源补给**: 产出资源包
   - Lv1: 每日产出银两资源包×2
   - Lv2: 每日产出粮食资源包×2
   - Lv3: 每日产出木材资源包×2
   - Lv4: 每日产出混合资源包×2
   - Lv5: 每日产出高级资源包×3

**战斗类**（被动加成）:
4. **兵法研习**: 提升所有成员门客属性
   - Lv1: 武力+2%
   - Lv2: 武力+4%
   - Lv3: 武力+6%，智力+2%
   - Lv4: 武力+8%，智力+4%
   - Lv5: 武力+10%，智力+6%，防御+2%

5. **强兵战术**: 提升兵种属性
   - Lv1: 兵种攻击+3%
   - Lv2: 兵种攻击+6%
   - Lv3: 兵种攻击+9%，兵种防御+3%
   - Lv4: 兵种攻击+12%，兵种防御+6%
   - Lv5: 兵种攻击+15%，兵种防御+9%，兵种生命+5%

**福利类**（被动加成）:
6. **资源增产**: 提升建筑资源产出
   - Lv1: 资源产出+5%
   - Lv2: 资源产出+10%
   - Lv3: 资源产出+15%
   - Lv4: 资源产出+20%
   - Lv5: 资源产出+25%

7. **行军加速**: 减少任务行军时间
   - Lv1: 行军时间-5%
   - Lv2: 行军时间-10%
   - Lv3: 行军时间-15%
   - Lv4: 行军时间-20%
   - Lv5: 行军时间-25%

#### 2.5.3 科技升级成本
**消耗资源**: 帮会资源池（银两+粮食+金条）
```python
def calculate_tech_upgrade_cost(tech_key, current_level):
    """
    基础成本按科技类型和等级计算
    """
    base_costs = {
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

    base = base_costs.get(tech_key, {'silver': 5000, 'grain': 2000, 'gold_bar': 1})
    multiplier = 2 ** current_level  # 指数增长

    return {
        'silver': base['silver'] * multiplier,
        'grain': base['grain'] * multiplier,
        'gold_bar': base['gold_bar'] * multiplier,
    }
```

#### 2.5.4 科技升级流程
1. 帮主/管理员进入帮会科技页面
2. 选择要升级的科技，查看成本和效果
3. 确认升级，消耗帮会资源
4. 科技等级+1
5. 如果是生产类科技，立即触发产出任务
6. 如果是加成类科技，全体成员获得增益
7. 发送帮会公告："{管理员名称}将{科技名称}升至{等级}级！"

**权限**: 帮主和管理员可操作

#### 2.5.5 科技产出机制
**产出时间**: 每日凌晨0点（UTC+8）
**执行方式**: Celery定时任务

```python
@shared_task
def guild_tech_daily_production():
    """每日帮会科技产出"""
    for guild in Guild.objects.filter(is_active=True):
        # 装备锻造
        equipment_level = get_guild_tech_level(guild, 'equipment_forge')
        if equipment_level > 0:
            produce_equipment(guild, equipment_level)

        # 经验炼制
        experience_level = get_guild_tech_level(guild, 'experience_refine')
        if experience_level > 0:
            produce_experience_items(guild, experience_level)

        # 资源补给
        resource_level = get_guild_tech_level(guild, 'resource_supply')
        if resource_level > 0:
            produce_resource_packs(guild, resource_level)
```

### 2.6 帮会仓库与兑换系统

#### 2.6.1 帮会仓库
**容量**: 初始200个物品格子，不随等级增长

**物品来源**:
- 科技产出的装备、经验道具、资源包
- 未来可扩展：帮会任务奖励、帮会活动奖励

**物品管理**:
- 仓库物品属于帮会公有
- 成员可查看仓库物品列表
- 物品有库存数量显示

#### 2.6.2 兑换系统
**兑换流程**:
1. 成员进入帮会仓库页面
2. 浏览可兑换物品（按分类/稀有度筛选）
3. 查看物品信息：
   - 物品名称、图标、稀有度
   - 物品效果说明
   - 兑换成本（贡献度）
   - 剩余库存
4. 点击兑换，消耗贡献度
5. 物品进入个人背包（InventoryItem）
6. 帮会仓库库存-1
7. 记录兑换日志

**兑换成本**:
```python
# 按物品稀有度和类型定价
EXCHANGE_COSTS = {
    # 装备
    'gear_green': 50,      # 绿色装备: 50贡献
    'gear_blue': 150,      # 蓝色装备: 150贡献
    'gear_purple': 500,    # 紫色装备: 500贡献
    'gear_orange': 2000,   # 橙色装备: 2000贡献

    # 经验道具
    'exp_small': 30,       # 小型经验丹: 30贡献
    'exp_medium': 100,     # 中型经验丹: 100贡献
    'exp_large': 400,      # 大型经验丹: 400贡献

    # 资源包
    'resource_pack_common': 20,    # 普通资源包: 20贡献
    'resource_pack_advanced': 80,  # 高级资源包: 80贡献
}
```

**兑换限制**:
- 每日兑换次数限制：每人每日最多兑换10次
- 物品库存限制：库存为0时无法兑换
- 贡献度限制：贡献度不足时无法兑换

#### 2.6.3 兑换日志
记录内容：
- 兑换时间
- 兑换成员
- 兑换物品
- 消耗贡献度
- 剩余贡献度

显示：最近50条兑换记录（帮会管理可见）

### 2.7 帮会资源池

#### 2.7.1 资源来源
1. **成员捐赠**: 银两、粮食
2. **帮会升级**: 帮主消耗金条时，金条进入资源池
3. **未来扩展**: 帮会任务奖励、帮会战奖励

#### 2.7.2 资源用途
1. **科技升级**: 消耗银两、粮食、金条
2. **未来扩展**: 帮会建设、帮会活动

#### 2.7.3 资源统计
显示信息：
- 当前资源数量（银两、粮食、金条）
- 本周捐赠统计
- 本周消耗统计

### 2.8 帮会信息与公告

#### 2.8.1 帮会信息页
显示内容：
- 帮会名称、徽章
- 帮会等级、成员数量/上限
- 帮会简介（帮主可编辑）
- 帮主、管理员列表
- 创建时间

#### 2.8.2 帮会公告
**公告类型**:
- 系统公告（自动生成）:
  - 成员加入/退出
  - 帮会升级
  - 科技升级
  - 职位变更
- 帮主公告（手动发布）:
  - 帮主可发布文字公告
  - 最多保留10条公告
  - 显示发布时间和发布人

**公告显示**:
- 进入帮会页面时显示最新3条公告
- 可展开查看全部公告
- 新公告有未读标记

---

## 三、数据模型设计

### 3.1 模型概览
```
Guild (帮会主体)
  ├── GuildMember (成员关系)
  ├── GuildTechnology (科技等级)
  ├── GuildWarehouse (仓库物品)
  ├── GuildExchangeLog (兑换日志)
  ├── GuildApplication (入帮申请)
  ├── GuildAnnouncement (帮会公告)
  ├── GuildDonationLog (捐赠日志)
  └── GuildResourceLog (资源流水)
```

### 3.2 详细模型定义

```python
# guilds/models.py

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.validators import MinLengthValidator, MaxLengthValidator

User = get_user_model()

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
        """当前成员数"""
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
        ).select_related('user').first()

    def get_admins(self):
        """获取管理员列表"""
        return self.members.filter(
            is_active=True,
            position='admin'
        ).select_related('user')

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
        if self.daily_donation_reset_at < today:
            self.daily_donation_silver = 0
            self.daily_donation_grain = 0
            self.daily_donation_reset_at = today

        if self.daily_exchange_reset_at < today:
            self.daily_exchange_count = 0
            self.daily_exchange_reset_at = today

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
```

### 3.3 数据库迁移
```bash
# 创建guilds应用
python manage.py startapp guilds

# 生成迁移文件
python manage.py makemigrations guilds

# 执行迁移
python manage.py migrate guilds
```

---

## 四、服务层设计

### 4.1 服务模块结构
```
guilds/
├── services/
│   ├── __init__.py
│   ├── guild.py          # 帮会创建、升级、解散
│   ├── member.py         # 成员管理、职位变更
│   ├── contribution.py   # 捐赠、贡献计算
│   ├── technology.py     # 科技升级、科技加成
│   ├── warehouse.py      # 仓库管理、物品兑换
│   └── announcement.py   # 公告管理
```

### 4.2 核心服务函数

#### 4.2.1 guild.py - 帮会服务
```python
# guilds/services/guild.py

from django.db import transaction
from django.utils import timezone
from ..models import Guild, GuildMember, GuildTechnology, GuildAnnouncement
from gameplay.models import Manor
from gameplay.services.resources import spend_resources

# 配置常量
GUILD_CREATION_COST = {'gold_bar': 2}
GUILD_UPGRADE_BASE_COST = 5  # 金条

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
    # 验证用户是否已加入帮会
    if hasattr(user, 'guild_membership') and user.guild_membership.is_active:
        raise ValueError("您已加入帮会，无法创建新帮会")

    # 验证帮会名称
    if Guild.objects.filter(name=name, is_active=True).exists():
        raise ValueError("帮会名称已存在")

    # 验证资源
    manor = Manor.objects.get(user=user)
    if manor.gold_bar < GUILD_CREATION_COST['gold_bar']:
        raise ValueError(f"金条不足，需要{GUILD_CREATION_COST['gold_bar']}金条")

    with transaction.atomic():
        # 消耗金条
        manor.gold_bar -= GUILD_CREATION_COST['gold_bar']
        manor.save(update_fields=['gold_bar'])

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
            f"帮会成立！帮主{user.username}创建了{name}！",
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
    membership = GuildMember.objects.get(guild=guild, user=operator, is_active=True)
    if not membership.is_leader:
        raise ValueError("只有帮主可以升级帮会")

    # 验证等级
    if guild.level >= 10:
        raise ValueError("帮会已达最高等级")

    # 计算升级成本
    cost = calculate_guild_upgrade_cost(guild.level)

    # 验证资源
    manor = Manor.objects.get(user=operator)
    if manor.gold_bar < cost:
        raise ValueError(f"金条不足，需要{cost}金条")

    with transaction.atomic():
        # 消耗金条
        manor.gold_bar -= cost
        manor.save(update_fields=['gold_bar'])

        # 升级帮会
        guild.level += 1
        guild.gold_bar += cost  # 金条进入帮会资源池
        guild.save(update_fields=['level', 'gold_bar'])

        # 记录资源流水
        from ..models import GuildResourceLog
        GuildResourceLog.objects.create(
            guild=guild,
            action='guild_upgrade',
            gold_bar_change=cost,
            related_user=operator,
            note=f"帮会升级至{guild.level}级",
        )

        # 发布公告
        create_announcement(
            guild,
            'system',
            f"{operator.username}将帮会提升至{guild.level}级！成员上限增加至{guild.member_capacity}人。",
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

    for tech_key, category, max_level in tech_configs:
        GuildTechnology.objects.create(
            guild=guild,
            tech_key=tech_key,
            category=category,
            level=0,
            max_level=max_level,
        )


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
    membership = GuildMember.objects.get(guild=guild, user=operator, is_active=True)
    if not membership.is_leader:
        raise ValueError("只有帮主可以解散帮会")

    with transaction.atomic():
        # 标记帮会为不活跃
        guild.is_active = False
        guild.save(update_fields=['is_active'])

        # 标记所有成员为离开
        guild.members.filter(is_active=True).update(
            is_active=False,
            left_at=timezone.now(),
        )

        # 发送解散通知（系统消息）
        from gameplay.services.messages import create_message
        for member in guild.members.all():
            create_message(
                manor=Manor.objects.get(user=member.user),
                kind='system',
                title='帮会解散通知',
                body=f"您所在的帮会【{guild.name}】已被帮主解散。",
            )


def get_guild_list(ordering='-level', search=None, page=1, page_size=20):
    """
    获取帮会列表

    Args:
        ordering: 排序字段
        search: 搜索关键词
        page: 页码
        page_size: 每页数量

    Returns:
        QuerySet
    """
    queryset = Guild.objects.filter(is_active=True)

    if search:
        queryset = queryset.filter(name__icontains=search)

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
```

#### 4.2.2 member.py - 成员管理服务
```python
# guilds/services/member.py

from django.db import transaction
from django.utils import timezone
from ..models import Guild, GuildMember, GuildApplication
from gameplay.models import Manor
from gameplay.services.messages import create_message
from .announcement import create_announcement

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
    if hasattr(application.applicant, 'guild_membership') and \
       application.applicant.guild_membership.is_active:
        raise ValueError("申请人已加入其他帮会")

    # 验证权限（非自动审批时）
    if not auto:
        membership = GuildMember.objects.get(
            guild=guild,
            user=reviewer,
            is_active=True
        )
        if not membership.can_manage:
            raise ValueError("您没有审批权限")

    with transaction.atomic():
        # 更新申请状态
        application.status = 'approved'
        application.reviewed_by = reviewer
        application.reviewed_at = timezone.now()
        application.save()

        # 创建成员记录
        GuildMember.objects.create(
            guild=guild,
            user=application.applicant,
            position='member',
        )

        # 发送系统消息给申请人
        create_message(
            manor=Manor.objects.get(user=application.applicant),
            kind='system',
            title='入帮申请通过',
            body=f"您的入帮申请已通过，欢迎加入【{guild.name}】！",
        )

        # 发布帮会公告
        create_announcement(
            guild,
            'system',
            f"欢迎新成员{application.applicant.username}加入帮会！",
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
    membership = GuildMember.objects.get(
        guild=application.guild,
        user=reviewer,
        is_active=True
    )
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

    with transaction.atomic():
        # 标记离开
        member.is_active = False
        member.left_at = timezone.now()
        member.save()

        # 发布公告
        create_announcement(
            member.guild,
            'system',
            f"成员{member.user.username}离开了帮会。",
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
    operator_member = GuildMember.objects.get(
        guild=target_member.guild,
        user=operator,
        is_active=True
    )
    if not operator_member.can_manage:
        raise ValueError("您没有辞退权限")

    # 不能辞退帮主和管理员
    if target_member.position in ['leader', 'admin']:
        raise ValueError("无法辞退帮主或管理员")

    # 不能辞退自己
    if target_member.user == operator:
        raise ValueError("无法辞退自己")

    with transaction.atomic():
        # 标记离开
        target_member.is_active = False
        target_member.left_at = timezone.now()
        target_member.save()

        # 发送系统消息
        create_message(
            manor=Manor.objects.get(user=target_member.user),
            kind='system',
            title='被移出帮会',
            body=f"您已被移出帮会【{target_member.guild.name}】。",
        )

        # 发布公告
        create_announcement(
            target_member.guild,
            'system',
            f"成员{target_member.user.username}被移出帮会。",
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
    operator_member = GuildMember.objects.get(
        guild=target_member.guild,
        user=operator,
        is_active=True
    )
    if not operator_member.is_leader:
        raise ValueError("只有帮主可以任命管理员")

    # 验证管理员数量
    if not target_member.guild.can_appoint_admin():
        raise ValueError("管理员数量已达上限（2人）")

    # 验证目标成员
    if target_member.position != 'member':
        raise ValueError("该成员已是管理人员")

    with transaction.atomic():
        # 任命为管理员
        target_member.position = 'admin'
        target_member.save(update_fields=['position'])

        # 发送系统消息
        create_message(
            manor=Manor.objects.get(user=target_member.user),
            kind='system',
            title='职位变更',
            body=f"您已被任命为帮会【{target_member.guild.name}】的管理员！",
        )

        # 发布公告
        create_announcement(
            target_member.guild,
            'system',
            f"{operator.username}任命{target_member.user.username}为管理员。",
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
    operator_member = GuildMember.objects.get(
        guild=target_member.guild,
        user=operator,
        is_active=True
    )
    if not operator_member.is_leader:
        raise ValueError("只有帮主可以罢免管理员")

    # 验证目标成员
    if target_member.position != 'admin':
        raise ValueError("该成员不是管理员")

    with transaction.atomic():
        # 降为普通成员
        target_member.position = 'member'
        target_member.save(update_fields=['position'])

        # 发送系统消息
        create_message(
            manor=Manor.objects.get(user=target_member.user),
            kind='system',
            title='职位变更',
            body=f"您已被罢免管理员职位，降为普通成员。",
        )

        # 发布公告
        create_announcement(
            target_member.guild,
            'system',
            f"{target_member.user.username}卸任管理员职位。",
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

    with transaction.atomic():
        # 原帮主降为普通成员
        current_leader_member.position = 'member'
        current_leader_member.save(update_fields=['position'])

        # 新帮主上任
        new_leader_member.position = 'leader'
        new_leader_member.save(update_fields=['position'])

        # 发送系统消息
        create_message(
            manor=Manor.objects.get(user=new_leader_member.user),
            kind='system',
            title='职位变更',
            body=f"您已成为帮会【{new_leader_member.guild.name}】的新任帮主！",
        )

        # 发布公告
        create_announcement(
            new_leader_member.guild,
            'system',
            f"{current_leader_member.user.username}将帮主之位传给了{new_leader_member.user.username}！",
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
```

#### 4.2.3 contribution.py - 贡献度服务
```python
# guilds/services/contribution.py

from django.db import transaction
from django.utils import timezone
from ..models import Guild, GuildMember, GuildDonationLog, GuildResourceLog
from gameplay.models import Manor
from .announcement import create_announcement

# 贡献兑换比例
CONTRIBUTION_RATES = {
    'silver': 1,      # 1银两 = 1贡献
    'grain': 2,       # 1粮食 = 2贡献
}

# 每日捐赠上限
DAILY_DONATION_LIMITS = {
    'silver': 100000,  # 10万银两
    'grain': 50000,    # 5万粮食
}

# 最小捐赠数量
MIN_DONATION_AMOUNT = 100


def donate_resource(member, resource_type, amount):
    """
    捐赠资源获得贡献

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

    # 重置每日限制
    member.reset_daily_limits()

    # 验证每日捐赠上限
    if resource_type == 'silver':
        if member.daily_donation_silver + amount > DAILY_DONATION_LIMITS['silver']:
            raise ValueError(f"今日银两捐赠已达上限（{DAILY_DONATION_LIMITS['silver']}）")
    elif resource_type == 'grain':
        if member.daily_donation_grain + amount > DAILY_DONATION_LIMITS['grain']:
            raise ValueError(f"今日粮食捐赠已达上限（{DAILY_DONATION_LIMITS['grain']}）")

    # 验证玩家资源
    manor = Manor.objects.get(user=member.user)
    if resource_type == 'silver' and manor.silver < amount:
        raise ValueError("银两不足")
    elif resource_type == 'grain' and manor.grain < amount:
        raise ValueError("粮食不足")

    # 计算贡献
    contribution = amount * CONTRIBUTION_RATES[resource_type]

    with transaction.atomic():
        # 扣除玩家资源
        if resource_type == 'silver':
            manor.silver -= amount
            manor.save(update_fields=['silver'])
        elif resource_type == 'grain':
            manor.grain -= amount
            manor.save(update_fields=['grain'])

        # 增加帮会资源
        guild = member.guild
        if resource_type == 'silver':
            guild.silver += amount
            guild.save(update_fields=['silver'])
        elif resource_type == 'grain':
            guild.grain += amount
            guild.save(update_fields=['grain'])

        # 增加成员贡献
        member.total_contribution += contribution
        member.current_contribution += contribution
        member.weekly_contribution += contribution

        # 更新每日捐赠统计
        if resource_type == 'silver':
            member.daily_donation_silver += amount
        elif resource_type == 'grain':
            member.daily_donation_grain += amount

        member.save()

        # 记录捐赠日志
        GuildDonationLog.objects.create(
            guild=guild,
            member=member,
            resource_type=resource_type,
            amount=amount,
            contribution_gained=contribution,
        )

        # 记录资源流水
        GuildResourceLog.objects.create(
            guild=guild,
            action='donation',
            silver_change=amount if resource_type == 'silver' else 0,
            grain_change=amount if resource_type == 'grain' else 0,
            related_user=member.user,
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
        limit: 返回数量

    Returns:
        QuerySet
    """
    members = guild.members.filter(is_active=True).select_related('user')

    if ranking_type == 'weekly':
        return members.order_by('-weekly_contribution', '-total_contribution')[:limit]
    else:
        return members.order_by('-total_contribution', '-weekly_contribution')[:limit]


def get_my_contribution_rank(member, ranking_type='total'):
    """
    获取我的贡献排名

    Args:
        member: GuildMember对象
        ranking_type: 'total'(总贡献) 或 'weekly'(本周贡献)

    Returns:
        int: 排名（从1开始）
    """
    guild = member.guild
    members = guild.members.filter(is_active=True)

    if ranking_type == 'weekly':
        higher_ranked = members.filter(
            weekly_contribution__gt=member.weekly_contribution
        ).count()
    else:
        higher_ranked = members.filter(
            total_contribution__gt=member.total_contribution
        ).count()

    return higher_ranked + 1
```

#### 4.2.4 technology.py - 科技服务
```python
# guilds/services/technology.py

from django.db import transaction
from django.utils import timezone
from ..models import Guild, GuildMember, GuildTechnology, GuildResourceLog
from .announcement import create_announcement

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
    membership = GuildMember.objects.get(
        guild=guild,
        user=operator,
        is_active=True
    )
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

    with transaction.atomic():
        # 消耗帮会资源
        guild.silver -= cost['silver']
        guild.grain -= cost['grain']
        guild.gold_bar -= cost['gold_bar']
        guild.save(update_fields=['silver', 'grain', 'gold_bar'])

        # 升级科技
        tech.level += 1
        tech.save(update_fields=['level'])

        # 记录资源流水
        GuildResourceLog.objects.create(
            guild=guild,
            action='tech_upgrade',
            silver_change=-cost['silver'],
            grain_change=-cost['grain'],
            gold_bar_change=-cost['gold_bar'],
            related_user=operator,
            note=f"升级{TECH_NAMES.get(tech_key, tech_key)}至{tech.level}级",
        )

        # 发布公告
        create_announcement(
            guild,
            'system',
            f"{operator.username}将{TECH_NAMES.get(tech_key, tech_key)}升至{tech.level}级！",
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
```

#### 4.2.5 warehouse.py - 仓库服务
```python
# guilds/services/warehouse.py

from django.db import transaction
from django.utils import timezone
from ..models import Guild, GuildMember, GuildWarehouse, GuildExchangeLog
from gameplay.models import Manor, InventoryItem
import random

# 兑换成本配置
EXCHANGE_COSTS = {
    # 装备
    'gear_green': 50,
    'gear_blue': 150,
    'gear_purple': 500,
    'gear_orange': 2000,

    # 经验道具
    'exp_small': 30,
    'exp_medium': 100,
    'exp_large': 400,

    # 资源包
    'resource_pack_common': 20,
    'resource_pack_advanced': 80,
}

# 每日兑换上限
DAILY_EXCHANGE_LIMIT = 10


def add_item_to_warehouse(guild, item_key, quantity, contribution_cost):
    """
    添加物品到帮会仓库

    Args:
        guild: Guild对象
        item_key: 物品key
        quantity: 数量
        contribution_cost: 兑换成本（贡献度）
    """
    warehouse_item, created = GuildWarehouse.objects.get_or_create(
        guild=guild,
        item_key=item_key,
        defaults={'contribution_cost': contribution_cost}
    )

    warehouse_item.quantity += quantity
    warehouse_item.total_produced += quantity
    warehouse_item.save(update_fields=['quantity', 'total_produced'])


def exchange_item(member, item_key, quantity=1):
    """
    兑换帮会仓库物品

    Args:
        member: GuildMember对象
        item_key: 物品key
        quantity: 兑换数量

    Raises:
        ValueError: 验证失败
    """
    # 重置每日限制
    member.reset_daily_limits()

    # 验证每日兑换次数
    if member.daily_exchange_count >= DAILY_EXCHANGE_LIMIT:
        raise ValueError(f"今日兑换次数已达上限（{DAILY_EXCHANGE_LIMIT}次）")

    # 获取仓库物品
    try:
        warehouse_item = GuildWarehouse.objects.get(
            guild=member.guild,
            item_key=item_key
        )
    except GuildWarehouse.DoesNotExist:
        raise ValueError("物品不存在")

    # 验证库存
    if warehouse_item.quantity < quantity:
        raise ValueError(f"库存不足，剩余{warehouse_item.quantity}件")

    # 计算消耗贡献
    total_cost = warehouse_item.contribution_cost * quantity

    # 验证贡献度
    if member.current_contribution < total_cost:
        raise ValueError(f"贡献度不足，需要{total_cost}贡献")

    with transaction.atomic():
        # 扣除贡献度
        member.current_contribution -= total_cost
        member.daily_exchange_count += 1
        member.save(update_fields=['current_contribution', 'daily_exchange_count'])

        # 扣除仓库库存
        warehouse_item.quantity -= quantity
        warehouse_item.total_exchanged += quantity
        warehouse_item.save(update_fields=['quantity', 'total_exchanged'])

        # 添加到玩家背包
        manor = Manor.objects.get(user=member.user)
        inventory_item, created = InventoryItem.objects.get_or_create(
            manor=manor,
            item_key=item_key,
            storage_location='warehouse',
            defaults={'quantity': 0}
        )
        inventory_item.quantity += quantity
        inventory_item.save(update_fields=['quantity'])

        # 记录兑换日志
        GuildExchangeLog.objects.create(
            guild=member.guild,
            member=member,
            item_key=item_key,
            quantity=quantity,
            contribution_cost=total_cost,
        )


def produce_equipment(guild, tech_level):
    """
    装备锻造科技产出装备

    Args:
        guild: Guild对象
        tech_level: 科技等级
    """
    # 根据等级确定产出
    production_table = {
        1: [('gear_green_random', 2, 50)],
        2: [('gear_green_random', 3, 50)],
        3: [('gear_blue_random', 2, 150)],
        4: [('gear_blue_random', 3, 150)],
        5: [('gear_purple_random', 1, 500)],
    }

    items = production_table.get(tech_level, [])
    for item_key, quantity, cost in items:
        # 这里简化处理，实际应该从ItemTemplate中随机选择装备
        add_item_to_warehouse(guild, item_key, quantity, cost)


def produce_experience_items(guild, tech_level):
    """
    经验炼制科技产出经验道具

    Args:
        guild: Guild对象
        tech_level: 科技等级
    """
    production_table = {
        1: [('exp_small', 3, 30)],
        2: [('exp_small', 5, 30)],
        3: [('exp_medium', 2, 100)],
        4: [('exp_medium', 3, 100)],
        5: [('exp_large', 1, 400)],
    }

    items = production_table.get(tech_level, [])
    for item_key, quantity, cost in items:
        add_item_to_warehouse(guild, item_key, quantity, cost)


def produce_resource_packs(guild, tech_level):
    """
    资源补给科技产出资源包

    Args:
        guild: Guild对象
        tech_level: 科技等级
    """
    production_table = {
        1: [('resource_pack_silver', 2, 20)],
        2: [('resource_pack_grain', 2, 20)],
        3: [('resource_pack_wood', 2, 20)],
        4: [('resource_pack_mixed', 2, 20)],
        5: [('resource_pack_advanced', 3, 80)],
    }

    items = production_table.get(tech_level, [])
    for item_key, quantity, cost in items:
        add_item_to_warehouse(guild, item_key, quantity, cost)


def get_warehouse_items(guild):
    """
    获取帮会仓库物品列表

    Args:
        guild: Guild对象

    Returns:
        QuerySet
    """
    return GuildWarehouse.objects.filter(
        guild=guild,
        quantity__gt=0
    ).order_by('-contribution_cost', 'item_key')


def get_exchange_logs(guild, limit=50):
    """
    获取兑换日志

    Args:
        guild: Guild对象
        limit: 返回数量

    Returns:
        QuerySet
    """
    return GuildExchangeLog.objects.filter(
        guild=guild
    ).select_related('member__user').order_by('-exchanged_at')[:limit]
```

---

## 五、URL路由设计

### 5.1 URL配置
```python
# guilds/urls.py

from django.urls import path
from . import views

app_name = 'guilds'

urlpatterns = [
    # 帮会大厅
    path('', views.guild_hall, name='hall'),

    # 帮会列表与搜索
    path('list/', views.guild_list, name='list'),
    path('search/', views.guild_search, name='search'),

    # 创建帮会
    path('create/', views.create_guild, name='create'),

    # 帮会详情
    path('<int:guild_id>/', views.guild_detail, name='detail'),
    path('<int:guild_id>/info/', views.guild_info, name='info'),

    # 申请与审批
    path('<int:guild_id>/apply/', views.apply_to_guild, name='apply'),
    path('applications/', views.application_list, name='applications'),
    path('application/<int:app_id>/approve/', views.approve_application, name='approve_application'),
    path('application/<int:app_id>/reject/', views.reject_application, name='reject_application'),

    # 成员管理
    path('members/', views.member_list, name='members'),
    path('member/<int:member_id>/kick/', views.kick_member, name='kick_member'),
    path('member/<int:member_id>/appoint/', views.appoint_admin, name='appoint_admin'),
    path('member/<int:member_id>/demote/', views.demote_admin, name='demote_admin'),
    path('member/<int:member_id>/transfer/', views.transfer_leadership, name='transfer_leadership'),
    path('leave/', views.leave_guild, name='leave'),

    # 帮会升级
    path('upgrade/', views.upgrade_guild, name='upgrade'),
    path('disband/', views.disband_guild, name='disband'),

    # 贡献系统
    path('donate/', views.donate_resource, name='donate'),
    path('contribution/ranking/', views.contribution_ranking, name='contribution_ranking'),

    # 科技系统
    path('technology/', views.technology_list, name='technology'),
    path('technology/<str:tech_key>/upgrade/', views.upgrade_technology, name='upgrade_tech'),

    # 仓库与兑换
    path('warehouse/', views.warehouse, name='warehouse'),
    path('warehouse/<str:item_key>/exchange/', views.exchange_item, name='exchange_item'),
    path('warehouse/logs/', views.exchange_logs, name='exchange_logs'),

    # 公告
    path('announcements/', views.announcement_list, name='announcements'),
    path('announcement/create/', views.create_announcement, name='create_announcement'),

    # 资源与日志
    path('resources/', views.resource_status, name='resources'),
    path('logs/donation/', views.donation_logs, name='donation_logs'),
    path('logs/resource/', views.resource_logs, name='resource_logs'),
]
```

### 5.2 主配置集成
```python
# config/urls.py

urlpatterns = [
    # ... 现有路由 ...
    path('guilds/', include('guilds.urls')),
]
```

---

## 六、视图函数设计

### 6.1 视图结构
```
guilds/views/
├── __init__.py
├── guild.py          # 帮会创建、详情、升级
├── member.py         # 成员管理
├── contribution.py   # 捐赠、贡献
├── technology.py     # 科技升级
└── warehouse.py      # 仓库、兑换
```

### 6.2 核心视图示例
```python
# guilds/views/guild.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from ..models import Guild, GuildMember
from ..services import guild as guild_service
from gameplay.models import Manor

@login_required
def guild_hall(request):
    """帮会大厅 - 入口页面"""
    user = request.user
    context = {}

    # 检查是否已加入帮会
    if hasattr(user, 'guild_membership') and user.guild_membership.is_active:
        # 已加入帮会，重定向到帮会详情
        return redirect('guilds:detail', guild_id=user.guild_membership.guild.id)

    # 未加入帮会，显示帮会列表
    guilds = Guild.objects.filter(is_active=True).order_by('-level', '-created_at')[:20]
    context['guilds'] = guilds
    context['can_create'] = True  # 可以创建帮会

    return render(request, 'guilds/hall.html', context)


@login_required
def create_guild(request):
    """创建帮会"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        emblem = request.POST.get('emblem', 'default')

        try:
            guild = guild_service.create_guild(
                user=request.user,
                name=name,
                description=description,
                emblem=emblem
            )
            messages.success(request, f'恭喜！帮会【{guild.name}】创建成功！')
            return redirect('guilds:detail', guild_id=guild.id)
        except ValueError as e:
            messages.error(request, str(e))

    # GET请求，显示创建表单
    manor = get_object_or_404(Manor, user=request.user)
    context = {
        'manor': manor,
        'creation_cost': guild_service.GUILD_CREATION_COST,
    }
    return render(request, 'guilds/create.html', context)


@login_required
def guild_detail(request, guild_id):
    """帮会详情页面"""
    guild = get_object_or_404(Guild, id=guild_id, is_active=True)
    user = request.user

    # 检查是否是本帮会成员
    is_member = False
    member = None
    if hasattr(user, 'guild_membership') and user.guild_membership.is_active:
        if user.guild_membership.guild == guild:
            is_member = True
            member = user.guild_membership

    # 获取帮会信息
    leader = guild.get_leader()
    admins = guild.get_admins()
    members = guild.members.filter(is_active=True).select_related('user')[:20]
    announcements = guild.announcements.all()[:5]

    context = {
        'guild': guild,
        'is_member': is_member,
        'member': member,
        'leader': leader,
        'admins': admins,
        'members': members,
        'announcements': announcements,
    }

    return render(request, 'guilds/detail.html', context)


@login_required
def upgrade_guild(request):
    """升级帮会"""
    if request.method != 'POST':
        return redirect('guilds:hall')

    user = request.user

    # 验证是否是帮主
    if not hasattr(user, 'guild_membership') or not user.guild_membership.is_active:
        messages.error(request, '您不在帮会中')
        return redirect('guilds:hall')

    member = user.guild_membership
    if not member.is_leader:
        messages.error(request, '只有帮主可以升级帮会')
        return redirect('guilds:detail', guild_id=member.guild.id)

    try:
        guild_service.upgrade_guild(member.guild, user)
        messages.success(request, f'帮会升级成功！当前等级：{member.guild.level}')
    except ValueError as e:
        messages.error(request, str(e))

    return redirect('guilds:detail', guild_id=member.guild.id)
```

---

## 七、前端界面设计

### 7.1 页面布局

#### 7.1.1 帮会大厅 (hall.html)
```html
{% extends 'base.html' %}

{% block title %}帮会大厅{% endblock %}

{% block content %}
<div class="container">
    <h1 class="page-title">帮会大厅</h1>

    {% if can_create %}
    <div class="action-bar">
        <a href="{% url 'guilds:create' %}" class="btn-primary">创建帮会</a>
        <a href="{% url 'guilds:list' %}" class="btn-secondary">帮会列表</a>
    </div>
    {% endif %}

    <h2>推荐帮会</h2>
    <div class="guild-grid">
        {% for guild in guilds %}
        <article class="guild-card">
            <div class="guild-emblem">
                <img src="/static/emblems/{{ guild.emblem }}.png" alt="{{ guild.name }}">
            </div>
            <div class="guild-info">
                <h3>{{ guild.name }}</h3>
                <p class="guild-level">等级：{{ guild.level }}</p>
                <p class="guild-members">成员：{{ guild.current_member_count }}/{{ guild.member_capacity }}</p>
                <p class="guild-leader">帮主：{{ guild.get_leader.user.username }}</p>
            </div>
            <div class="guild-actions">
                <a href="{% url 'guilds:detail' guild.id %}" class="btn-secondary">查看详情</a>
                <a href="{% url 'guilds:apply' guild.id %}" class="btn-primary">申请加入</a>
            </div>
        </article>
        {% endfor %}
    </div>
</div>
{% endblock %}
```

#### 7.1.2 帮会详情页 (detail.html)
```html
{% extends 'base.html' %}

{% block title %}{{ guild.name }}{% endblock %}

{% block content %}
<div class="container">
    <!-- 帮会头部 -->
    <div class="guild-header">
        <div class="guild-emblem-large">
            <img src="/static/emblems/{{ guild.emblem }}.png" alt="{{ guild.name }}">
        </div>
        <div class="guild-info">
            <h1>{{ guild.name }}</h1>
            <p class="guild-description">{{ guild.description }}</p>
            <div class="guild-stats">
                <span class="stat">等级：{{ guild.level }}</span>
                <span class="stat">成员：{{ guild.current_member_count }}/{{ guild.member_capacity }}</span>
                <span class="stat">创建时间：{{ guild.created_at|date:"Y-m-d" }}</span>
            </div>
        </div>

        {% if is_member and member.is_leader %}
        <div class="guild-actions">
            <button onclick="showUpgradeModal()" class="btn-primary">升级帮会</button>
            <a href="{% url 'guilds:info' guild.id %}" class="btn-secondary">帮会设置</a>
        </div>
        {% endif %}
    </div>

    <!-- 导航标签页 -->
    <nav class="guild-tabs">
        <a href="#overview" class="tab active">概览</a>
        <a href="#members" class="tab">成员</a>
        <a href="#technology" class="tab">科技</a>
        <a href="#warehouse" class="tab">仓库</a>
        <a href="#announcements" class="tab">公告</a>
    </nav>

    <!-- 概览页 -->
    <div id="overview" class="tab-content active">
        <div class="grid-2col">
            <!-- 帮会管理层 -->
            <div class="card">
                <h3>帮会管理</h3>
                <div class="leader-list">
                    <div class="leader-item">
                        <span class="position">帮主：</span>
                        <span class="username">{{ leader.user.username }}</span>
                    </div>
                    {% for admin in admins %}
                    <div class="leader-item">
                        <span class="position">管理员：</span>
                        <span class="username">{{ admin.user.username }}</span>
                    </div>
                    {% endfor %}
                </div>
            </div>

            <!-- 帮会资源 -->
            {% if is_member %}
            <div class="card">
                <h3>帮会资源</h3>
                <div class="resource-list">
                    <div class="resource-item">
                        <span class="resource-name">银两：</span>
                        <span class="resource-value">{{ guild.silver|floatformat:0 }}</span>
                    </div>
                    <div class="resource-item">
                        <span class="resource-name">粮食：</span>
                        <span class="resource-value">{{ guild.grain|floatformat:0 }}</span>
                    </div>
                    <div class="resource-item">
                        <span class="resource-name">金条：</span>
                        <span class="resource-value">{{ guild.gold_bar }}</span>
                    </div>
                </div>
                {% if is_member %}
                <a href="{% url 'guilds:donate' %}" class="btn-primary">捐赠资源</a>
                {% endif %}
            </div>
            {% endif %}
        </div>

        <!-- 最新公告 -->
        <div class="card">
            <h3>最新公告</h3>
            <div class="announcement-list">
                {% for announcement in announcements %}
                <div class="announcement-item {{ announcement.type }}">
                    <span class="time">{{ announcement.created_at|date:"m-d H:i" }}</span>
                    <span class="content">{{ announcement.content }}</span>
                </div>
                {% endfor %}
            </div>
            <a href="{% url 'guilds:announcements' %}" class="btn-secondary">查看全部公告</a>
        </div>
    </div>

    <!-- 其他标签页内容... -->
</div>
{% endblock %}
```

### 7.2 CSS样式指南
```css
/* guilds/static/guilds/style.css */

/* 古风配色 */
:root {
    --guild-primary: #DAA520;
    --guild-bg: #F0E5CA;
    --guild-border: #8B4513;
    --guild-text: #4A2612;
}

.guild-card {
    background: var(--guild-bg);
    border: 2px solid var(--guild-border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 16px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.guild-emblem {
    width: 80px;
    height: 80px;
    border-radius: 50%;
    overflow: hidden;
    border: 3px solid var(--guild-primary);
}

.guild-header {
    display: flex;
    align-items: center;
    gap: 24px;
    background: var(--guild-bg);
    padding: 24px;
    border: 2px solid var(--guild-border);
    border-radius: 8px;
    margin-bottom: 24px;
}

.guild-tabs {
    display: flex;
    gap: 8px;
    border-bottom: 2px solid var(--guild-border);
    margin-bottom: 24px;
}

.guild-tabs .tab {
    padding: 12px 24px;
    background: #E8D4A0;
    border: 2px solid var(--guild-border);
    border-bottom: none;
    border-radius: 8px 8px 0 0;
    cursor: pointer;
    transition: all 0.3s;
}

.guild-tabs .tab.active {
    background: var(--guild-bg);
    color: var(--guild-primary);
    font-weight: bold;
}

/* 响应式布局 */
@media (max-width: 768px) {
    .guild-header {
        flex-direction: column;
    }

    .grid-2col {
        grid-template-columns: 1fr;
    }
}
```

---

## 八、异步任务设计

### 8.1 Celery任务定义
```python
# guilds/tasks.py

from celery import shared_task
from django.utils import timezone
from datetime import datetime
from .models import Guild, GuildTechnology
from .services.warehouse import (
    produce_equipment,
    produce_experience_items,
    produce_resource_packs
)
from .services.contribution import reset_weekly_contributions


@shared_task
def guild_tech_daily_production():
    """
    每日帮会科技产出
    执行时间：每天00:00（UTC+8）
    """
    guilds = Guild.objects.filter(is_active=True)

    for guild in guilds:
        # 装备锻造
        try:
            tech = GuildTechnology.objects.get(guild=guild, tech_key='equipment_forge')
            if tech.level > 0:
                produce_equipment(guild, tech.level)
                tech.last_production_at = timezone.now()
                tech.save(update_fields=['last_production_at'])
        except GuildTechnology.DoesNotExist:
            pass

        # 经验炼制
        try:
            tech = GuildTechnology.objects.get(guild=guild, tech_key='experience_refine')
            if tech.level > 0:
                produce_experience_items(guild, tech.level)
                tech.last_production_at = timezone.now()
                tech.save(update_fields=['last_production_at'])
        except GuildTechnology.DoesNotExist:
            pass

        # 资源补给
        try:
            tech = GuildTechnology.objects.get(guild=guild, tech_key='resource_supply')
            if tech.level > 0:
                produce_resource_packs(guild, tech.level)
                tech.last_production_at = timezone.now()
                tech.save(update_fields=['last_production_at'])
        except GuildTechnology.DoesNotExist:
            pass


@shared_task
def reset_guild_weekly_stats():
    """
    重置帮会每周统计
    执行时间：每周一00:00（UTC+8）
    """
    reset_weekly_contributions()


@shared_task
def cleanup_old_guild_logs():
    """
    清理旧的帮会日志
    执行时间：每天凌晨03:00（UTC+8）
    保留最近30天的日志
    """
    from datetime import timedelta
    from .models import GuildDonationLog, GuildExchangeLog, GuildResourceLog

    cutoff_date = timezone.now() - timedelta(days=30)

    GuildDonationLog.objects.filter(donated_at__lt=cutoff_date).delete()
    GuildExchangeLog.objects.filter(exchanged_at__lt=cutoff_date).delete()
    GuildResourceLog.objects.filter(created_at__lt=cutoff_date).delete()
```

### 8.2 定时任务配置
```python
# config/celery.py

from celery.schedules import crontab

app.conf.beat_schedule = {
    # ... 现有定时任务 ...

    # 帮会科技每日产出
    'guild-tech-daily-production': {
        'task': 'guilds.tasks.guild_tech_daily_production',
        'schedule': crontab(hour=0, minute=0),  # 每天00:00
    },

    # 帮会每周统计重置
    'reset-guild-weekly-stats': {
        'task': 'guilds.tasks.reset_guild_weekly_stats',
        'schedule': crontab(hour=0, minute=0, day_of_week=1),  # 每周一00:00
    },

    # 清理旧日志
    'cleanup-old-guild-logs': {
        'task': 'guilds.tasks.cleanup_old_guild_logs',
        'schedule': crontab(hour=3, minute=0),  # 每天03:00
    },
}
```

---

## 九、与现有系统集成

### 9.1 导航栏集成
```html
<!-- templates/base.html -->

<nav class="navbar">
    <!-- ... 现有导航 ... -->

    {% if user.is_authenticated %}
        <a href="{% url 'guilds:hall' %}" class="nav-link">
            帮会
            {% if user.guild_membership.is_active %}
            <span class="badge">{{ user.guild_membership.guild.name }}</span>
            {% endif %}
        </a>
    {% endif %}
</nav>
```

### 9.2 资源加成集成
```python
# gameplay/services/resources.py

def sync_resource_production(manor):
    """同步资源产出（集成帮会科技加成）"""
    # ... 现有代码 ...

    # 应用帮会科技加成
    user = manor.user
    if hasattr(user, 'guild_membership') and user.guild_membership.is_active:
        from guilds.services.technology import get_tech_bonus
        guild = user.guild_membership.guild
        production_bonus = get_tech_bonus(guild, 'resource_production')

        # 应用加成到各项资源
        wood_gain = int(wood_gain * (1 + production_bonus))
        stone_gain = int(stone_gain * (1 + production_bonus))
        iron_gain = int(iron_gain * (1 + production_bonus))
        grain_gain = int(grain_gain * (1 + production_bonus))
```

### 9.3 战斗系统集成
```python
# battle/services/battle_simulator.py

def create_combatant_from_guest(guest, side):
    """创建战斗单位（集成帮会科技加成）"""
    # ... 现有代码 ...

    # 应用帮会科技加成
    from guilds.services.technology import apply_guild_bonus_to_guest
    bonused_stats = apply_guild_bonus_to_guest(guest)

    return {
        'force': bonused_stats['force'],
        'intellect': bonused_stats['intellect'],
        'defense': bonused_stats['defense'],
        # ... 其他属性 ...
    }
```

### 9.4 任务系统集成
```python
# gameplay/services/missions.py

def launch_mission(manor, mission, guest_ids, loadout):
    """发起任务（集成帮会科技加成）"""
    # ... 现有代码 ...

    # 应用行军加速
    user = manor.user
    if hasattr(user, 'guild_membership') and user.guild_membership.is_active:
        from guilds.services.technology import get_tech_bonus
        guild = user.guild_membership.guild
        march_speed_bonus = get_tech_bonus(guild, 'march_speed')

        # 减少行军时间
        total_duration = int(total_duration * (1 - march_speed_bonus))
```

---

## 十、测试计划

### 10.1 单元测试
```python
# guilds/tests/test_services.py

from django.test import TestCase
from django.contrib.auth import get_user_model
from guilds.services import guild as guild_service
from guilds.models import Guild, GuildMember
from gameplay.models import Manor

User = get_user_model()

class GuildServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.manor = Manor.objects.create(
            user=self.user,
            gold_bar=10
        )

    def test_create_guild(self):
        """测试创建帮会"""
        guild = guild_service.create_guild(
            user=self.user,
            name='测试帮会',
            description='这是一个测试帮会'
        )

        self.assertEqual(guild.name, '测试帮会')
        self.assertEqual(guild.level, 1)
        self.assertEqual(guild.member_capacity, 10)

        # 验证创建者成为帮主
        membership = GuildMember.objects.get(guild=guild, user=self.user)
        self.assertEqual(membership.position, 'leader')
        self.assertTrue(membership.is_active)

    def test_upgrade_guild(self):
        """测试升级帮会"""
        guild = guild_service.create_guild(
            user=self.user,
            name='测试帮会'
        )

        # 添加足够的金条
        self.manor.gold_bar = 100
        self.manor.save()

        # 升级帮会
        guild_service.upgrade_guild(guild, self.user)

        guild.refresh_from_db()
        self.assertEqual(guild.level, 2)
        self.assertEqual(guild.member_capacity, 12)
```

### 10.2 集成测试
```python
# guilds/tests/test_views.py

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

class GuildViewsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.client.login(username='testuser', password='testpass')

    def test_guild_hall_view(self):
        """测试帮会大厅页面"""
        response = self.client.get(reverse('guilds:hall'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'guilds/hall.html')

    def test_create_guild_view(self):
        """测试创建帮会"""
        response = self.client.post(reverse('guilds:create'), {
            'name': '测试帮会',
            'description': '测试描述',
            'emblem': 'default'
        })
        self.assertEqual(response.status_code, 302)  # 重定向到帮会详情
```

### 10.3 功能测试清单
- [ ] 创建帮会（正常流程、异常情况）
- [ ] 申请加入帮会
- [ ] 审批入帮申请（通过/拒绝）
- [ ] 自动审批功能
- [ ] 成员退出帮会
- [ ] 辞退成员
- [ ] 任命管理员
- [ ] 罢免管理员
- [ ] 转让帮主
- [ ] 解散帮会
- [ ] 帮会升级
- [ ] 资源捐赠
- [ ] 贡献度计算
- [ ] 每日捐赠限制
- [ ] 本周贡献重置
- [ ] 科技升级
- [ ] 科技加成应用（门客、兵种、资源、行军）
- [ ] 科技每日产出
- [ ] 仓库物品兑换
- [ ] 每日兑换限制
- [ ] 帮会公告发布
- [ ] 系统公告自动生成

---

## 十一、开发实施计划

### 11.1 开发阶段

#### 第一阶段：基础架构（2-3天）
1. 创建guilds应用
2. 定义数据模型
3. 生成数据库迁移
4. 创建服务层目录结构
5. 配置URL路由

**交付物**:
- 完整的数据模型
- 数据库迁移文件
- 基础的服务层框架

#### 第二阶段：核心功能（5-7天）
1. 实现帮会创建与管理服务
2. 实现成员管理服务
3. 实现贡献度系统
4. 编写视图函数
5. 创建前端模板

**交付物**:
- 帮会创建功能
- 加入/退出帮会功能
- 成员管理功能
- 资源捐赠功能
- 基础UI页面

#### 第三阶段：科技与仓库（4-5天）
1. 实现科技系统服务
2. 实现仓库与兑换服务
3. 集成科技加成到现有系统
4. 创建科技和仓库页面
5. 实现Celery定时任务

**交付物**:
- 科技升级功能
- 科技加成生效
- 仓库兑换功能
- 每日产出任务

#### 第四阶段：测试与优化（2-3天）
1. 编写单元测试
2. 进行集成测试
3. 性能优化
4. Bug修复
5. 文档完善

**交付物**:
- 完整的测试套件
- 性能优化报告
- 开发文档

### 11.2 总体时间估算
- **开发时间**: 13-18天
- **测试时间**: 2-3天
- **总计**: 15-21天

### 11.3 里程碑
- **M1**: 基础架构完成（第3天）
- **M2**: 核心功能完成（第10天）
- **M3**: 全部功能完成（第15天）
- **M4**: 测试与上线（第21天）

---

## 十二、后续扩展规划

### 12.1 短期扩展（3个月内）
1. **帮会任务系统**
   - 每日帮会任务
   - 完成任务获得帮贡
   - 任务奖励机制

2. **帮会活动**
   - 每周帮会活动
   - 活动排行榜
   - 特殊奖励

3. **帮会商店**
   - 独有装备
   - 稀有道具
   - 限时商品

### 12.2 中期扩展（6个月内）
1. **帮会战系统**
   - 帮会间对战
   - 战斗积分
   - 赛季奖励

2. **帮会领地**
   - 占领地盘
   - 地盘产出
   - 地盘争夺

3. **帮会建筑**
   - 可升级的帮会建筑
   - 建筑特殊功能
   - 建筑外观展示

### 12.3 长期扩展（1年内）
1. **跨服帮会战**
   - 跨服匹配
   - 服务器排名
   - 跨服奖励

2. **帮会联盟**
   - 多帮会联盟
   - 联盟科技
   - 联盟战争

---

## 十三、注意事项

### 13.1 性能优化
- 使用`select_related`和`prefetch_related`优化查询
- 帮会列表添加分页
- 日志表定期清理
- 添加适当的数据库索引

### 13.2 安全考虑
- 所有操作需验证权限
- 防止SQL注入
- 防止XSS攻击
- 敏感操作需二次确认

### 13.3 用户体验
- 操作反馈清晰
- 错误提示友好
- 加载状态提示
- 移动端适配

### 13.4 数据一致性
- 使用事务保证原子性
- 并发操作加锁
- 定期数据校验
- 异常数据修复机制

---

## 十四、附录

### 14.1 配置文件模板
```python
# guilds/config.py

# 帮会配置
GUILD_CONFIG = {
    # 创建成本
    'creation_cost': {
        'gold_bar': 2,
    },

    # 升级成本
    'upgrade_base_cost': 5,

    # 成员上限
    'base_capacity': 10,
    'capacity_per_level': 2,
    'max_level': 10,

    # 职位限制
    'max_admins': 2,

    # 捐赠配置
    'contribution_rates': {
        'silver': 1,
        'grain': 2,
    },
    'daily_donation_limits': {
        'silver': 100000,
        'grain': 50000,
    },
    'min_donation_amount': 100,

    # 兑换配置
    'daily_exchange_limit': 10,

    # 日志保留
    'log_retention_days': 30,
}
```

### 14.2 数据库索引建议
```sql
-- 帮会查询优化
CREATE INDEX idx_guilds_active_level ON guilds(is_active, level DESC);
CREATE INDEX idx_guilds_name ON guilds(name) WHERE is_active = true;

-- 成员查询优化
CREATE INDEX idx_guild_members_active ON guild_members(guild_id, is_active, position);
CREATE INDEX idx_guild_members_contribution ON guild_members(guild_id, total_contribution DESC);

-- 日志查询优化
CREATE INDEX idx_donation_logs_time ON guild_donation_logs(guild_id, donated_at DESC);
CREATE INDEX idx_exchange_logs_time ON guild_exchange_logs(guild_id, exchanged_at DESC);
```

### 14.3 常见问题FAQ
**Q: 帮会解散后成员的贡献度怎么办？**
A: 贡献度记录保留在GuildMember表中，即使帮会解散，数据也不会删除，可用于统计和历史查询。

**Q: 科技加成如何实时生效？**
A: 科技加成在每次计算时动态获取，确保升级后立即生效。

**Q: 如何防止恶意刷帮贡？**
A: 设置了每日捐赠上限和单次最小捐赠量，同时记录完整的捐赠日志便于审计。

**Q: 帮会仓库容量不够怎么办？**
A: 初期设置200格容量，后续可通过升级帮会建筑扩容（预留扩展点）。

---

## 文档变更记录

| 版本 | 日期 | 修改人 | 修改内容 |
|------|------|--------|----------|
| 1.0  | 2025-12-04 | Claude | 初始版本 |

---

**文档结束**

