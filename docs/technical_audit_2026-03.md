# 项目技术审计与优化清单（2026-03）

本文档基于 2026-03-16 对仓库的静态审查、配置检查与代表性测试验证整理，目标是把后续优化工作落成一份可执行清单，而不是停留在口头评价。

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

- `make lint`
- `python -m pytest -q tests/test_settings_base.py tests/test_single_session_middleware.py tests/test_world_chat_consumer.py tests/test_trade_selectors.py`
- `python -m pytest --collect-only -q`

当前抽样结果：

- `make lint` 通过
- 代表性测试 `43 passed`
- 当前可收集测试数 `1381`

## 2. 当前状态快照

量化信号：

- Python 源文件约 `578` 个
- 测试文件约 `177` 个
- 运行期 YAML 配置文件约 `22` 个
- 业务代码中 `except Exception` 约 `237` 处
- 以下热点文件总计 `5355` 行：
  - `gameplay/services/inventory/guest_items.py`
  - `gameplay/services/arena/core.py`
  - `gameplay/services/raid/combat/battle.py`
  - `gameplay/services/raid/combat/runs.py`
  - `guests/views/recruit.py`
  - `guests/models.py`
  - `gameplay/admin.py`
  - `trade/services/bank_service.py`

整体判断：

- 优点：工程化意识明显，测试规模不小，CI、健康检查、缓存与并发防护都已经起步。
- 问题：项目已经进入“复杂度开始反噬”的阶段，很多地方用降级、兜底和宽泛异常处理维持表面稳定，导致边界不够硬、错误不够可见、默认反馈回路与真实生产语义存在偏差。

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

### P0-1 单登录约束当前是“尽力而为”，不是硬约束

现象：

- `accounts/utils.py` 中的 `purge_other_sessions()` 在同步失败时只记日志，不中止登录流程。
- `core/middleware/single_session.py` 在读取缓存、校验活跃 session 失败时会降级放行。

影响：

- 基础设施抖动时，单登录约束可能静默失效。
- 这类问题很难在页面层被发现，但会直接破坏安全和业务承诺。

证据：

- `accounts/utils.py`
- `core/middleware/single_session.py`

建议：

- 明确哪些能力必须 fail-closed，哪些可以 fail-open。
- 对认证、权限、库存扣减、资金冻结、单登录这类硬约束，默认 fail-closed。
- 将“缓存不可用”和“数据库不可用”拆分处理，不要统一吞成 warning。
- 为单登录增加显式的失败状态埋点和告警。

完成标准：

- 出现 session 同步异常时有明确策略和可观测信号。
- 认证约束相关路径不再依赖“记录 warning 后继续执行”。

### P0-2 默认测试路径与生产语义差距过大

现象：

- `config/settings/__init__.py` 在默认测试场景下切到 `config/settings/testing.py`。
- 默认测试使用 SQLite、LocMem cache、InMemory channel layer。
- `make test` 默认不会运行依赖真实 MySQL/Redis 语义的关键并发测试。

影响：

- 日常开发反馈回路无法覆盖 `select_for_update`、Redis、Channels、Celery 的真实行为。
- 容易形成“本地和单测都稳，线上才暴露”的错觉。

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

### P0-3 广泛吞异常会把真实错误变成“功能偶尔不完整”

现象：

- 业务代码存在大量 `except Exception`。
- 多处使用“打日志 + 返回默认值/空结果”的降级模式。

影响：

- 线上失败被包装成页面少一块数据、聊天历史为空、统计数异常、任务未触发等隐性故障。
- 排障难度高，容易积累脏数据和用户投诉。

典型位置：

- `gameplay/context_processors.py`
- `websocket/consumers/world_chat.py`
- `trade/selectors.py`
- `config/asgi.py`
- `trade/tasks.py`
- `guests/tasks.py`

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
- `gameplay/admin.py`

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

### P1-2 Context processor 承担了过多运行时职责

现象：

- `gameplay/context_processors.py` 不只是拼模板上下文，还承担缓存访问、Redis 统计、在线用户回退、排行加载、消息数统计等职责。

影响：

- 每个模板请求都可能触发多层依赖。
- 页面渲染链路变得脆弱，且难以做精细性能分析。

建议：

- 将全局模板上下文限制在真正轻量、稳定的字段。
- 复杂统计移到 selector 或页面专属接口。
- 对首页和侧边栏这类“重上下文”做按页面加载，不要挂到全站模板链路。

完成标准：

- 全局 context processor 只保留轻量级、低失败风险字段。
- 重统计逻辑从全局渲染路径剥离。

### P1-3 Admin 层过重，不利于长期维护

现象：

- `gameplay/admin.py` 体积过大，容易成为后台配置逻辑、格式化逻辑和查询优化的聚合点。

影响：

- Django Admin 代码难以测试。
- 配置行为与业务行为容易互相污染。

建议：

- 按资源域拆分 admin 模块，例如建筑、任务、仓库、活动、统计。
- 复杂展示逻辑使用专门的 helper，不要堆在 `ModelAdmin` 类里。
- 为关键管理动作补最小回归测试。

完成标准：

- Admin 不再是单一巨型入口。

### P1-4 WebSocket consumer 需要继续瘦身

现象：

- `websocket/consumers/world_chat.py` 同时负责鉴权、速率限制、历史管理、消息构造、道具消费、退款和降级策略。

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

### P1-5 mypy 当前更像“展示已接入”，不是“高信噪比防线”

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

### P1-6 覆盖率门槛偏低，且缺少查询/性能基线

现象：

- CI 的 unit coverage 门槛为 `60%`。
- 目前缺少明确的查询次数基线测试、性能回归测试。

影响：

- 对这种状态机多、并发多、缓存多的项目来说，`60%` 更像底线，不像质量门槛。
- N+1、缓存击穿、重查询回归难以及早发现。

建议：

- 将覆盖率门槛逐步提高到更合理水平。
- 为首页、交易、仓库、招募、战斗详情等热点页面补查询基线测试。
- 增加轻量性能烟测，不追求压测级别，但要能发现明显回退。

完成标准：

- 覆盖率门槛阶段性提升。
- 热点页面有查询上限保护。

### P1-7 默认测试入口需要更清晰地表达质量等级

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
- 但任务失败、重试、积压、补偿逻辑的监控闭环不够完整。

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
- 对“扫描兜底”类任务补说明，避免它们变成长期隐藏主路径问题的遮羞布。

完成标准：

- 异步链路问题可从指标定位，而不是只能翻日志。

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
- 当前已有部分导入命令和测试，但配置治理仍偏“工程师自觉”。

影响：

- 配置错误可能在导入时、运行时甚至用户操作时才暴露。

建议：

- 为高价值 YAML 建立统一 schema 校验。
- 补负例测试，不只验证“正确配置可导入”，也验证“错误配置会被拦下”。
- 导入命令支持 `--dry-run`、差异摘要、失败报告。
- 关键模板文件建立变更评审清单。

完成标准：

- 配置错误在导入前或导入时被明确阻断。

### P2-5 配置、缓存、事务三者的边界要更清楚

现象：

- 部分业务路径同时使用 YAML 配置、缓存值和事务锁，依赖关系较隐式。

建议：

- 为关键域补架构说明：
  - 数据来源是什么
  - 何时缓存
  - 何时失效
  - 事务边界在哪里
  - 失败后如何补偿
- 优先覆盖交易、拍卖、出征、招募、门客装备。

完成标准：

- 核心业务域具备可落地的状态流与一致性说明。

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

### P3-2 技术债文档已经有，但缺少审计结果与执行闭环

现象：

- 已有 `docs/optimization_plan.md`，但更偏路线图。

建议：

- 将本文档作为“现状审计输入”，与优化计划配合使用。
- 后续每完成一轮治理，都在本文档中回填状态：
  - 未开始
  - 进行中
  - 已完成
  - 延后

完成标准：

- 优化工作可追踪，不再依赖聊天记录或个人记忆。

### P3-3 仓库中缺少更明确的架构决策沉淀

建议：

- 为关键决策补 ADR（Architecture Decision Record），至少覆盖：
  - 默认测试为何使用 hermetic 模式
  - 哪些路径允许 fail-open
  - Redis / Celery / Channels 的拆分原则
  - YAML 配置与数据库配置的边界

完成标准：

- 关键工程取舍有文档依据，新人能理解“为什么这样做”。

## 10. 建议执行顺序

### 第一阶段：2 周内完成的治理项

- 收敛认证、单登录、库存/资金类路径的 broad catch。
- 梳理 fail-open / fail-closed 策略，并写成规则。
- 给关键降级路径补 metrics 和结构化日志字段。
- 补文档，明确默认测试道与集成测试道的边界。

### 第二阶段：2-4 周完成的治理项

- 拆分首批热点文件：
  - `gameplay/services/raid/combat/runs.py`
  - `gameplay/services/raid/combat/battle.py`
  - `trade/services/bank_service.py`
  - `websocket/consumers/world_chat.py`
- 缩小 `pyproject.toml` 中 mypy 豁免范围。
- 给热点页面补查询次数基线测试。

### 第三阶段：持续推进

- 继续拆分大文件和 admin 聚合模块。
- 为 YAML 驱动配置补 schema、dry-run 和负例测试。
- 将指标、日志、健康检查接入统一运维面板。
- 逐步提高覆盖率门槛。

## 11. 建议建立的跟踪模板

后续可按以下模板登记每个优化项：

| 编号 | 主题 | 优先级 | 状态 | 负责人 | 目标完成时间 | 验证方式 |
| --- | --- | --- | --- | --- | --- | --- |
| P0-1 | 单登录约束硬化 | P0 | 未开始 |  |  | 集成测试 + 异常演练 |
| P0-2 | 测试路径分层说明与集成门禁 | P0 | 未开始 |  |  | 文档 + CI + 本地脚本 |
| P0-3 | broad catch 收敛专项 | P0 | 未开始 |  |  | 代码审查 + 日志验证 |

## 12. 本次审计结论

这个项目不是“缺工程化”，而是“工程化已经铺开，但约束和边界还不够硬”。下一阶段最值得做的，不是继续叠功能，而是先把下面三件事做扎实：

1. 把正确性约束做硬，减少“尽量兜底”的灰色地带。
2. 把热点模块拆小，阻止复杂度继续堆积。
3. 把测试、类型、监控变成真正有效的门禁，而不是形式上的存在。

只要这三件事推进到位，后面的功能迭代成本会明显下降，线上风险也会更可控。
