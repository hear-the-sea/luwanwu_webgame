# 春秋乱世庄园主 - 数据库边界

> 最近校正：2026-03-23

这份文档不再维护按字段展开的长表结构手册。当前更有价值的内容是：数据库在各环境中的角色、模型按 app 的归属、迁移与索引协作边界，以及哪些语义只能在真实 MySQL 上验证。

## 数据库角色

| 场景 | 后端 | 说明 |
|------|------|------|
| 本地默认开发 | SQLite | 零配置、反馈快 |
| hermetic 测试 | SQLite 临时文件 | 默认 `pytest` 路径使用 |
| 真实服务 / 集成测试 | MySQL 8.x | 验证锁、事务、唯一约束与并发语义 |

重点约束：

- 默认 `make test` 不能代表真实 MySQL 行锁语义已经验证。
- `select_for_update()`、唯一约束竞争、事务隔离等行为必须通过 `DJANGO_TEST_USE_ENV_SERVICES=1` 的外部服务环境复核。

## 模型归属

### `accounts`

- `User`：自定义认证用户，继承 `AbstractUser`
- `UserActiveSession`：单会话权威记录

### `gameplay`

当前 `gameplay/models/` 已拆分为多模块，主要覆盖：

- `manor.py`：`Manor`、`BuildingType`、`Building`
- `items.py`：`ResourceEvent`、`ItemTemplate`、`InventoryItem`、`Message`、`GlobalMailCampaign`、`GlobalMailDelivery`
- `missions.py`：`MissionTemplate`、`MissionRun`、`MissionExtraAttempt`
- `progression.py`：`PlayerTechnology`、`WorkTemplate`、`WorkAssignment`、`PlayerTroop`、`TroopBankStorage`、各类生产/募兵模型
- `arena.py`：竞技场轮次、报名、对战、兑换记录
- `pvp.py`：`ScoutRecord`、`ScoutCooldown`、`RaidRun`、`OathBond`、`JailPrisoner`

### `guests`

覆盖门客模板、招募池、技能、装备、实例门客、培养与工资相关模型：

- `GuestTemplate`
- `RecruitmentPool` / `RecruitmentPoolEntry`
- `Skill` / `SkillBook`
- `Guest`
- `GearTemplate` / `GearItem`
- `RecruitmentRecord` / `GuestRecruitment` / `RecruitmentCandidate`
- `TrainingLog`
- `GuestSkill`
- `SalaryPayment`
- `GuestDefection`

### `battle`

- `TroopTemplate`
- `BattleReport`

### `trade`

覆盖商铺、银庄、交易行、拍卖四类数据：

- 商铺：`ShopStock`、`ShopPurchaseLog`、`ShopSellLog`
- 银庄：`GoldBarExchangeLog`
- 交易行：`MarketListing`、`MarketTransaction`
- 拍卖：`AuctionRound`、`AuctionSlot`、`AuctionBid`、`FrozenGoldBar`

### `guilds`

覆盖帮会主实体、成员、科技、仓库、日志与英雄池：

- `Guild`
- `GuildMember`
- `GuildTechnology`、`GuildWarehouse`
- `GuildApplication`、`GuildAnnouncement`
- `GuildExchangeLog`、`GuildDonationLog`、`GuildResourceLog`
- `GuildHeroPoolEntry`、`GuildBattleLineupEntry`

## 当前建模事实

- `AUTH_USER_MODEL` 为 `accounts.User`
- `gameplay.models` 与 `guilds.models` 都已经拆包，但保留 `__init__.py` 重导出兼容入口
- 玩法模板大量存于数据库，但数据源并不手工维护在表结构文档中，而是来自 `data/*.yaml` 与对应导入命令

## 迁移协作约束

1. 新模型或字段变更必须通过 Django migration 进入仓库，不接受“只改线上库”。
2. 任何依赖 MySQL 特性的设计，都必须补真实服务测试或至少给出不可用范围说明。
3. 迁移如果涉及兼容窗口，先更新 [`compatibility_inventory_2026-03.md`](compatibility_inventory_2026-03.md)。
4. 变更会影响写路径状态机时，同步检查 [`write_model_boundaries.md`](write_model_boundaries.md)。

## 索引与约束约定

- 与高频读写路径直接相关的复合索引，必须在模型 `Meta.indexes` 或 migration 中显式声明。
- 状态机类模型优先使用“状态 + 时间 / 主体”复合索引。
- 唯一性如果只对活跃状态生效，优先使用条件唯一约束。
- 只为“可能有用”而加索引不可接受，必须能对应到查询路径、并发约束或后台扫描任务。

## 哪些问题要去真实 MySQL 验证

- `select_for_update()` 互斥
- 条件唯一约束竞争
- 长事务与回滚后的状态恢复
- 任务扫描器与异步补偿在多进程下的观察结果
- 与拍卖、任务、招募、踢馆相关的并发状态机

## 查询源

想看当前真实字段定义时，直接查以下文件，不再依赖手工抄录表结构：

- `accounts/models.py`
- `gameplay/models/*.py`
- `guests/models.py`
- `battle/models.py`
- `trade/models.py`
- `guilds/models/*.py`
