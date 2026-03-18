# 项目技术审计与优化清单（2026-03）

本文档只保留当前仍成立的问题、缺口和待跟踪项。已经完成并有代码/测试证据支撑的优化、重构和历史问题，均已从正文删除，不再混入当前审计结论。

最近更新：2026-03-18（第七十批校正文档：继续优先处理抽象问题，完成 `battle/services.py` 一轮内部职责收口，将锁定参与者装配、攻击方门客解析、`BattleOptions` 构建与带锁执行拆成独立 helper；同步补齐 battle 定向回归）

相关文档：

- [优化计划](optimization_plan.md)
- [架构设计](architecture.md)
- [开发指南](development.md)
- [兼容入口清单](compatibility_inventory_2026-03.md)

## 1. 当前有效证据

当前仍有效、且可作为结论依据的验证结果只有这些：

- 历史默认门禁记录仍显示：默认 `flake8` 通过，默认非 integration `pytest` 通过，`manage.py check` / `check --deploy` 可执行完成
- 本轮抽样回归通过：`python -m pytest -q tests/test_base_settings.py tests/test_health.py tests/test_trade_views.py`
- 本轮代码审查重点覆盖：
  - `trade/services/market_service.py`
  - `trade/services/bank_service.py`
  - `trade/services/market_commands.py`
  - `trade/selectors.py`
  - `battle/services.py`
  - `gameplay/services/raid/combat/runs.py`
  - `gameplay/services/missions_impl/execution.py`
  - `guests/views/recruit.py`
  - `guilds/views/core.py`
  - `guilds/services/member.py`
  - `config/settings/__init__.py`
  - `config/settings/testing.py`
  - `tests/conftest.py`
  - `pytest.ini`
  - `.coveragerc`
- 本轮启动了全量 `python -m pytest -q` 抽查，运行进度到约 50% 时未见失败信号，但该次执行未完整收尾，因此不能作为“全量测试再次确认通过”的正式证据
- 本轮过度抽象收敛回归通过：
  - `python -m pytest -q tests/test_market_service.py tests/test_trade.py -k "market or listing or purchase or cancel or expire"`
  - `python -m pytest -q tests/test_trade_views.py tests/test_trade_tasks.py`
  - `python -m pytest -q tests/test_trade_bank_service.py tests/test_trade_views.py -k "bank or exchange_gold_bar"`
  - `python -m pytest -q tests/test_raid_combat_runs.py tests/test_raid_concurrency_integration.py tests/test_trade_bank_service.py`
  - `python -m pytest -q tests/test_mission_launch_resilience.py tests/test_mission_refresh_async.py tests/test_gameplay.py -k "mission"`
- 本轮 trade 读侧优化回归通过：
  - `python -m pytest -q tests/test_trade_selectors.py tests/test_trade_views.py tests/test_trade_shop_service.py`
- 本轮 guilds 写入口收口回归通过：
  - `python -m pytest -q tests/test_guilds.py`
- 本轮 battle 锁恢复回归通过：
  - `python -m pytest -q tests/test_battle.py tests/test_battle_lock_order.py tests/test_raid_combat_runs.py tests/test_raid_concurrency_integration.py`
- 本轮 guests 技能写入口收口回归通过：
  - `python -m pytest -q tests/test_guest_skill_service.py tests/test_guest_view_error_boundaries.py -k "learn_skill_view or forget_skill_view or skill_service"`
  - `python -m pytest -q tests/test_guest_item_view_validation.py -k "learn_skill_view or forget_skill_view"`
- 本轮 guests / guilds 抽象收口回归通过：
  - `python -m pytest -q tests/test_guest_roster_service.py tests/test_inventory_views.py -k "dismiss_guest or dismiss"`
  - `python -m pytest -q tests/test_guilds.py tests/test_guest_roster_service.py tests/test_inventory_views.py -k "guild or dismiss"`
  - `python -m pytest -q tests/test_guest_skill_service.py tests/test_guests_services.py tests/test_recruitment_hall_cache.py tests/test_guest_recruitment_service.py -k "skill_service or recover_guest_hp or available_guests or list_pools or cache or recruitment"`
- 本轮 trade 平台层删除回归通过：
  - `python -m pytest -q tests/test_trade_selectors.py tests/test_trade_views.py tests/test_trade_shop_service.py tests/test_trade_bank_service.py -k "trade or shop or bank or exchange_gold_bar"`
  - `python -m pytest -q tests/test_market_service.py tests/test_trade.py -k "market or listing or purchase or cancel or expire"`
  - `python -m pytest -q tests/test_trade_auction_rounds.py tests/test_auction_gold_bars.py tests/test_market_notification_helpers.py -k "auction or gold_bar or notify or message"`
- 本轮 recruit 视图结构收口回归通过：
  - `python -m pytest -q tests/test_guest_item_view_validation.py -k "recruit_view or candidate_accept_view or use_magnifying_glass_view"`
  - `python -m pytest -q tests/test_guest_view_error_boundaries.py -k "recruit_view or accept_candidate_view or use_magnifying_glass_view"`
- 本轮 guild member 服务收口回归通过：
  - `python -m pytest -q tests/test_guilds.py tests/test_guild_hero_pool.py`
- 本轮 battle 服务结构收口回归通过：
  - `python -m pytest -q tests/test_battle.py tests/test_battle_lock_order.py tests/test_raid_combat_runs.py tests/test_raid_concurrency_integration.py`
  - `python -m pytest -q tests/test_mission_launch_resilience.py tests/test_gameplay.py -k "mission or DEPLOYED or battle"`

当前无法宣称已闭环的部分：

- `DJANGO_TEST_USE_ENV_SERVICES=1` 下的真实 MySQL / Redis / Channels / Celery 关键语义，仍没有本轮重新执行确认
- 默认测试入口仍显式声明不验证真实锁语义、Redis 语义和真实 Channels 语义
- `mypy` 仍不是全项目高信噪比硬门禁，views / admin / management commands 等大面积区域仍保留豁免

## 2. 当前状态判断

项目的真实状态，不适合再按“接近完成收尾”来描述。

更准确的判断是：

1. 功能体量和业务复杂度已经明显超过普通练手项目，说明项目有真实的系统设计与实现能力。
2. 但工程纪律没有同步跟上规模增长，代码组织复杂度已经开始高于业务本身复杂度。
3. 当前最主要的问题不再是缺一个功能点，或者少几个测试，而是模块边界、写入口、异常边界、测试可信度和复杂度控制正在同时失守。

这意味着项目并不处于“只差少量扫尾即可进入高分稳定态”的阶段，而是进入了一个更危险的中段：

- 能继续开发新功能；
- 也能继续补测试和补修复；
- 但如果不先收权、收边界、收抽象，后续每次需求迭代都会继续把维护成本抬高。

## 3. 剩余高优先级问题

### P1-1 伪平台层与分层纪律不稳定，服务层没有成为唯一写入口

重点区域：

- `trade/services/trade_platform.py`
- `guilds/services/guild_platform.py`
- `guests/services/guest_platform.py`
- `guilds/views/core.py`
- `guilds/services/*`

当前缺口：

- 一批 `platform` 文件只是把别的 service 再薄包一层，没有形成真正稳定的边界或外部端口
- 同一 app 内，部分写路径走 service，部分写路径仍直接在 view 中开事务、锁行、改模型
- 这说明“服务层是唯一写入口”没有真正落地，分层更像约定而不是约束

具体证据：

- `trade/services/trade_platform.py`、`guilds/services/guild_platform.py`、`guests/services/guest_platform.py` 已在本轮全部删除
- `guilds/views/core.py:guild_info`、`guests/views/skills.py`、`guests/views/roster.py` 已改为委托 service 写入口，`guests/views/recruit.py` 也已统一锁控制与异常分层
- `guilds/services/member.py` 已在本轮拆成事务状态变更 helper + follow-up helper
- `battle/services.py` 已在本轮将锁定参与者装配、攻击方门客解析、`BattleOptions` 构建与带锁执行拆为独立 helper，但文件整体仍偏厚

完成标准：

- 平台层仅保留真正需要隔离外部依赖或跨 app 协作的窄端口
- view 不再直接承担写模型、事务和并发控制逻辑
- service 成为唯一且清晰的写侧入口

### P1-2 战斗锁与门客状态锁定策略仍有真实一致性风险

重点区域：

- `battle/services.py`
- `gameplay/services/raid/combat/*`
- `guests/models.py`

当前缺口：

- 战斗锁并未在完整关键阶段内持有数据库锁，而是先把 `Guest.status` 标记为 `DEPLOYED`，退出事务后再执行战斗，最后再恢复
- 这本质上是“状态字段充当分布式锁/业务锁”的折中实现，而不是强一致并发控制
- 如果进程崩溃、任务被 kill、补偿路径失效，门客状态可能卡死，需要额外修复逻辑兜底

具体证据：

- `battle/services.py:lock_guests_for_battle` 先锁行并批量更新状态，再在事务外 `yield` 执行战斗，最后另起事务恢复状态
- 本轮已补 `recover_orphaned_deployed_guests(...)`，可在重复出战前自动恢复未被 mission / raid / arena 引用的孤儿 `DEPLOYED` 门客，并留下 warning 日志
- `battle/services.py` 同时还承担门客锁定、战斗参数装配、AI 组装和执行入口，进一步提高了该链路的变更风险

完成标准：

- 明确“状态锁”和“数据库锁”分别承担什么职责，避免混淆
- 为门客卡死在 `DEPLOYED` 的路径建立明确恢复机制、监控和回归测试
- 拆分战斗并发协调与战斗业务执行入口，降低单文件风险

### P1-3 默认测试入口的可信度仍明显不足

重点区域：

- `Makefile`
- `config/settings/testing.py`
- `tests/conftest.py`
- `tests/test_raid_concurrency_integration.py`
- `tests/test_work_service_concurrency.py`

当前缺口：

- 默认 `make test` 只验证 SQLite / LocMem / InMemory channel layer / memory Celery 这一套 hermetic 环境
- `Makefile` 已明确说明默认门禁不验证 `select_for_update`、Redis、真实 Channels 语义
- 关键并发 integration 测试依赖 `DJANGO_TEST_USE_ENV_SERVICES=1`，但这条门禁仍不是团队默认工作流

具体证据：

- `Makefile` 明写 hermetic 环境“不验证”真实锁与外部服务语义
- `config/settings/testing.py` 默认替换为 SQLite、LocMem、InMemoryChannelLayer、memory Celery
- `tests/conftest.py` 中真实服务探测失败时广泛使用 `pytest.skip`

完成标准：

- 明确区分“默认快速门禁”和“真实语义门禁”，但后者必须成为持续执行的固定流程
- 关键并发链路必须有真实外部服务下的稳定执行记录
- “默认测试全绿”不再被误读为“生产语义已验证”

## 4. P2：结构性复杂度热点

### P2-1 God module 与热点文件继续累积职责

重点区域：

- `guests/views/recruit.py`
- `battle/services.py`
- `trade/selectors.py`
- `gameplay/views/production.py`
- `gameplay/views/jail.py`
- `guests/models.py`
- `guests/services/recruitment*.py`

当前缺口：

- `guests/views/recruit.py` 同时承担参数解析、锁控制、缓存失效、AJAX 片段渲染、消息拼装、异常分类和双通道响应
- `battle/services.py` 同时承担门客锁定、状态恢复、战斗参数准备、AI 组装和执行入口
- `trade/selectors.py` 已经不只是 selector，而是厚重的页面编排和部分业务触发入口

问题不在于“文件行数大”，而在于这些文件同时承载多种变化原因，一旦继续堆需求，就会迅速反弹回“大而全”巨石。

完成标准：

- orchestrator 只保留编排职责
- presenter / selector 只保留读侧装配，不再混入写侧动作和重副作用
- request parsing、规则判断、副作用派发、AJAX payload 组装等职责拆到稳定边界

### P2-2 Selector / View 边界模糊，页面读取路径仍有残余装配复杂度

重点区域：

- `trade/selectors.py`
- `guests/views/recruit.py`
- `gameplay/views/*`

当前缺口：

- `trade/selectors.py` 的资源同步副作用已在本轮移回 `TradeView`，shop 卖出列表也改成先分页库存查询集，再转换当前页展示行
- 但 `trade/selectors.py` 仍然承担较厚的页面编排职责，auction / bank / market / shop 多个 tab 仍集中在同一文件
- 其他页面读取路径依然存在“selector / presenter / view 边界不够稳定”的问题
- View 和 Selector 之间没有建立稳定的职责边界，导致读取路径混入锁、缓存、消息和业务刷新动作

具体证据：

- `trade/selectors.py` 已不再在 `get_trade_context` 中执行资源同步，shop 卖出路径已通过 `InventoryItem` 查询集分页后再构造展示数据
- `trade/selectors.py` 仍是多 tab 聚合入口，bank / auction / market / shop 的上下文装配继续集中
- `guests/views/recruit.py` 等热点入口仍同时承担请求编排、锁、缓存和响应拼装

完成标准：

- selector 只读，不再执行资源刷新、状态推进或其他业务动作
- 数据分页尽量在数据库层完成
- 页面读取性能与职责边界可以独立分析和优化

### P2-3 广谱吞异常与 fail-open 设计使用过多

重点区域：

- `core/utils/task_monitoring.py`
- `trade/services/cache_resilience.py`
- `trade/services/market_expiration.py`
- `trade/services/bank_supply_runtime.py`
- `guilds/services/member.py`
- `websocket/consumers/*`
- `gameplay/tasks/*`

当前缺口：

- 项目中仍存在大量裸 `except Exception` 和 best-effort 降级路径
- 这些写法短期提高了“别炸”的概率，但也放大了静默失败、状态漂移和问题滞后的风险
- 目前还缺少统一规则来约束哪些链路允许 fail-open，哪些链路必须 fail-closed

完成标准：

- 经济结算、库存扣减、战斗结算、奖励发放等关键链路不再使用裸 `except Exception` 作为常规控制流
- 基础设施异常、业务异常、用户输入异常分别归入清晰层级
- 降级策略在代码、文档和测试中统一表达

## 5. P2：测试体系与门禁组织问题

### P2-4 pytest 收集边界和测试组织仍不够专业

重点区域：

- `pytest.ini`
- `tests/`
- `guilds/tests.py`
- `trade/tests.py`
- `guests/management/commands/test_recruitment.py`

当前缺口：

- `pytest.ini` 没有设置 `testpaths`，收集边界过宽
- 仓库主要测试集中在根 `tests/`，但 app 内仍保留 Django 脚手架式空壳 `tests.py`
- 存在命名上容易撞入 pytest 收集规则、但实际不是测试的文件，例如 `guests/management/commands/test_recruitment.py`

完成标准：

- 明确仓库的测试组织策略：集中式测试或就近测试，二选一并清理残留
- 通过 `testpaths` 和更严格的命名约束收紧 pytest 收集边界
- 移除空壳 `tests.py` 和歧义命名文件带来的噪音

### P2-5 覆盖率与测试抽象层仍不够可信

重点区域：

- `.coveragerc`
- `tests/conftest.py`
- `tests/test_gameplay_services.py`
- 其他超长测试文件

当前缺口：

- 默认测试命令不跑 coverage，覆盖率压力不在默认工作流中
- `.coveragerc` 仍直接忽略 `management/commands`、`templatetags` 等入口
- 公共 fixture 和测试工厂抽象还不够强，许多测试仍手工建模、手工造状态
- 仓库内已有大量 300 行以上的大测试文件，测试代码本身也在累积维护成本

完成标准：

- 关键门禁至少具备覆盖率可见性，避免长期盲区
- 关键入口不因覆盖率配置被长期排除在外
- 通过更强的 fixture / factory / builder 收缩重复测试搭建代码

## 6. 当前待跟踪项

| 编号 | 主题 | 优先级 | 当前未完成点 | 当前证据 |
| --- | --- | --- | --- | --- |
| P1-1 | 分层纪律与唯一写入口 | P1 | `trade/guilds/guests` 伪 platform 已删除，主写入口基本收口，剩余热点更多转为高密度 orchestrator | `battle/services.py`、`trade/selectors.py` |
| P1-2 | 战斗锁生命周期 | P1 | 孤儿 `DEPLOYED` 已可恢复，但 `Guest.status` 仍承担业务锁职责 | `battle/services.py:lock_guests_for_battle`、`recover_orphaned_deployed_guests` |
| P1-3 | 默认测试可信度 | P1 | 默认门禁仍不验证真实外部服务关键语义 | `Makefile`、`config/settings/testing.py`、`tests/conftest.py` |
| P2-1 | God module 热点 | P2 | `battle/services.py`、`trade/selectors.py` 仍高密度耦合 | 本轮结构审查 |
| P2-2 | View / Selector 边界 | P2 | 页面读取路径仍混入资源同步、缓存、低效分页等职责 | `trade/selectors.py` |
| P2-3 | 异常治理与降级边界 | P2 | 广谱 `except Exception` 和 fail-open 路径仍多 | `core/utils/task_monitoring.py`、`trade/services/cache_resilience.py` 等 |
| P2-4 | pytest 收集与测试组织 | P2 | 测试边界宽、空壳 `tests.py` 和歧义命名文件仍在 | `pytest.ini`、`guilds/tests.py`、`trade/tests.py` |
| P2-5 | 覆盖率与测试抽象 | P2 | coverage 不在默认门禁，测试搭建重复度高 | `.coveragerc`、`tests/conftest.py`、超长测试文件 |

## 7. To Do List

1. `[已完成]` 收口 `guilds` 写入口。
当前结果：`guilds/views/core.py:guild_info` 不再直接开事务和改模型，已统一委托 `guilds/services/guild.py:update_guild_info`，并补齐 leader/越权回归。
2. `[已完成]` 补 battle 孤儿 `DEPLOYED` 自愈路径。
当前结果：`battle/services.py` 新增 `recover_orphaned_deployed_guests(...)`，对未被 active mission / raid / arena 占用的孤儿出征状态执行恢复，并由 `lock_guests_for_battle(...)` 自动接入。
3. `[进行中]` 继续收口剩余非唯一写入口。
当前结果：`guests/views/skills.py` 的学习/遗忘技能事务已迁入 `guests/services/skills.py`，`guests/views/roster.py` 的辞退门客事务已迁入 `guests/services/roster.py`，`trade/services/trade_platform.py`、`guilds/services/guild_platform.py` 与 `guests/services/guest_platform.py` 已全部删除，`guests/views/recruit.py` 已统一锁控制与异常分层，`guilds/services/member.py` 也已拆成事务状态变更 helper + follow-up helper。
下一批重点：`trade/selectors.py`，目标是继续压缩多 tab 页面编排职责，进一步稳定 selector / view 边界。
4. `[待执行]` 继续压 battle God module。
当前结果：`battle/services.py` 已拆出锁定参与者装配、攻击方门客解析、`BattleOptions` 构建与带锁执行 helper。
下一批重点：继续压缩 battle 文件体积，必要时再把锁生命周期与战斗装配落到更清晰的具体模块。
5. `[待执行]` 处理默认测试可信度。
下一批重点：把真实外部服务 integration 门禁写进固定流程，避免默认 `make test` 继续被误解为生产语义验证。

## 8. 建议执行顺序

1. 先处理 `P1-1`：继续把伪平台层和非唯一写入口收口，不要让刚收直的链路重新长回去。
2. 紧接着处理 `P1-2`：重做或补强门客战斗锁生命周期，至少先把状态卡死恢复、监控和回归测试补齐。
3. 同步处理 `P1-3`：把真实外部服务 integration 门禁纳入固定工作流，避免默认绿灯继续掩盖真实语义缺口。
4. 然后集中压缩 `P2-1` 和 `P2-2`：拆 `guests/views/recruit.py`、`battle/services.py`、`trade/selectors.py` 这几个最容易继续反弹的热点。
5. 最后处理 `P2-3`、`P2-4`、`P2-5`：重建异常分层、测试收集边界、coverage 可见性和测试抽象层。

## 9. 重构指导原则

后续重构不建议继续沿着“加 facade、加 wrapper、加 platform 名字层”的方向推进。当前项目最需要的是减少概念数量，而不是增加概念数量。

本轮已经证明，market / bank / raid / mission 这几条主链路在去掉动态 facade 之后，行为并没有变差，反而更容易测试和定位问题。因此后续可以默认采用“优先显式依赖，谨慎引入中间层”的策略。

建议遵循以下原则：

1. 一个写侧用例只保留一个权威入口。
2. facade 只保留稳定边界，不做运行时依赖拼装。
3. platform 只在确实需要隔离跨 app / 外部依赖时存在。
4. selector 只做读侧装配，不触发业务动作。
5. view 只保留请求解析、权限和响应装配，不负责事务、锁和副作用。
6. 关键链路先定义 fail-open / fail-closed，再写异常处理代码。
7. 所有并发设计都要明确“锁对象、锁时长、补偿路径、监控信号、测试方式”。
8. 测试门禁要明确区分“快速反馈”与“真实语义验证”，但两者都必须进入固定流程。

## 10. 当前结论

项目当前的核心问题，不是“还有没有明显 bug 没修掉”，而是“工程组织方式已经开始反噬开发效率和长期可维护性”。

更直接地说：

- 功能能力强于工程纪律；
- 业务复杂度增长快于模块边界治理；
- 默认测试绿灯强于真实生产语义保障。

综合评分下调为：`5.7/10`

分项参考：

- 功能完成度：`8/10`
- 业务复杂度承载能力：`7.5/10`
- 架构设计：`5.5/10`
- 工程纪律：`5/10`
- 测试可信度：`4.5/10`
- 可维护性：`5/10`

要把项目拉回高分区间，优先级不是“继续拆更多 facade”，而是：

1. 收敛边界；
2. 收紧写入口；
3. 收掉伪抽象；
4. 把真实语义门禁重新立起来。
