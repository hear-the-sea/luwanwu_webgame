# 打工系统开发文档

## 1. 功能概述

打工系统允许玩家派遣门客前往不同的工作地点打工，获得银两报酬。系统分为三个工作区：初级工作区、中级工作区和高级工作区，每个工作地点有不同的等级要求和报酬。

### 1.1 核心特性

- 三级工作区分类：初级、中级、高级
- 每个工作地点有独立的等级要求
- 打工需要消耗时间（建议2-4小时）
- 打工完成后获得银两报酬
- 门客打工期间状态为"打工中"，无法参与其他活动
- 可以提前召回门客，但无法获得报酬

## 2. 工作地点配置

### 2.1 初级工作区（等级3-13）

| 工作地点 | 简介 | 报酬 | 等级要求 | 武力要求 | 智力要求 | 打工时长 |
|---------|------|------|---------|---------|---------|---------|
| 酒楼 | 城市中的酒楼，因物廉价满生意很好，每天都在招募人手。 | 1000 | 3 | 0 | 0 | 2小时 |
| 医馆 | 一家老字号的医馆叫"济世堂"，目前正在招募学徒。 | 1500 | 5 | 0 | 0 | 2小时 |
| 驿站 | 驿站是传递宫府文书、情报的人或来往官员途中食宿，换马的场所，目前正在招募送递使者。 | 2000 | 7 | 0 | 0 | 2小时 |
| 书院 | 书院为乐育人才之地，希望有文德兼美之士入院职教。 | 2500 | 9 | 0 | 0 | 2小时 |
| 茶馆 | 上午卖清茶，下午和晚上请艺人临场说评书，茶客边听书，边饮茶，倒也优哉游哉，乐乐陶陶。 | 3000 | 11 | 0 | 0 | 2小时 |
| 码头 | 码头是商人用货船卸货的地方，人来人往非常的热闹繁忙！ | 3500 | 13 | 0 | 0 | 2小时 |

### 2.2 中级工作区（等级14-17）

| 工作地点 | 简介 | 报酬 | 等级要求 | 武力要求 | 智力要求 | 打工时长 |
|---------|------|------|---------|---------|---------|---------|
| 武馆 | 城中武馆招募陪练，需要一定武艺基础。 | 4000 | 14 | 0 | 0 | 3小时 |
| 商行 | 大型商行招募账房和伙计，需要处理复杂账目。 | 4500 | 15 | 0 | 0 | 3小时 |
| 官府 | 地方官府招募文书，协助处理政务。 | 5000 | 16 | 0 | 0 | 3小时 |
| 钱庄 | 城中钱庄招募护卫和账房，待遇优渥。 | 5500 | 17 | 0 | 0 | 3小时 |

### 2.3 高级工作区（等级18+）

| 工作地点 | 简介 | 报酬 | 等级要求 | 武力要求 | 智力要求 | 打工时长 |
|---------|------|------|---------|---------|---------|---------|
| 镖局 | 城中一家镖局目前正在扩大规模，目前正在招募武艺高强的镖师。 | 6000 | 18 | 0 | 0 | 4小时 |
| 精武盟 | 精武盟势力分部全国，成员皆为武艺高强之辈，为武林中最强势力。 | 7000 | 23 | 0 | 0 | 4小时 |
| 神风驿 | 神风驿为全国最高等级驿站，送递情报日行千里。 | 8000 | 28 | 0 | 0 | 4小时 |
| 国子监 | 国子监全国中央官学，为国内教育体系中的最高学府。 | 9000 | 33 | 0 | 0 | 4小时 |

## 3. 数据模型设计

### 3.1 WorkTemplate（工作模板）

```python
class WorkTemplate(models.Model):
    """工作地点模板"""

    class Tier(models.TextChoices):
        JUNIOR = "junior", "初级工作区"
        INTERMEDIATE = "intermediate", "中级工作区"
        SENIOR = "senior", "高级工作区"

    key = models.SlugField(unique=True, verbose_name="工作标识")
    name = models.CharField(max_length=64, verbose_name="工作名称")
    description = models.TextField(blank=True, verbose_name="工作简介")
    tier = models.CharField(
        max_length=16,
        choices=Tier.choices,
        default=Tier.JUNIOR,
        verbose_name="工作区等级"
    )

    # 工作要求
    required_level = models.PositiveIntegerField(default=1, verbose_name="等级要求")
    required_force = models.PositiveIntegerField(default=0, verbose_name="武力要求")
    required_intellect = models.PositiveIntegerField(default=0, verbose_name="智力要求")

    # 工作报酬
    reward_silver = models.PositiveIntegerField(default=0, verbose_name="银两报酬")

    # 工作时长（秒）
    work_duration = models.PositiveIntegerField(default=7200, verbose_name="工作时长")

    # 显示顺序
    display_order = models.PositiveIntegerField(default=0, verbose_name="显示顺序")

    # 图标
    icon = models.CharField(max_length=32, blank=True, verbose_name="图标")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "工作模板"
        verbose_name_plural = "工作模板"
        ordering = ["tier", "display_order", "required_level"]

    def __str__(self):
        return f"{self.name}（{self.get_tier_display()}）"
```

### 3.2 WorkAssignment（打工记录）

```python
class WorkAssignment(models.Model):
    """门客打工记录"""

    class Status(models.TextChoices):
        WORKING = "working", "打工中"
        COMPLETED = "completed", "已完成"
        RECALLED = "recalled", "已召回"

    manor = models.ForeignKey(
        "gameplay.Manor",
        on_delete=models.CASCADE,
        related_name="work_assignments",
        verbose_name="庄园"
    )
    guest = models.ForeignKey(
        "guests.Guest",
        on_delete=models.CASCADE,
        related_name="work_assignments",
        verbose_name="门客"
    )
    work_template = models.ForeignKey(
        WorkTemplate,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="工作地点"
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.WORKING,
        verbose_name="状态"
    )

    # 时间记录
    started_at = models.DateTimeField(auto_now_add=True, verbose_name="开始时间")
    complete_at = models.DateTimeField(verbose_name="完成时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="实际完成时间")

    # 报酬记录
    reward_claimed = models.BooleanField(default=False, verbose_name="已领取报酬")

    class Meta:
        verbose_name = "打工记录"
        verbose_name_plural = "打工记录"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status", "-started_at"]),
            models.Index(fields=["guest", "-started_at"]),
        ]

    def __str__(self):
        return f"{self.guest.name} - {self.work_template.name}"

    @property
    def time_remaining(self) -> int:
        """剩余时间（秒）"""
        if self.status != self.Status.WORKING:
            return 0
        from django.utils import timezone
        delta = self.complete_at - timezone.now()
        return max(0, int(delta.total_seconds()))

    @property
    def is_ready_to_claim(self) -> bool:
        """是否可以领取"""
        return (
            self.status == self.Status.COMPLETED
            and not self.reward_claimed
        )
```

## 4. 门客状态扩展

需要在 `guests.models.Guest` 的 `GuestStatus` 中添加新状态：

```python
class GuestStatus(models.TextChoices):
    IDLE = "idle", "待命"
    TRAINING = "training", "训练中"
    WORKING = "working", "打工中"  # 新增
    MISSION = "mission", "出征中"
    BATTLE = "battle", "战斗中"
```

## 5. 业务逻辑设计

### 5.1 核心服务方法（work/services.py）

```python
# 获取可用的工作列表
def get_available_works(guest: Guest) -> List[WorkTemplate]
    """获取门客可接受的工作列表"""

# 派遣门客打工
def assign_guest_to_work(guest: Guest, work_template: WorkTemplate) -> WorkAssignment
    """派遣门客打工"""

# 完成打工（定时任务）
def complete_work_assignments() -> int
    """完成所有到期的打工任务"""

# 召回门客
def recall_guest_from_work(assignment: WorkAssignment) -> bool
    """召回打工中的门客"""

# 领取报酬
def claim_work_reward(assignment: WorkAssignment) -> Dict[str, int]
    """领取打工报酬"""

# 刷新打工状态
def refresh_work_assignments(manor: Manor) -> None
    """刷新打工状态，自动完成到期的任务"""
```

### 5.2 业务规则

1. **派遣条件检查**
   - 门客必须为"待命"状态
   - 门客等级满足工作要求
   - 门客武力、智力满足工作要求

2. **打工流程**
   - 派遣打工：设置门客状态为"打工中"，创建WorkAssignment记录
   - 计算完成时间：started_at + work_duration
   - 定时检查：每分钟检查一次是否有完成的打工任务
   - 自动完成：到期后状态改为"已完成"，门客状态改为"待命"

3. **领取报酬**
   - 仅完成状态且未领取的任务可领取
   - 领取后增加庄园银两
   - 记录资源流水

4. **召回机制**
   - 仅"打工中"状态可召回
   - 召回后门客状态改为"待命"
   - 不发放任何报酬

## 6. URL 路由设计

```python
# gameplay/urls.py
urlpatterns = [
    # ... 现有路由

    # 打工系统
    path("work/", WorkView.as_view(), name="work"),
    path("work/assign/", assign_work_view, name="assign_work"),
    path("work/recall/<int:pk>/", recall_work_view, name="recall_work"),
    path("work/claim/<int:pk>/", claim_work_reward_view, name="claim_work_reward"),
]
```

## 7. 视图设计

### 7.1 WorkView（打工页面）

```python
class WorkView(LoginRequiredMixin, TemplateView):
    """打工页面"""
    template_name = "gameplay/work.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        manor = ensure_manor(self.request.user)

        # 刷新状态
        refresh_work_assignments(manor)

        # 获取所有工作模板，按等级分组
        junior_works = WorkTemplate.objects.filter(tier=WorkTemplate.Tier.JUNIOR)
        intermediate_works = WorkTemplate.objects.filter(tier=WorkTemplate.Tier.INTERMEDIATE)
        senior_works = WorkTemplate.objects.filter(tier=WorkTemplate.Tier.SENIOR)

        # 获取所有待命的门客
        idle_guests = manor.guests.filter(status=GuestStatus.IDLE)

        # 获取正在打工的记录
        working_assignments = manor.work_assignments.filter(
            status=WorkAssignment.Status.WORKING
        ).select_related("guest", "work_template")

        # 获取可领取的记录
        claimable_assignments = manor.work_assignments.filter(
            status=WorkAssignment.Status.COMPLETED,
            reward_claimed=False
        ).select_related("guest", "work_template")

        context.update({
            "manor": manor,
            "junior_works": junior_works,
            "intermediate_works": intermediate_works,
            "senior_works": senior_works,
            "idle_guests": idle_guests,
            "working_assignments": working_assignments,
            "claimable_assignments": claimable_assignments,
        })

        return context
```

### 7.2 派遣打工视图

```python
@login_required
@require_POST
def assign_work_view(request):
    """派遣门客打工"""
    guest_id = request.POST.get("guest_id")
    work_key = request.POST.get("work_key")

    manor = ensure_manor(request.user)
    guest = get_object_or_404(Guest, id=guest_id, manor=manor)
    work_template = get_object_or_404(WorkTemplate, key=work_key)

    try:
        assignment = assign_guest_to_work(guest, work_template)
        messages.success(request, f"{guest.name} 已前往 {work_template.name} 打工")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect("gameplay:work")
```

### 7.3 召回门客视图

```python
@login_required
@require_POST
def recall_work_view(request, pk):
    """召回打工中的门客"""
    manor = ensure_manor(request.user)
    assignment = get_object_or_404(
        WorkAssignment,
        id=pk,
        manor=manor,
        status=WorkAssignment.Status.WORKING
    )

    if recall_guest_from_work(assignment):
        messages.success(request, f"{assignment.guest.name} 已从 {assignment.work_template.name} 召回")
    else:
        messages.error(request, "召回失败")

    return redirect("gameplay:work")
```

### 7.4 领取报酬视图

```python
@login_required
@require_POST
def claim_work_reward_view(request, pk):
    """领取打工报酬"""
    manor = ensure_manor(request.user)
    assignment = get_object_or_404(
        WorkAssignment,
        id=pk,
        manor=manor
    )

    try:
        reward = claim_work_reward(assignment)
        messages.success(request, f"获得银两 {reward['silver']}")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect("gameplay:work")
```

## 8. 模板设计

### 8.1 页面布局

```
gameplay/templates/gameplay/work.html

├── 页面标题："打工"
├── 资源显示栏（银两）
├── 正在打工区域
│   └── 显示正在打工的门客、工作地点、剩余时间、召回按钮
├── 可领取报酬区域
│   └── 显示已完成的工作、门客、报酬、领取按钮
├── 初级工作区
│   └── 工作卡片列表（名称、描述、要求、报酬、派遣按钮）
├── 中级工作区
│   └── 工作卡片列表
└── 高级工作区
    └── 工作卡片列表
```

### 8.2 工作卡片设计

每个工作卡片包含：
- 工作名称
- 工作描述
- 等级要求（红色显示如果不满足）
- 武力要求（红色显示如果不满足）
- 智力要求（红色显示如果不满足）
- 报酬显示
- 工作时长
- 派遣下拉框（选择门客）+ 派遣按钮

## 9. 定时任务设计

### 9.1 Celery 定时任务

```python
# gameplay/tasks.py

@celery_app.task
def complete_work_assignments_task():
    """定时完成到期的打工任务"""
    from gameplay.services.work import complete_work_assignments
    count = complete_work_assignments()
    return f"完成 {count} 个打工任务"

# config/celery.py
app.conf.beat_schedule = {
    # ... 现有任务

    'complete-work-assignments': {
        'task': 'gameplay.tasks.complete_work_assignments_task',
        'schedule': crontab(minute='*/1'),  # 每分钟执行一次
    },
}
```

## 10. 数据迁移

### 10.1 创建初始数据迁移

```python
# gameplay/migrations/0XXX_seed_work_templates.py

from django.db import migrations

def create_work_templates(apps, schema_editor):
    WorkTemplate = apps.get_model("gameplay", "WorkTemplate")

    # 初级工作区
    junior_works = [
        {"key": "jiulou", "name": "酒楼", "description": "城市中的酒楼，因物廉价满生意很好，每天都在招募人手。", "tier": "junior", "required_level": 3, "reward_silver": 1000, "work_duration": 7200, "display_order": 1},
        {"key": "yiguan", "name": "医馆", "description": "一家老字号的医馆叫"济世堂"，目前正在招募学徒。", "tier": "junior", "required_level": 5, "reward_silver": 1500, "work_duration": 7200, "display_order": 2},
        {"key": "yizhan", "name": "驿站", "description": "驿站是传递宫府文书、情报的人或来往官员途中食宿，换马的场所，目前正在招募送递使者。", "tier": "junior", "required_level": 7, "reward_silver": 2000, "work_duration": 7200, "display_order": 3},
        {"key": "shuyuan", "name": "书院", "description": "书院为乐育人才之地，希望有文德兼美之士入院职教。", "tier": "junior", "required_level": 9, "reward_silver": 2500, "work_duration": 7200, "display_order": 4},
        {"key": "chaguan", "name": "茶馆", "description": "上午卖清茶，下午和晚上请艺人临场说评书，茶客边听书，边饮茶，倒也优哉游哉，乐乐陶陶。", "tier": "junior", "required_level": 11, "reward_silver": 3000, "work_duration": 7200, "display_order": 5},
        {"key": "matou", "name": "码头", "description": "码头是商人用货船卸货的地方，人来人往非常的热闹繁忙！", "tier": "junior", "required_level": 13, "reward_silver": 3500, "work_duration": 7200, "display_order": 6},
    ]

    # 中级工作区
    intermediate_works = [
        {"key": "wuguan", "name": "武馆", "description": "城中武馆招募陪练，需要一定武艺基础。", "tier": "intermediate", "required_level": 14, "reward_silver": 4000, "work_duration": 10800, "display_order": 1},
        {"key": "shanghang", "name": "商行", "description": "大型商行招募账房和伙计，需要处理复杂账目。", "tier": "intermediate", "required_level": 15, "reward_silver": 4500, "work_duration": 10800, "display_order": 2},
        {"key": "guanfu", "name": "官府", "description": "地方官府招募文书，协助处理政务。", "tier": "intermediate", "required_level": 16, "reward_silver": 5000, "work_duration": 10800, "display_order": 3},
        {"key": "qianzhuang", "name": "钱庄", "description": "城中钱庄招募护卫和账房，待遇优渥。", "tier": "intermediate", "required_level": 17, "reward_silver": 5500, "work_duration": 10800, "display_order": 4},
    ]

    # 高级工作区
    senior_works = [
        {"key": "biaoju", "name": "镖局", "description": "城中一家镖局目前正在扩大规模，目前正在招募武艺高强的镖师。", "tier": "senior", "required_level": 18, "reward_silver": 6000, "work_duration": 14400, "display_order": 1},
        {"key": "jingwumeng", "name": "精武盟", "description": "精武盟势力分部全国，成员皆为武艺高强之辈，为武林中最强势力。", "tier": "senior", "required_level": 23, "reward_silver": 7000, "work_duration": 14400, "display_order": 2},
        {"key": "shenfengyi", "name": "神风驿", "description": "神风驿为全国最高等级驿站，送递情报日行千里。", "tier": "senior", "required_level": 28, "reward_silver": 8000, "work_duration": 14400, "display_order": 3},
        {"key": "guozijian", "name": "国子监", "description": "国子监全国中央官学，为国内教育体系中的最高学府。", "tier": "senior", "required_level": 33, "reward_silver": 9000, "work_duration": 14400, "display_order": 4},
    ]

    for work_data in junior_works + intermediate_works + senior_works:
        WorkTemplate.objects.create(**work_data)

class Migration(migrations.Migration):
    dependencies = [
        ('gameplay', '0XXX_add_work_models'),  # 依赖模型创建迁移
    ]

    operations = [
        migrations.RunPython(create_work_templates, migrations.RunPython.noop),
    ]
```

## 11. 开发步骤

### 第一阶段：模型和迁移
1. 创建 `WorkTemplate` 和 `WorkAssignment` 模型
2. 在 `GuestStatus` 中添加 `WORKING` 状态
3. 在 `ResourceEvent.Reason` 中添加 `WORK_REWARD` 原因
4. 运行 `makemigrations` 和 `migrate`
5. 创建初始数据迁移，填充工作模板

### 第二阶段：业务逻辑
1. 创建 `gameplay/services/work.py`
2. 实现核心服务方法
3. 编写单元测试

### 第三阶段：视图和路由
1. 在 `gameplay/views.py` 中添加视图
2. 在 `gameplay/urls.py` 中添加路由
3. 测试视图逻辑

### 第四阶段：模板和前端
1. 创建 `gameplay/templates/gameplay/work.html`
2. 添加页面样式
3. 实现交互逻辑（派遣、召回、领取）

### 第五阶段：定时任务
1. 在 `gameplay/tasks.py` 中添加定时任务
2. 在 `config/celery.py` 中配置任务调度
3. 测试定时任务

### 第六阶段：集成和测试
1. 在导航栏添加"打工"链接
2. 集成测试所有功能
3. 性能测试和优化

### 第七阶段：后台管理
1. 在 `gameplay/admin.py` 中注册模型
2. 添加管理界面自定义

## 12. 技术要点

### 12.1 性能优化
- 使用 `select_related` 和 `prefetch_related` 优化查询
- 为状态和时间字段添加数据库索引
- 缓存工作模板数据

### 12.2 并发控制
- 使用事务确保派遣打工的原子性
- 使用 `select_for_update()` 防止重复派遣

### 12.3 用户体验
- 实时显示剩余时间（JavaScript 倒计时）
- 使用 AJAX 提交表单，避免页面刷新
- 提供清晰的错误提示

## 13. 扩展功能（可选）

### 13.1 高级特性
- 批量派遣：一次派遣多个门客
- 自动打工：门客完成后自动继续打工
- 打工加成：根据门客属性增加报酬
- 打工事件：打工过程中随机触发事件
- 每日打工限制：每个工作地点每天限制次数

### 13.2 统计功能
- 打工历史记录
- 收入统计图表
- 门客打工排行榜

## 14. 附录

### 14.1 时长参考
- 初级工作：2小时（7200秒）
- 中级工作：3小时（10800秒）
- 高级工作：4小时（14400秒）

### 14.2 报酬平衡
按等级梯度设计，确保玩家有动力升级门客：
- 等级3-13：1000-3500银两
- 等级14-17：4000-5500银两
- 等级18-33：6000-9000银两

### 14.3 数据库表关系
```
Manor (1) ----< (N) WorkAssignment
Guest (1) ----< (N) WorkAssignment
WorkTemplate (1) ----< (N) WorkAssignment
```
