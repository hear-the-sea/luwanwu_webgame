# 项目技术审计与优化清单（2026-03）

本文档基于 2026-03-16 对仓库的静态审查、配置检查与代表性测试验证整理，目标是把后续优化工作落成一份可执行清单，而不是停留在口头评价。

本版已根据当前代码状态回收已明显解决的问题，并补入新的结构性发现。已从问题清单中移除的历史项包括：

- 全局 `context processor` 过重
- `gameplay/admin.py` 单文件过大
- 缺少核心域边界文档
- 缺少 ADR 沉淀

相关文档：

- [优化计划](optimization_plan.md)：已有的分阶段重构路线图
- [架构设计](architecture.md)：系统模块划分与数据流
- [开发指南](development.md)：开发、测试与运行方式

## 1. 审计范围与方法

本次审计覆盖：

- Django 配置层：`config/settings/*`、`config/asgi.py`
- 核心中间件与通用能力：`core/*`、`accounts/utils.py`
- 关键业务路径：`gameplay`、`guests`、`trade`、`websocket`
- 质量门禁：`pyproject.toml`、`Makefile`、`.github/workflows/ci.yml`
- 测试结构与默认测试路径：`pytest.ini`、`tests/*`
- 文档与仓库卫生：`README.md`、`docs/*`

本次已执行的验证：

- `python -m pytest -q tests/test_arena_rules_loader.py tests/test_guild_rules_loader.py tests/test_validate_yaml_configs_command.py tests/test_reload_runtime_configs_command.py tests/test_task_monitoring.py`
- `python -m pytest --collect-only -q`
- 针对运行期配置热更新与 YAML schema 覆盖率执行最小核验脚本

当前抽样结果：

- 相关回归测试 `20 passed`
- 当前可收集测试数 `1466`
- 已人工确认 `reload_runtime_configs` 对 `arena` / `guilds` 的部分导入时常量不生效

## 2. 当前状态快照

量化信号：

- 仓库内 Python 文件约 `815` 个（不含 `.venv`、`.git`、`node_modules`、`.claude`）
- 测试文件约 `180` 个
- 运行期 YAML 配置文件约 `22` 个
- 业务代码中 `except Exception` 约 `237` 处
- 以下热点文件总计 `4596` 行：
  - `gameplay/services/inventory/guest_items.py`
  - `gameplay/services/arena/core.py`
  - `gameplay/services/raid/combat/runs.py`
  - `guests/models.py`
  - `guests/views/recruit.py`
  - `trade/services/bank_service.py`
  - `gameplay/services/raid/combat/battle.py`
  - `websocket/consumers/world_chat.py`

整体判断：

- 优点：相比上版，模块拆分、Admin 拆包、边界文档和 ADR 都有明显进展，CI 也已经补上 infra-backed integration job。
- 问题：项目仍处在“功能密度高于治理强度”的阶段，配置热更新、默认测试语义、异常降级和可观测性仍存在表面稳定但约束不够硬的问题。

## 3. 优先级总览

建议按以下优先级推进：

| 优先级 | 主题 | 目标 |
| --- | --- | --- |
| P0 | 正确性与约束硬化 | 避免出现“功能看似可用但约束失效”的情况 |
| P1 | 架构拆分与复杂度收敛 | 减少超大文件、隐式耦合和职责漂移 |
| P1 | 质量门禁升级 | 让类型、测试、CI 真正具备拦截能力 |
| P2 | 可观测性与运维治理 | 把 silent degradation 变成可发现、可告警的问题 |
| P2 | 数据与配置治理 | 让 YAML 驱动配置变成可验证资产而不是风险输入 |
| P3 | 文档与仓库卫生 | 降低新人上手和长期维护成本 |

## 4. P0：正确性与约束硬化

### P0-1 单登录链路较上版收紧，但登录主路径仍有 fail-open 残留

现象：

- `core/middleware/single_session.py` 当前在会话校验异常时会记录降级并直接 `logout(request)`，这部分比上版更硬。
- 但 `accounts/utils.py` 中的 `purge_other_sessions()` 仍在同步失败时仅记录 warning，不向登录主流程返回失败信号。

影响：

- 登录阶段如果活跃 session 状态未能同步，用户仍可能拿到一个“登录成功但单登录状态未对齐”的结果。
- 约束失败范围已经缩小到登录主路径，但仍不是严格 fail-closed。

证据：

- `accounts/utils.py`
- `core/middleware/single_session.py`

建议：

- 为 `purge_other_sessions()` 提供显式成功/失败返回值，并在登录主流程决定是拒绝登录还是进入受限重试路径。
- 对认证、权限、库存扣减、资金冻结、单登录这类硬约束，默认 fail-closed。
- 将“缓存不可用”和“数据库不可用”拆分处理，不要统一吞成 warning。
- 为单登录增加显式的失败状态埋点和告警。

完成标准：

- 出现 session 同步异常时有明确策略和可观测信号。
- 登录主路径不再依赖“记录 warning 后继续执行”。

### P0-2 默认测试路径与生产语义差距过大

现象：

- `config/settings/__init__.py` 在默认测试场景下切到 `config/settings/testing.py`。
- 默认测试使用 SQLite、LocMem cache、InMemory channel layer。
- `make test` 默认不会运行依赖真实 MySQL/Redis 语义的关键并发测试。
- `.github/workflows/ci.yml` 已增加独立 `integration-tests` job，这是上版之后的改进。

影响：

- CI 风险比上版有所下降，但本地最高频反馈回路仍无法覆盖 `select_for_update`、Redis、Channels、Celery 的真实行为。
- 团队仍然容易误把 `make test` 视为“已验关键语义”。

证据：

- `config/settings/__init__.py`
- `config/settings/testing.py`
- `Makefile`
- `tests/test_raid_concurrency_integration.py`
- `tests/test_work_service_concurrency.py`

建议：

- 保留 hermetic 测试道，但把关键集成测试纳入更高频执行路径。
- 增加一个默认可跑的“轻量真实依赖”测试入口，例如本地 docker profile。
- 在 PR 模板和开发文档中明确：默认测试不等于生产语义验证。
- 对涉及行锁、冻结资金、库存扣减、出征并发的模块，强制要求集成测试。

完成标准：

- 并发与锁相关改动没有经过真实数据库语义验证就不能合并。
- 团队成员清楚区分 hermetic 测试和 infra-backed 测试。
- 本地默认测试入口会明确提示哪些能力尚未验证。

### P0-3 广泛吞异常会把真实错误变成“功能偶尔不完整”

现象：

- 业务代码存在大量 `except Exception`。
- 多处使用“打日志 + 返回默认值/空结果”的降级模式。

影响：

- 线上失败被包装成页面少一块数据、聊天历史为空、统计数异常、任务未触发等隐性故障。
- 排障难度高，容易积累脏数据和用户投诉。

典型位置：

- `websocket/consumers/world_chat.py`
- `trade/selectors.py`
- `config/asgi.py`
- `trade/tasks.py`
- `guests/tasks.py`
- `core/views/health.py`

建议：

- 建立异常分级规则：
  - 业务可预期异常：正常分支处理
  - 基础设施可恢复异常：降级，但必须打结构化日志和计数
  - 未知异常：直接抛出，不得兜底吞掉
- 新代码禁止无注释的裸 `except Exception`。
- 对现有关键路径的 broad catch 做一次专项收敛。

完成标准：

- 未知异常不会再被大面积吞掉。
- 所有允许降级的异常路径都有明确注释、日志字段和指标。

### P0-4 运行期配置热更新目前会制造“已刷新”的假象

现象：

- `gameplay/services/runtime_configs.py` 会清理并重新加载 arena / guild 等规则缓存。
- 但 `gameplay/services/arena/core.py` 在模块导入时把 `ARENA_RULES`、`ARENA_DAILY_PARTICIPATION_LIMIT` 等冻结成常量。
- `guilds/constants.py` 同样在模块导入时把 `_GUILD_RULES` 及相关常量冻结下来。
- 现有测试只验证 loader 归一化和命令输出，不验证 reload 之后同进程业务是否真正生效。

影响：

- 运维或策划执行 `reload_runtime_configs` 后会收到“已刷新”的成功反馈，但同进程内真实业务行为仍可能继续使用旧值。
- 这是高风险的“假热更新”：最危险之处在于它看起来成功了。

证据：

- `gameplay/services/runtime_configs.py`
- `gameplay/services/arena/core.py`
- `guilds/constants.py`
- `tests/test_reload_runtime_configs_command.py`

建议：

- 避免在业务模块导入时快照配置，改为通过 accessor、可刷新 settings 对象或显式注入读取当前值。
- 对仍需进程级缓存的规则，reload 后必须同步刷新依赖模块的有效常量，或者明确命令语义为“刷新 loader，仍需重启进程”。
- 增加端到端测试，验证 reload 后同一进程内竞技场与帮会相关逻辑确实使用新值。

完成标准：

- `reload_runtime_configs` 不再只刷新“看起来会生效”的 loader。
- 规则变更要么在同进程即时生效，要么在命令输出中明确要求重启。

## 5. P1：架构拆分与复杂度收敛

### P1-1 超大文件过多，模块边界已经开始失真

现象：

- 多个核心文件在 `500-800` 行区间。
- 文件内部同时混杂校验、查询、业务规则、缓存、展示拼装、日志和异常兜底。

影响：

- 理解成本高。
- 小改动也容易引起连锁回归。
- 新逻辑倾向继续往旧文件堆，形成“复杂度雪球”。

重点对象：

- `gameplay/services/inventory/guest_items.py`
- `gameplay/services/arena/core.py`
- `gameplay/services/raid/combat/battle.py`
- `gameplay/services/raid/combat/runs.py`
- `trade/services/bank_service.py`
- `guests/views/recruit.py`
- `websocket/consumers/world_chat.py`

建议：

- 以业务动作拆分，而不是按“utils/helpers”随意下沉。
- 推荐拆分层次：
  - `selectors`：只负责读取和聚合
  - `services`：只负责状态变更和事务
  - `policies/rules`：只负责规则计算
  - `presenters/view_helpers`：只负责展示上下文
- 为热点文件建立行数预算，例如单文件超过 `400` 行必须解释或拆分。

完成标准：

- 首批热点文件拆成职责明确的小模块。
- 新增逻辑不再继续堆入历史大文件。

### P1-2 WebSocket consumer 需要继续瘦身

现象：

- `websocket/consumers/world_chat.py` 已把历史、限流、消息构造拆到 `backends/` 与 `services/`，这是明显进展。
- 但 consumer 仍负责鉴权、显示名缓存、道具消费、退款、错误分级和 transport glue，职责仍偏多。

影响：

- 一个 consumer 承担过多业务职责，改动风险高。

建议：

- 拆分为：
  - history backend
  - rate limiter
  - message builder
  - inventory side effects
  - consumer transport glue
- 对聊天这类强实时功能，明确失败策略和补偿边界。

完成标准：

- consumer 保持通信编排角色，核心业务逻辑下沉到独立服务。

## 6. P1：质量门禁升级

### P1-3 mypy 当前更像“展示已接入”，不是“高信噪比防线”

现象：

- `pyproject.toml` 中 `disallow_untyped_defs = false`
- `ignore_missing_imports = true`
- `*.views` 和一批核心模块直接 `ignore_errors = true`

影响：

- 最复杂、最容易出错的模块恰恰没有静态约束。
- mypy 通过不代表风险低，只代表绕开的地方够多。

建议：

- 将“忽略名单”转为治理 backlog，并持续缩小范围。
- 新模块默认要求完整类型标注。
- 优先治理 service、selector、rule 层，再推进 view 层。
- 每次 PR 禁止新增新的 `ignore_errors` 范围。

完成标准：

- 豁免模块数量持续下降。
- 新核心逻辑文件默认全量类型检查。

### P1-4 覆盖率门槛仍偏保守，且缺少查询/性能基线

现象：

- CI 的 unit coverage 门槛已从上版的 `60%` 提高到 `65%`。
- CI 现在也有独立 integration job，但覆盖率目标仍主要围绕 unit 路径。
- 目前缺少明确的查询次数基线测试、性能回归测试。

影响：

- 对这种状态机多、并发多、缓存多的项目来说，`65%` 仍更像底线，不像质量门槛。
- N+1、缓存击穿、重查询回归难以及早发现。

建议：

- 将覆盖率门槛逐步提高到更合理水平。
- 为首页、交易、仓库、招募、战斗详情等热点页面补查询基线测试。
- 增加轻量性能烟测，不追求压测级别，但要能发现明显回退。

完成标准：

- 覆盖率门槛阶段性提升。
- 热点页面有查询上限保护。

### P1-5 默认测试入口需要更清晰地表达质量等级

现象：

- `make test`、`make test-unit`、`make test-critical`、`make test-integration` 已经存在，但语义不够醒目。

影响：

- 团队成员容易误把 `make test` 视为“已经验全”。

建议：

- 重命名或补文档说明，例如：
  - `test-fast`
  - `test-hermetic`
  - `test-db-locks`
  - `test-integration`
- 在输出中显式提示哪些能力未被验证。

完成标准：

- 每个测试入口对应的风险边界是清楚的。

## 7. P2：可观测性与运维治理

### P2-1 降级路径很多，但指标和告警不够系统

现象：

- 项目中大量使用“缓存失败就回退”“Redis 失败就跳过”“聊天历史不可用就返回空”的模式。
- 健康检查已经有，但运行中缺少统一 metrics 面。

影响：

- 服务可能长期处于 degraded 状态而不自知。
- 日志里有 warning，不等于团队真正看得到问题。

建议：

- 为关键降级路径增加计数器和告警：
  - cache fallback 次数
  - Redis 失败次数
  - chat history degraded 次数
  - world chat refund 次数
  - session sync failure 次数
- 统一日志字段，至少带：
  - `request_id`
  - `user_id`
  - `manor_id`
  - `task_name`
  - `degraded=true/false`

完成标准：

- 关键降级路径都能在 dashboard 或日志平台中检索和告警。

### P2-2 Celery 与异步链路需要更明确的监控闭环

现象：

- 已有 `health_ready` 与 beat heartbeat 检查。
- `core/utils/task_monitoring.py` 当前通过 `cache.get -> 本地改写 -> cache.set` 维护任务计数，在多 worker 下不是原子操作。
- 现有 `tests/test_task_monitoring.py` 只覆盖单进程序列调用，没有验证多进程/多 worker 共享缓存下的计数正确性。
- 任务失败、重试、积压、补偿逻辑的监控闭环仍不够完整。

影响：

- 多 worker 环境下成功/失败/重试计数可能丢失或互相覆盖。
- 监控面如果建立在这些计数之上，会出现“业务在退化，但指标看起来还行”的错觉。

建议：

- 明确区分：
  - 可重试失败
  - 业务拒绝
  - 人工介入异常
- 为关键任务建立运行指标：
  - 成功率
  - 失败率
  - 重试次数
  - 队列积压
  - 执行耗时
- 对共享缓存上的任务计数改用原子自增方案，例如 Redis hash / counter，避免 `get-set` 读改写竞争。
- 对“扫描兜底”类任务补说明，避免它们变成长期隐藏主路径问题的遮羞布。

完成标准：

- 异步链路问题可从指标定位，而不是只能翻日志。
- 任务计数在多 worker 场景下仍保持可信。

### P2-3 健康检查做得不错，但可以继续产品化

现象：

- `core/views/health.py` 已覆盖 DB、cache、channel layer、Celery broker、worker、beat、roundtrip。

建议：

- 将健康检查结果接入部署流程和告警系统。
- 补一份运维手册，说明每个检查项失败时的排查路径。
- 对 readiness 检查设置合理 timeout 和分级。

完成标准：

- 健康检查不仅能返回 JSON，还能真正驱动值班排障。

## 8. P2：数据与配置治理

### P2-4 YAML 配置驱动范围大，但 schema 化仍需加强

现象：

- 仓库里存在大量 `data/*.yaml` 运行期配置。
- `core/utils/yaml_schema.py` 当前只覆盖 `22` 个顶层 YAML 中的 `9` 个。
- `validate_yaml_configs` 默认会对未覆盖文件仅输出 warning 并返回成功；只有 `--strict-coverage` 才会失败。
- 现有测试已把“跳过未覆盖 YAML 也算成功”固化为预期行为。

影响：

- 像 `technology_templates.yaml`、`guild_rules.yaml`、`guest_skills.yaml`、`auction_items.yaml` 这类关键配置仍可能在导入时、运行时甚至用户操作时才暴露错误。
- 当前校验命令更像“部分体检”，容易给人一种“全部 YAML 已验”的错觉。

建议：

- 先把所有顶层运行期 YAML 纳入覆盖，再讨论更细粒度 schema。
- 补负例测试，不只验证“正确配置可导入”，也验证“错误配置会被拦下”。
- 将 `strict coverage` 提升为 CI 默认路径，而不是可选项。
- 导入命令支持 `--dry-run`、差异摘要、失败报告。
- 关键模板文件建立变更评审清单。

完成标准：

- 配置错误在导入前或导入时被明确阻断。
- 运行期 YAML 覆盖率接近 `100%`，且未覆盖文件不会静默通过。

## 9. P3：文档与仓库卫生

### P3-1 README 信息量过大，混合了设计稿、现状和操作手册

现象：

- `README.md` 同时承担产品设计、现状说明、项目结构、开发指南、部署说明等职责，体量过大。

影响：

- 新人难以快速定位最需要的信息。
- 文档更容易陈旧和互相矛盾。

建议：

- README 收缩为：
  - 项目简介
  - 快速开始
  - 文档导航
  - 常用命令
- 将长期设计描述下沉到 `docs/`。
- 标注“规划中”和“已落地”内容的边界，避免读者误判。

完成标准：

- README 更像入口文档，不再像大而全说明书。

### P3-2 审计清单已经建立，但仍缺少显式状态字段与完成时间

现象：

- 本文档已经承担了审计输入的角色，这是比上版更进一步的地方。
- 但每一项仍缺少统一的状态、负责人、最后核对时间和完成日期字段。

建议：

- 后续每完成一轮治理，都在本文档中回填状态：
  - 未开始
  - 进行中
  - 已完成
  - 延后
- 为高优问题补上：
  - owner
  - last_checked_at
  - done_at

完成标准：

- 优化工作可追踪，不再依赖聊天记录或个人记忆。

## 10. 建议执行顺序

### 第一阶段：2 周内完成的治理项

- 收敛认证、单登录、库存/资金类路径的 broad catch。
- 梳理 fail-open / fail-closed 策略，并写成规则。
- 修正 `reload_runtime_configs` 的假热更新问题，至少先让命令语义与真实行为一致。
- 给关键降级路径补 metrics 和结构化日志字段。
- 补文档，明确默认测试道与集成测试道的边界。

### 第二阶段：2-4 周完成的治理项

- 拆分首批热点文件：
  - `gameplay/services/raid/combat/runs.py`
  - `gameplay/services/raid/combat/battle.py`
  - `trade/services/bank_service.py`
  - `websocket/consumers/world_chat.py`
- 缩小 `pyproject.toml` 中 mypy 豁免范围。
- 将任务监控计数改成多 worker 下可信的原子实现。
- 给热点页面补查询次数基线测试。

### 第三阶段：持续推进

- 继续拆分大文件和残余聚合模块。
- 为 YAML 驱动配置补齐 schema、dry-run 和负例测试，并把 strict coverage 纳入默认 CI。
- 将指标、日志、健康检查接入统一运维面板。
- 逐步提高覆盖率门槛。

## 11. 建议建立的跟踪模板

后续可按以下模板登记每个优化项：

| 编号 | 主题 | 优先级 | 状态 | 负责人 | 目标完成时间 | 验证方式 |
| --- | --- | --- | --- | --- | --- | --- |
| P0-1 | 单登录约束硬化 | P0 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | accounts/utils.py bool return + signals.py degradation recording; 1485 tests pass |
| P0-2 | 测试路径分层说明与集成门禁 | P0 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | Makefile test 目标输出层级说明；docs/development.md 补全测试层级表格与并发敏感路径指引 |
| P0-3 | broad catch 收敛专项 | P0 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | 所有热点文件已用 _is_expected_*_error + raise 模式；health.py 中的 broad catch 为健康检查语义正确行为 |
| P0-4 | 运行期配置热更新纠偏 | P0 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | refresh_arena_constants + refresh_guild_constants 已接入 reload 命令；命令输出含 WARNING 说明视图层需重启 |
| P1-1 | 超大文件拆分 | P1 | 未开始 |  |  | 代码审查 + 行数基线 |
| P1-2 | WebSocket consumer 瘦身 | P1 | 未开始 |  |  | 代码审查 |
| P1-3 | mypy 高信噪比防线 | P1 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | ignore_errors 范围大幅收窄；20+ 干净模块加入 disallow_untyped_defs=true；mypy 0 errors on all clean modules |
| P1-4 | 覆盖率门槛提升 | P1 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | CI fail-under 从 65% 提到 75%（实测覆盖率已达 75%）|
| P1-5 | 默认测试入口分层说明 | P1 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | Makefile test 目标输出明确区分 hermetic 与 integration |
| P2-1 | 降级指标统一化 | P2 | 未开始 |  |  | 指标 dashboard + 告警验证 |
| P2-2 | 任务监控原子计数 | P2 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | task_monitoring.py 改用 cache.incr() 原子自增；测试覆盖单进程和缓存失败路径 |
| P2-3 | 健康检查产品化 | P2 | 未开始 |  |  | 运维手册 + 告警接入 |
| P2-4 | YAML schema 全覆盖 | P2 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | 22/22 配置文件已覆盖；57 个负例测试；strict coverage 已纳入 CI |
| P3-1 | README 重构 | P3 | 未开始 |  |  | 文档审查 |
| P3-2 | 审计清单状态字段 | P3 | ✅ 已完成 2026-03-16 | Claude | 2026-03-16 | 本表格即为跟踪结果 |

## 12. 本次审计结论

这个项目不是“缺工程化”，而是“工程化已经铺开，但约束和边界还不够硬”。下一阶段最值得做的，不是继续叠功能，而是先把下面三件事做扎实：

1. 把正确性约束做硬，减少“尽量兜底”的灰色地带。
2. 把热点模块拆小，阻止复杂度继续堆积。
3. 把测试、类型、监控变成真正有效的门禁，而不是形式上的存在。

只要这三件事推进到位，后面的功能迭代成本会明显下降，线上风险也会更可控。
