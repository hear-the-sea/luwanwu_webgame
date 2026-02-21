# 春秋乱世庄园主 - 数据库设计文档

本文档详细描述了游戏的数据库结构，包括所有数据表、字段定义、索引和表间关系。

---

## 数据库概览

### 技术选型

| 环境 | 数据库 | 说明 |
|------|--------|------|
| 开发 | SQLite | 零配置，快速启动 |
| 生产 | MySQL 8.0+ | 推荐，支持连接池 |
| 测试 | SQLite (内存) | 自动隔离 |

### 模块划分

| Django App | 数据表数量 | 核心职责 |
|------------|------------|----------|
| accounts | 1 | 用户认证 |
| gameplay | 12 | 庄园、建筑、物品、任务、科技、打工 |
| guests | 12 | 门客、技能、装备、招募 |
| battle | 2 | 战斗、兵种 |
| trade | 6 | 商店、交易行、银庄 |
| guilds | 9 | 帮会系统 |

---

## ER 关系图

```
                                    ┌─────────────┐
                                    │    User     │
                                    │  (accounts) │
                                    └──────┬──────┘
                                           │ 1:1
                                           ▼
                                    ┌─────────────┐
                           ┌────────│    Manor    │────────┐
                           │        │ (gameplay)  │        │
                           │        └──────┬──────┘        │
                           │               │               │
              ┌────────────┼───────────────┼───────────────┼────────────┐
              │            │               │               │            │
              ▼            ▼               ▼               ▼            ▼
       ┌──────────┐ ┌──────────┐   ┌──────────┐   ┌──────────┐  ┌──────────┐
       │ Building │ │  Guest   │   │InventoryItem│ │MissionRun│  │ Message  │
       └──────────┘ └────┬─────┘   └──────────┘   └──────────┘  └──────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
    ┌──────────┐  ┌──────────┐   ┌──────────┐
    │ GearItem │  │GuestSkill│   │SkillBook │
    └──────────┘  └──────────┘   └──────────┘
```

---

## 账户模块 (accounts)

### User 表

继承 Django AbstractUser，扩展用户功能。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| username | VARCHAR(150) | UNIQUE, NOT NULL | 用户名 |
| password | VARCHAR(128) | NOT NULL | 密码哈希 |
| email | VARCHAR(254) | | 邮箱 |
| is_active | BOOLEAN | DEFAULT TRUE | 账号状态 |
| date_joined | DATETIME | AUTO | 注册时间 |
| last_login | DATETIME | | 最后登录 |

**索引：**
- `username` - UNIQUE INDEX

---

## 庄园模块 (gameplay)

### Manor 表

玩家庄园核心数据。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| user_id | BigInt | FK(User), UNIQUE | 所属用户 |
| name | VARCHAR(50) | DEFAULT "我的庄园" | 庄园名称 |
| wood | INT | DEFAULT 1000 | 木材 |
| stone | INT | DEFAULT 1000 | 石料 |
| iron | INT | DEFAULT 500 | 铁矿 |
| grain | INT | DEFAULT 2000 | 粮食 |
| silver | INT | DEFAULT 10000 | 银两 |
| retainer_count | INT | DEFAULT 0 | 家丁数量 |
| created_at | DATETIME | AUTO | 创建时间 |
| updated_at | DATETIME | AUTO | 更新时间 |

**索引：**
- `user_id` - UNIQUE INDEX
- `created_at` - INDEX

**关联：**
- `User` 1:1 关系
- `Building` 1:N 关系
- `Guest` 1:N 关系
- `InventoryItem` 1:N 关系

**计算属性：**
- `guest_capacity` - 门客容量（基础值 + 聚贤庄等级加成）
- `retainer_capacity` - 家丁容量（基础值 + 建筑加成）
- `max_squad_size` - 出战门客上限（基础5，最高15）

---

### BuildingType 表

建筑类型定义（配置数据）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 建筑标识 |
| name | VARCHAR(100) | NOT NULL | 建筑名称 |
| description | TEXT | | 描述 |
| resource_type | VARCHAR(20) | | 产出资源类型 |
| base_production | INT | DEFAULT 0 | 基础产量 |
| max_level | INT | DEFAULT 10 | 最高等级 |
| icon | VARCHAR(100) | | 图标路径 |

**预设建筑：**
- `lumberyard` - 伐木场（产木材）
- `quarry` - 采石场（产石料）
- `mine` - 矿场（产铁矿）
- `farm` - 农场（产粮食）
- `market` - 集市（产银两）
- `juxianzhuang` - 聚贤庄（增加门客容量）
- `retainer_hall` - 家丁营（增加家丁容量）
- `youxibaota` - 游戏宝塔（解锁功能）

---

### Building 表

玩家建筑实例。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| building_type_id | BigInt | FK(BuildingType) | 建筑类型 |
| level | INT | DEFAULT 1 | 当前等级 |
| is_upgrading | BOOLEAN | DEFAULT FALSE | 是否升级中 |
| upgrade_complete_at | DATETIME | NULL | 升级完成时间 |

**索引：**
- (`manor_id`, `building_type_id`) - UNIQUE INDEX
- `upgrade_complete_at` - INDEX (用于定时任务扫描)

---

### ItemTemplate 表

物品模板定义。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 物品标识 |
| name | VARCHAR(100) | NOT NULL | 物品名称 |
| description | TEXT | | 描述 |
| icon | VARCHAR(100) | | 图标 |
| image | VARCHAR(100) | | 大图 |
| effect_type | VARCHAR(50) | | 效果类型 |
| effect_value | INT | DEFAULT 0 | 效果数值 |
| rarity | VARCHAR(20) | DEFAULT "gray" | 稀有度 |
| tradeable | BOOLEAN | DEFAULT TRUE | 可否交易 |
| price | INT | DEFAULT 0 | 基础价格 |
| stack_limit | INT | DEFAULT 99 | 堆叠上限 |

**效果类型枚举：**
- `resource_pack` - 资源包
- `exp_item` - 经验道具
- `medicine` - 药品
- `magnifying_glass` - 放大镜
- `skill_book` - 技能书
- `gold_bar` - 金条

**稀有度枚举：**
- `black` (1星) → `gray` (2星) → `green` (3星) → `blue` (4星) → `red` (5星) → `purple` (6星) → `orange` (7星)

---

### InventoryItem 表

玩家物品库存。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| template_id | BigInt | FK(ItemTemplate) | 物品模板 |
| quantity | INT | DEFAULT 1 | 数量 |
| storage_location | VARCHAR(20) | DEFAULT "warehouse" | 存储位置 |
| created_at | DATETIME | AUTO | 获取时间 |

**存储位置枚举：**
- `warehouse` - 仓库
- `treasury` - 藏宝阁

**索引：**
- (`manor_id`, `template_id`, `storage_location`) - UNIQUE INDEX

---

### Message 表

系统/战报消息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| title | VARCHAR(200) | NOT NULL | 标题 |
| content | TEXT | | 内容 |
| message_type | VARCHAR(20) | DEFAULT "system" | 消息类型 |
| is_read | BOOLEAN | DEFAULT FALSE | 是否已读 |
| battle_report_id | BigInt | FK(BattleReport), NULL | 关联战报 |
| attachments | JSON | | 附件（资源/物品） |
| attachment_claimed | BOOLEAN | DEFAULT FALSE | 附件是否领取 |
| created_at | DATETIME | AUTO | 创建时间 |

**消息类型：**
- `system` - 系统消息
- `battle` - 战报
- `reward` - 奖励
- `guild` - 帮会消息

**索引：**
- (`manor_id`, `is_read`) - INDEX
- `created_at` - INDEX

---

### MissionTemplate 表

任务模板定义。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 任务标识 |
| name | VARCHAR(100) | NOT NULL | 任务名称 |
| description | TEXT | | 描述 |
| difficulty | INT | DEFAULT 1 | 难度等级 |
| travel_time | INT | DEFAULT 60 | 行军时间（秒） |
| daily_limit | INT | DEFAULT 5 | 每日次数限制 |
| enemy_guests | JSON | | 敌方门客配置 |
| enemy_troops | JSON | | 敌方兵种配置 |
| drop_table | JSON | | 固定掉落 |
| probability_drop_table | JSON | | 概率掉落 |
| resource_cost | JSON | | 消耗资源 |

---

### MissionRun 表

任务执行记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| mission_id | BigInt | FK(MissionTemplate) | 任务模板 |
| status | VARCHAR(20) | DEFAULT "active" | 状态 |
| is_retreating | BOOLEAN | DEFAULT FALSE | 是否撤退中 |
| troops | JSON | | 携带兵种 |
| started_at | DATETIME | AUTO | 出发时间 |
| battle_at | DATETIME | | 战斗时间 |
| return_at | DATETIME | | 返程时间 |
| finished_at | DATETIME | | 完成时间 |
| battle_report_id | BigInt | FK(BattleReport), NULL | 战报 |

**状态枚举：**
- `active` - 进行中
- `completed` - 已完成
- `retreated` - 已撤退

**索引：**
- (`manor_id`, `status`) - INDEX
- `battle_at` - INDEX

**M2M 关系：**
- `guests` - 参战门客（ManyToMany via `mission_run_guests`）

---

### ResourceEvent 表

资源变动日志。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| resource_type | VARCHAR(20) | NOT NULL | 资源类型 |
| amount | INT | NOT NULL | 变动数量（正/负） |
| reason | VARCHAR(50) | NOT NULL | 变动原因 |
| created_at | DATETIME | AUTO | 发生时间 |

**变动原因枚举：**
- `production` - 建筑产出
- `mission_reward` - 任务奖励
- `mission_cost` - 任务消耗
- `building_upgrade` - 建筑升级
- `shop_buy` - 商店购买
- `shop_sell` - 商店出售
- `salary` - 工资支出
- `work_reward` - 打工收入
- `donate` - 帮会捐赠
- `guild_exchange` - 帮会兑换

---

### PlayerTechnology 表

玩家科技等级。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| tech_key | VARCHAR(50) | NOT NULL | 科技标识 |
| level | INT | DEFAULT 0 | 当前等级 |
| is_upgrading | BOOLEAN | DEFAULT FALSE | 是否升级中 |
| upgrade_complete_at | DATETIME | NULL | 完成时间 |

**索引：**
- (`manor_id`, `tech_key`) - UNIQUE INDEX

---

### WorkTemplate 表

打工工作定义。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 工作标识 |
| name | VARCHAR(100) | NOT NULL | 工作名称 |
| description | TEXT | | 描述 |
| tier | VARCHAR(20) | NOT NULL | 工作区等级 |
| work_duration | INT | NOT NULL | 工作时长（秒） |
| base_silver | INT | NOT NULL | 基础银两奖励 |
| display_order | INT | DEFAULT 0 | 显示顺序 |

**工作区等级：**
- `junior` - 初级（2小时）
- `intermediate` - 中级（3小时）
- `senior` - 高级（4小时）

---

### WorkAssignment 表

打工任务记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| guest_id | BigInt | FK(Guest) | 门客 |
| work_template_id | BigInt | FK(WorkTemplate) | 工作模板 |
| status | VARCHAR(20) | DEFAULT "working" | 状态 |
| started_at | DATETIME | AUTO | 开始时间 |
| complete_at | DATETIME | | 完成时间 |
| finished_at | DATETIME | NULL | 实际结束时间 |
| reward_claimed | BOOLEAN | DEFAULT FALSE | 奖励是否领取 |

**状态枚举：**
- `working` - 进行中
- `completed` - 已完成
- `cancelled` - 已取消

---

## 门客模块 (guests)

### GuestTemplate 表

门客模板定义。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 门客标识 |
| name | VARCHAR(100) | NOT NULL | 门客名称 |
| title | VARCHAR(100) | | 称号 |
| description | TEXT | | 描述 |
| portrait | VARCHAR(100) | | 头像 |
| rarity | VARCHAR(20) | DEFAULT "gray" | 稀有度 |
| archetype | VARCHAR(20) | DEFAULT "warrior" | 职业类型 |
| element | VARCHAR(20) | | 五行属性 |
| base_force | INT | DEFAULT 10 | 基础武力 |
| base_intellect | INT | DEFAULT 10 | 基础智力 |
| base_defense | INT | DEFAULT 10 | 基础防御 |
| base_agility | INT | DEFAULT 10 | 基础敏捷 |
| base_luck | INT | DEFAULT 10 | 基础运气 |
| force_growth | FLOAT | DEFAULT 1.0 | 武力成长 |
| intellect_growth | FLOAT | DEFAULT 1.0 | 智力成长 |
| defense_growth | FLOAT | DEFAULT 1.0 | 防御成长 |
| agility_growth | FLOAT | DEFAULT 1.0 | 敏捷成长 |
| luck_growth | FLOAT | DEFAULT 1.0 | 运气成长 |
| morality | INT | DEFAULT 50 | 道义值 |
| recruitable | BOOLEAN | DEFAULT TRUE | 可否招募 |
| daily_salary | INT | DEFAULT 100 | 日薪 |

**职业类型：**
- `warrior` - 武将
- `strategist` - 谋士
- `assassin` - 刺客
- `support` - 辅助

**五行属性：**
- `metal` - 金
- `wood` - 木
- `water` - 水
- `fire` - 火
- `earth` - 土

---

### Guest 表

玩家门客实例。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| template_id | BigInt | FK(GuestTemplate) | 门客模板 |
| custom_name | VARCHAR(100) | NULL | 自定义名称 |
| level | INT | DEFAULT 1 | 等级（上限100） |
| experience | INT | DEFAULT 0 | 经验值 |
| status | VARCHAR(20) | DEFAULT "idle" | 状态 |
| current_hp | INT | | 当前生命值 |
| hp_bonus | INT | DEFAULT 0 | 生命加成 |
| attribute_points | INT | DEFAULT 0 | 可分配属性点 |
| allocated_force | INT | DEFAULT 0 | 已分配武力 |
| allocated_intellect | INT | DEFAULT 0 | 已分配智力 |
| allocated_defense | INT | DEFAULT 0 | 已分配防御 |
| allocated_agility | INT | DEFAULT 0 | 已分配敏捷 |
| allocated_luck | INT | DEFAULT 0 | 已分配运气 |
| last_hp_recovery_at | DATETIME | NULL | 上次恢复时间 |
| salary_paid_today | BOOLEAN | DEFAULT FALSE | 今日工资已付 |
| created_at | DATETIME | AUTO | 招募时间 |

**状态枚举：**
- `idle` - 空闲
- `working` - 打工中
- `deployed` - 出征中
- `injured` - 重伤

**索引：**
- (`manor_id`, `status`) - INDEX
- `template_id` - INDEX

**常量：**
- `MAX_GUEST_LEVEL = 100`
- `DEFENSE_TO_HP_MULTIPLIER = 50`

**计算属性：**
- `max_hp` = (base_defense + allocated_defense + gear_defense) * 50 + hp_bonus
- `force` = base + level * growth + allocated + gear_bonus
- `troop_capacity` = 200 + (50 if level >= 70 else 0)

---

### Skill 表

技能定义。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 技能标识 |
| name | VARCHAR(100) | NOT NULL | 技能名称 |
| description | TEXT | | 描述 |
| kind | VARCHAR(20) | DEFAULT "active" | 技能类型 |
| damage_formula | VARCHAR(200) | | 伤害公式 |
| targets | VARCHAR(20) | DEFAULT "single" | 目标类型 |
| cooldown | INT | DEFAULT 0 | 冷却回合 |
| required_force | INT | DEFAULT 0 | 武力需求 |
| required_intellect | INT | DEFAULT 0 | 智力需求 |
| required_agility | INT | DEFAULT 0 | 敏捷需求 |
| icon | VARCHAR(100) | | 图标 |

**技能类型：**
- `active` - 主动技能
- `passive` - 被动技能
- `ultimate` - 终极技能

**目标类型：**
- `single` - 单体
- `row` - 横排
- `column` - 纵列
- `all` - 全体

---

### SkillBook 表

技能书（学习技能的道具）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 技能书标识 |
| name | VARCHAR(100) | NOT NULL | 名称 |
| description | TEXT | | 描述 |
| skill_id | BigInt | FK(Skill) | 教授技能 |
| rarity | VARCHAR(20) | DEFAULT "green" | 稀有度 |
| icon | VARCHAR(100) | | 图标 |

---

### GuestSkill 表

门客已学技能（关联表）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| guest_id | BigInt | FK(Guest) | 门客 |
| skill_id | BigInt | FK(Skill) | 技能 |
| slot | INT | DEFAULT 0 | 技能槽位 |
| learned_at | DATETIME | AUTO | 学习时间 |

**约束：**
- (`guest_id`, `skill_id`) - UNIQUE
- `MAX_GUEST_SKILL_SLOTS = 3`

---

### GearTemplate 表

装备模板定义。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 装备标识 |
| name | VARCHAR(100) | NOT NULL | 装备名称 |
| description | TEXT | | 描述 |
| slot | VARCHAR(20) | NOT NULL | 装备槽位 |
| rarity | VARCHAR(20) | DEFAULT "gray" | 稀有度 |
| force_bonus | INT | DEFAULT 0 | 武力加成 |
| intellect_bonus | INT | DEFAULT 0 | 智力加成 |
| defense_bonus | INT | DEFAULT 0 | 防御加成 |
| agility_bonus | INT | DEFAULT 0 | 敏捷加成 |
| luck_bonus | INT | DEFAULT 0 | 运气加成 |
| hp_bonus | INT | DEFAULT 0 | 生命加成 |
| set_key | VARCHAR(50) | NULL | 套装标识 |
| set_bonus | JSON | NULL | 套装效果 |
| set_description | TEXT | NULL | 套装描述 |
| icon | VARCHAR(100) | | 图标 |

**装备槽位：**
- `weapon` - 武器
- `armor` - 护甲
- `accessory` - 饰品
- `mount` - 坐骑

---

### GearItem 表

玩家装备实例。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| template_id | BigInt | FK(GearTemplate) | 装备模板 |
| guest_id | BigInt | FK(Guest), NULL | 装备者 |
| enhanced_level | INT | DEFAULT 0 | 强化等级 |
| acquired_at | DATETIME | AUTO | 获取时间 |

**索引：**
- (`manor_id`, `guest_id`) - INDEX
- `template_id` - INDEX

---

### RecruitmentPool 表

招募卡池定义。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 卡池标识 |
| name | VARCHAR(100) | NOT NULL | 卡池名称 |
| description | TEXT | | 描述 |
| cost_silver | INT | DEFAULT 1000 | 银两消耗 |
| cost_gold | INT | DEFAULT 0 | 金条消耗 |
| is_core | BOOLEAN | DEFAULT FALSE | 是否核心卡池 |
| rarity_weights | JSON | | 稀有度权重 |
| available_guests | JSON | | 可抽门客列表 |

---

### RecruitmentCandidate 表

招募候选门客（临时）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| pool_id | BigInt | FK(RecruitmentPool) | 来源卡池 |
| template_id | BigInt | FK(GuestTemplate) | 门客模板 |
| archetype | VARCHAR(20) | | 职业类型 |
| revealed_rarity | BOOLEAN | DEFAULT FALSE | 稀有度是否显示 |
| created_at | DATETIME | AUTO | 生成时间 |

---

### RecruitRecord 表

招募历史记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| pool_id | BigInt | FK(RecruitmentPool) | 卡池 |
| guest_id | BigInt | FK(Guest), NULL | 招募门客 |
| action | VARCHAR(20) | NOT NULL | 操作类型 |
| created_at | DATETIME | AUTO | 操作时间 |

**操作类型：**
- `accept` - 招募
- `discard` - 放弃
- `retain` - 收为家丁

---

### SalaryPayment 表

工资支付记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| guest_id | BigInt | FK(Guest) | 门客 |
| amount | INT | NOT NULL | 支付金额 |
| paid_at | DATETIME | AUTO | 支付时间 |

---

### GuestDefection 表

门客叛逃记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 所属庄园 |
| guest_name | VARCHAR(100) | NOT NULL | 门客名称 |
| template_key | VARCHAR(50) | | 模板标识 |
| reason | VARCHAR(50) | NOT NULL | 叛逃原因 |
| defected_at | DATETIME | AUTO | 叛逃时间 |

---

## 战斗模块 (battle)

### TroopTemplate 表

兵种模板定义。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| key | VARCHAR(50) | UNIQUE | 兵种标识 |
| label | VARCHAR(100) | NOT NULL | 兵种名称 |
| description | TEXT | | 描述 |
| attack | INT | DEFAULT 10 | 攻击力 |
| defense | INT | DEFAULT 5 | 防御力 |
| hp | INT | DEFAULT 100 | 生命值 |
| speed | INT | DEFAULT 10 | 速度 |
| element | VARCHAR(20) | | 五行属性 |
| icon | VARCHAR(100) | | 图标 |

**预设兵种：**
- `militia` - 民兵
- `infantry` - 步兵
- `cavalry` - 骑兵
- `archer` - 弓箭手
- `pikeman` - 枪兵

---

### BattleReport 表

战斗报告。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| battle_type | VARCHAR(20) | DEFAULT "mission" | 战斗类型 |
| attacker_id | BigInt | FK(Manor), NULL | 攻方庄园 |
| defender_id | BigInt | FK(Manor), NULL | 守方庄园 |
| attacker_team | JSON | NOT NULL | 攻方配置 |
| defender_team | JSON | NOT NULL | 守方配置 |
| attacker_troops | JSON | | 攻方兵种 |
| defender_troops | JSON | | 守方兵种 |
| rounds | JSON | NOT NULL | 回合详情 |
| winner | VARCHAR(20) | NOT NULL | 胜利方 |
| attacker_losses | JSON | | 攻方损失 |
| defender_losses | JSON | | 守方损失 |
| drops | JSON | | 掉落物品 |
| created_at | DATETIME | AUTO | 战斗时间 |

**战斗类型：**
- `mission` - 任务战斗
- `pvp` - 玩家对战
- `guild_war` - 帮会战

**胜利方：**
- `attacker` - 攻方胜
- `defender` - 守方胜
- `draw` - 平局

**JSON 结构示例：**
```json
// attacker_team
{
  "guests": [
    {
      "id": 1,
      "name": "张三",
      "level": 50,
      "force": 120,
      "skills": ["skill_key_1"]
    }
  ]
}

// rounds
[
  {
    "round": 1,
    "actions": [
      {
        "actor": "guest_1",
        "skill": "普通攻击",
        "target": "enemy_1",
        "damage": 150,
        "is_critical": false
      }
    ]
  }
]
```

---

## 交易模块 (trade)

### ShopStock 表

商店库存。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| item_key | VARCHAR(50) | UNIQUE | 物品标识 |
| category | VARCHAR(50) | | 分类 |
| buy_price | INT | NOT NULL | 买入价格 |
| sell_price | INT | NOT NULL | 卖出价格 |
| daily_limit | INT | DEFAULT 0 | 每日限购（0=不限） |
| stock | INT | DEFAULT -1 | 库存（-1=无限） |
| is_active | BOOLEAN | DEFAULT TRUE | 是否上架 |

---

### ShopPurchaseLog 表

商店购买记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 买家 |
| item_key | VARCHAR(50) | NOT NULL | 物品标识 |
| quantity | INT | NOT NULL | 数量 |
| total_price | INT | NOT NULL | 总价 |
| purchased_at | DATETIME | AUTO | 购买时间 |

---

### ShopSellLog 表

商店出售记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 卖家 |
| item_key | VARCHAR(50) | NOT NULL | 物品标识 |
| quantity | INT | NOT NULL | 数量 |
| total_price | INT | NOT NULL | 总价 |
| sold_at | DATETIME | AUTO | 出售时间 |

---

### GoldBarExchangeLog 表

金条兑换记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| manor_id | BigInt | FK(Manor) | 庄园 |
| quantity | INT | NOT NULL | 金条数量 |
| silver_received | INT | NOT NULL | 获得银两 |
| fee | INT | DEFAULT 0 | 手续费 |
| exchanged_at | DATETIME | AUTO | 兑换时间 |

---

### MarketListing 表

交易行上架商品。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| seller_id | BigInt | FK(Manor) | 卖家 |
| item_key | VARCHAR(50) | NOT NULL | 物品标识 |
| quantity | INT | NOT NULL | 数量 |
| unit_price | INT | NOT NULL | 单价 |
| total_price | INT | NOT NULL | 总价 |
| duration | VARCHAR(20) | DEFAULT "medium" | 上架时长 |
| status | VARCHAR(20) | DEFAULT "active" | 状态 |
| expires_at | DATETIME | NOT NULL | 过期时间 |
| created_at | DATETIME | AUTO | 上架时间 |

**上架时长：**
- `short` - 2小时
- `medium` - 8小时
- `long` - 24小时

**状态：**
- `active` - 在售
- `sold` - 已售
- `cancelled` - 已取消
- `expired` - 已过期

**索引：**
- (`status`, `expires_at`) - INDEX
- `seller_id` - INDEX
- `item_key` - INDEX

---

### MarketTransaction 表

交易行成交记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| listing_id | BigInt | FK(MarketListing) | 商品 |
| buyer_id | BigInt | FK(Manor) | 买家 |
| seller_id | BigInt | FK(Manor) | 卖家 |
| item_key | VARCHAR(50) | NOT NULL | 物品标识 |
| quantity | INT | NOT NULL | 数量 |
| unit_price | INT | NOT NULL | 单价 |
| total_price | INT | NOT NULL | 总价 |
| fee | INT | DEFAULT 0 | 手续费 |
| transacted_at | DATETIME | AUTO | 成交时间 |

---

## 帮会模块 (guilds)

### Guild 表

帮会信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| name | VARCHAR(50) | UNIQUE | 帮会名称 |
| description | TEXT | | 帮会描述 |
| emblem | VARCHAR(50) | DEFAULT "default" | 帮徽 |
| level | INT | DEFAULT 1 | 帮会等级 |
| experience | INT | DEFAULT 0 | 帮会经验 |
| leader_id | BigInt | FK(User) | 帮主 |
| fund_wood | INT | DEFAULT 0 | 帮会木材 |
| fund_stone | INT | DEFAULT 0 | 帮会石料 |
| fund_iron | INT | DEFAULT 0 | 帮会铁矿 |
| fund_grain | INT | DEFAULT 0 | 帮会粮食 |
| fund_silver | INT | DEFAULT 0 | 帮会银两 |
| auto_accept | BOOLEAN | DEFAULT FALSE | 自动接受申请 |
| created_at | DATETIME | AUTO | 创建时间 |

**索引：**
- `name` - UNIQUE INDEX
- `leader_id` - INDEX
- `level` - INDEX

**计算属性：**
- `member_capacity` - 成员上限（基础20 + 等级*5）

**Manager 方法：**
- `with_member_count()` - 预加载成员数量

---

### GuildMember 表

帮会成员。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| guild_id | BigInt | FK(Guild) | 帮会 |
| user_id | BigInt | FK(User) | 用户 |
| position | VARCHAR(20) | DEFAULT "member" | 职位 |
| contribution_total | INT | DEFAULT 0 | 总贡献 |
| contribution_weekly | INT | DEFAULT 0 | 周贡献 |
| joined_at | DATETIME | AUTO | 加入时间 |

**职位：**
- `leader` - 帮主
- `admin` - 管理员
- `member` - 成员

**索引：**
- (`guild_id`, `user_id`) - UNIQUE INDEX
- `user_id` - INDEX
- `contribution_total` - INDEX

---

### GuildTechnology 表

帮会科技。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| guild_id | BigInt | FK(Guild) | 帮会 |
| tech_key | VARCHAR(50) | NOT NULL | 科技标识 |
| level | INT | DEFAULT 0 | 当前等级 |
| is_upgrading | BOOLEAN | DEFAULT FALSE | 升级中 |
| upgrade_complete_at | DATETIME | NULL | 完成时间 |

**索引：**
- (`guild_id`, `tech_key`) - UNIQUE INDEX

---

### GuildWarehouse 表

帮会仓库物品。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| guild_id | BigInt | FK(Guild) | 帮会 |
| item_key | VARCHAR(50) | NOT NULL | 物品标识 |
| quantity | INT | DEFAULT 0 | 数量 |
| exchange_cost | INT | DEFAULT 0 | 兑换贡献 |

**索引：**
- (`guild_id`, `item_key`) - UNIQUE INDEX

---

### GuildExchangeLog 表

帮会仓库兑换记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| guild_id | BigInt | FK(Guild) | 帮会 |
| member_id | BigInt | FK(GuildMember) | 成员 |
| item_key | VARCHAR(50) | NOT NULL | 物品标识 |
| quantity | INT | NOT NULL | 数量 |
| cost | INT | NOT NULL | 消耗贡献 |
| exchanged_at | DATETIME | AUTO | 兑换时间 |

---

### GuildApplication 表

帮会申请。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| guild_id | BigInt | FK(Guild) | 帮会 |
| user_id | BigInt | FK(User) | 申请人 |
| message | TEXT | | 申请留言 |
| status | VARCHAR(20) | DEFAULT "pending" | 状态 |
| reviewed_by_id | BigInt | FK(User), NULL | 审核人 |
| reviewed_at | DATETIME | NULL | 审核时间 |
| reject_note | TEXT | NULL | 拒绝理由 |
| created_at | DATETIME | AUTO | 申请时间 |

**状态：**
- `pending` - 待审核
- `approved` - 已通过
- `rejected` - 已拒绝

**索引：**
- (`guild_id`, `user_id`, `status`) - INDEX

---

### GuildAnnouncement 表

帮会公告。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| guild_id | BigInt | FK(Guild) | 帮会 |
| author_id | BigInt | FK(User) | 发布者 |
| content | TEXT | NOT NULL | 公告内容 |
| is_pinned | BOOLEAN | DEFAULT FALSE | 是否置顶 |
| created_at | DATETIME | AUTO | 发布时间 |

---

### GuildDonationLog 表

帮会捐赠记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| guild_id | BigInt | FK(Guild) | 帮会 |
| member_id | BigInt | FK(GuildMember) | 成员 |
| resource_type | VARCHAR(20) | NOT NULL | 资源类型 |
| amount | INT | NOT NULL | 数量 |
| contribution_earned | INT | NOT NULL | 获得贡献 |
| donated_at | DATETIME | AUTO | 捐赠时间 |

---

### GuildResourceLog 表

帮会资源变动日志。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigAutoField | PK | 主键 |
| guild_id | BigInt | FK(Guild) | 帮会 |
| resource_type | VARCHAR(20) | NOT NULL | 资源类型 |
| amount | INT | NOT NULL | 变动数量 |
| reason | VARCHAR(50) | NOT NULL | 变动原因 |
| operator_id | BigInt | FK(User), NULL | 操作者 |
| created_at | DATETIME | AUTO | 发生时间 |

---

## 索引优化建议

### 高频查询索引

```sql
-- 任务扫描优化
CREATE INDEX idx_mission_run_battle_at ON gameplay_missionrun(battle_at)
    WHERE status = 'active';

-- 建筑升级扫描优化
CREATE INDEX idx_building_upgrade ON gameplay_building(upgrade_complete_at)
    WHERE is_upgrading = TRUE;

-- 门客状态查询优化
CREATE INDEX idx_guest_status ON guests_guest(manor_id, status);

-- 交易行过期清理优化
CREATE INDEX idx_market_expires ON trade_marketlisting(expires_at)
    WHERE status = 'active';

-- 消息未读查询优化
CREATE INDEX idx_message_unread ON gameplay_message(manor_id, is_read, created_at);
```

### 分页查询优化

对于大数据量分页，建议使用游标分页而非 OFFSET：

```python
# 不推荐
Message.objects.filter(manor=manor).order_by('-id')[offset:offset+limit]

# 推荐
Message.objects.filter(manor=manor, id__lt=cursor_id).order_by('-id')[:limit]
```

---

## 数据迁移注意事项

### 迁移命令

```bash
# 生成迁移文件
python manage.py makemigrations

# 查看迁移状态
python manage.py showmigrations

# 执行迁移
python manage.py migrate

# 回滚迁移（谨慎）
python manage.py migrate <app> <migration_number>
```

### 数据迁移最佳实践

1. **大表迁移**：使用 `RunSQL` 分批执行
2. **添加索引**：使用 `CONCURRENTLY` 避免锁表（PostgreSQL）
3. **字段类型变更**：先添加新字段，迁移数据，再删除旧字段
4. **默认值**：避免在大表上添加带默认值的字段

---

## 数据备份与恢复

### MySQL 备份

```bash
# 全量备份
mysqldump -u root -p webgame_db > backup_$(date +%Y%m%d).sql

# 恢复
mysql -u root -p webgame_db < backup_20240101.sql
```

### SQLite 备份

```bash
# 直接复制数据库文件
cp db.sqlite3 db.sqlite3.backup

# 使用 Django 导出
python manage.py dumpdata > backup.json
python manage.py loaddata backup.json
```

---

## 附录：数据字典

### 资源类型 (ResourceType)

| 标识 | 名称 | 说明 |
|------|------|------|
| wood | 木材 | 建筑/科技消耗 |
| stone | 石料 | 建筑/科技消耗 |
| iron | 铁矿 | 装备/科技消耗 |
| grain | 粮食 | 出征/养兵消耗 |
| silver | 银两 | 通用货币 |

### 稀有度 (Rarity)

| 等级 | 标识 | 颜色 | 说明 |
|------|------|------|------|
| 1 | black | 黑 | 最低稀有度 |
| 2 | gray | 灰 | 普通 |
| 3 | green | 绿 | 优秀 |
| 4 | blue | 蓝 | 精良 |
| 5 | red | 红 | 史诗 |
| 6 | purple | 紫 | 传说 |
| 7 | orange | 橙 | 神话 |

### 五行属性 (Element)

| 标识 | 名称 | 克制 | 被克 |
|------|------|------|------|
| metal | 金 | 木 | 火 |
| wood | 木 | 土 | 金 |
| water | 水 | 火 | 土 |
| fire | 火 | 金 | 水 |
| earth | 土 | 水 | 木 |

**克制效果**：造成/受到 +20% 伤害
