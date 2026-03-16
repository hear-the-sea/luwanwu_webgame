# 项目技术审计与优化清单（2026-03）

本文档基于 2026-03-16 对仓库的静态审查、配置检查与代表性测试验证整理，只保留当前代码里仍然成立的问题。已闭环或本轮未再观察到反例的事项已从正文移除，避免把历史问题继续挂在当前审计结果里。

相关文档：

- [优化计划](optimization_plan.md)：已有的分阶段重构路线图
- [架构设计](architecture.md)：系统模块划分与数据流
- [开发指南](development.md)：开发、测试与运行方式

## 1. 审计范围与方法

本次审计覆盖：

- Django 配置层：`config/settings/*`、`config/asgi.py`
- 核心通用能力：`core/*`、`common/utils/celery.py`
- 关键业务路径：`gameplay`、`guests`、`trade`、`accounts`、`websocket`
- 质量门禁：`pyproject.toml`、`Makefile`、`.github/workflows/ci.yml`
- 测试结构与代表性回归：`tests/*`
- 当前技术债文档：`docs/technical_audit_2026-03.md`

本次实际执行的验证：

- `pytest -q tests/test_common_celery_utils.py tests/test_cache_lock_utils.py tests/test_bank_service_rates.py tests/test_raid_combat_runs.py`
- `pytest -q tests/test_accounts.py -k 'fail_closed or login_attempts'`
- `python manage.py check --deploy`

当前抽样结果：

- 代表性回归测试 `57 passed, 10 deselected`
- `manage.py check --deploy` 在当前本地开发环境下返回 `6` 条安全告警；这说明默认运行态仍偏开发模式，但不单独作为代码缺陷条目展开

## 2. 当前状态快照

量化信号：

- 核心业务与配置目录 Python 文件约 `610` 个
- 测试 Python 文件约 `183` 个
- `data/` 顶层 YAML 配置文件 `22` 个
- 业务代码中 `except Exception` / 裸 `except:` / `except BaseException` 约 `249` 处
- 当前仍显著偏大的热点文件：
  - `gameplay/services/inventory/guest_items.py` `837` 行
  - `gameplay/services/raid/combat/runs.py` `534` 行
  - `guests/views/recruit.py` `517` 行
  - `trade/services/bank_service.py` `489` 行
  - `gameplay/services/arena/core.py` `444` 行
  - `gameplay/services/__init__.py` `335` 行

整体判断：

- 优点：文档、测试、CI、并发敏感路径的工程意识已经铺开，项目不是“没工程化”。
- 问题：当前主要短板不是功能缺失，而是硬约束、门禁和可观测性之间仍有漏口。很多地方已经有封装和补偿，但还没把这些封装变成真正被所有调用方遵守的系统约束。

## 3. 优先级总览

建议按以下优先级推进：

| 优先级 | 主题 | 目标 |
| --- | --- | --- |
| P0 | 关键状态一致性硬化 | 避免任务调度异常后出现“数据库已改、收尾没做”的半完成状态 |
| P0 | 生产语义验证收口 | 降低团队把 hermetic 测试通过误判为生产语义正确的风险 |
| P1 | 质量门禁升级 | 让类型检查和运行时指标真正覆盖高风险区域 |
| P1 | 复杂度收敛 | 把热点模块继续拆小，减少伪分层和隐式耦合 |
| P2 | 审计与观测治理闭环 | 让技术审计、指标和代码状态保持同步 |

## 4. P0：关键状态一致性硬化

### P0-1 多个关键状态流没有兑现 `safe_apply_async()` 的契约

现象：

- `common/utils/celery.py` 已经明确约定：对“must-execute”场景，调用方必须检查返回值并在失败时走同步 fallback 或显式报错。
- 但多个关键状态流仍只是调用 `safe_apply_async()`，没有消费返回值：
  - `gameplay/services/raid/combat/runs.py`
  - `gameplay/services/raid/scout.py`
  - `gameplay/services/buildings/ranch.py`
  - `gameplay/services/buildings/stable.py`
  - `gameplay/services/buildings/smithy.py`
  - `gameplay/services/manor/core.py`
- 同一项目中也存在对比鲜明的正例：`gameplay/services/missions_impl/execution.py`、`gameplay/services/raid/combat/runs.py` 的部分路径已经会在 dispatch 失败后同步补偿或显式记录。

影响：

- 这不是单纯的“消息延迟”问题，而是状态机一致性问题。
- 一旦 broker / worker / import 链异常，数据库状态可能已经切到“撤退中”“返程中”“生产中”，但后续完成动作没人执行，只能寄希望于用户刷新、扫描任务或人工补偿。
- 同一封装在不同调用点语义不一致，会让维护者误以为“用了统一 helper 就安全”，实际上安全性仍取决于调用者是否记得补返回值处理。

证据：

- `common/utils/celery.py`
- `gameplay/services/raid/combat/runs.py`
- `gameplay/services/raid/scout.py`
- `gameplay/services/buildings/ranch.py`
- `gameplay/services/buildings/stable.py`
- `gameplay/services/buildings/smithy.py`
- `gameplay/services/manor/core.py`

建议：

- 给 `safe_apply_async()` 的调用点做一次分级清点：
  - 纯优化型任务：允许 best-effort
  - 状态推进型任务：必须检查返回值
- 对撤退、返程、生产完成、建筑升级完成这类状态推进链路，统一补：
  - dispatch 失败后的同步补偿
  - 或显式 fail-closed
- 为关键调用点补测试，直接断言“dispatch 返回 False 时状态如何收口”。

完成标准：

- 所有关键状态推进动作都能回答“调度失败后谁来收尾”。
- 不再存在“helper 契约要求处理失败，但调用方直接忽略返回值”的路径。

### P0-2 默认测试路径与真实生产语义仍有明显距离

现象：

- 默认测试设置仍使用 SQLite、LocMem cache、InMemory channel layer、memory broker。
- `CI` 虽已加入 MySQL + Redis 集成测试 job，也在注释里说明了 hermetic 套件无法覆盖真实语义。
- 但团队最常运行的本地反馈回路，依然不是 MySQL / Redis / 真实 Channels / 真实 broker 语义。

影响：

- `select_for_update()`、共享缓存锁、分布式去重、Celery broker、Channels Redis 行为这类问题，依旧容易在日常开发阶段被低估。
- 当前流程已经“知道边界”，但还没把“高风险改动必须跑真实依赖验证”收紧成真正的默认约束。

证据：

- `config/settings/testing.py`
- `Makefile`
- `.github/workflows/ci.yml`
- `docs/development.md`

建议：

- 保留 hermetic 套件，但在开发文档和 PR 约束里更直接地区分：
  - 能证明业务基本正确的测试
  - 只能证明代码在假依赖下可运行的测试
- 对包含以下特征的改动，要求显式跑 infra-backed 验证：
  - `select_for_update()`
  - 共享缓存锁 / dedup
  - Celery dispatch / retry / scanner fallback
  - Channels / Redis 聊天链路
- 把“哪些改动必须附集成测试验证结果”写成仓库规则，而不只写在注释里。

完成标准：

- 高风险模块改动不再默认只靠 hermetic 套件背书。
- 团队不会把“默认测试通过”误读为“生产语义已经验证”。

### P0-3 broad catch 仍然大量存在，灰色故障风险依旧高

现象：

- 当前业务代码中仍有约 `249` 处 broad catch。
- 虽然部分路径已经补了 `degraded=True` 或 fallback 注释，但仍有大量逻辑采用“记 warning 然后继续跑”的模式。

影响：

- 它会持续制造“看起来没挂，但结果不完整”的灰色故障。
- 这类故障最难排查，因为表面功能往往还能继续使用，真正的问题会被拖到后续状态校正、客服反馈或数据核对时才暴露。

典型位置：

- `trade/services/bank_service.py`
- `common/utils/celery.py`
- `websocket/consumers/world_chat.py`
- `gameplay/services/raid/combat/battle.py`
- `gameplay/services/missions_impl/execution.py`
- `accounts/views.py`

建议：

- 继续推进异常分级收口：
  - 可预期业务异常：正常返回
  - 明确的基础设施异常：允许降级，但必须带结构化上下文
  - 未知异常：直接抛出
- 优先收敛资金、库存、聊天消费、异步状态推进相关路径。

完成标准：

- 未知异常不再被大范围吞掉。
- 每一条保留的 broad catch 都能清楚说明“为何允许继续”和“如何观测”。

## 5. P1：质量门禁与复杂度收敛

### P1-1 mypy 已接入，但仍不是高信噪比门禁

现象：

- 全局 `disallow_untyped_defs = false`。
- `ignore_missing_imports = true`。
- `*.views`、`gameplay.models.*`、`gameplay.services.raid.*`、`guests.services.*` 等高风险区域仍在 `ignore_errors` 名单中。

影响：

- 最复杂、最容易出错的区域，恰恰没有被静态检查真正约束。
- 当前 mypy 更像“项目已接入类型检查”，还不是“高风险回归的可靠门禁”。

证据：

- `pyproject.toml`

建议：

- 缩小 `ignore_errors` 时优先清理高风险服务层，而不是先做边角模块。
- 对新建核心模块直接要求完整注解，不允许进入豁免名单。
- 在 PR 审查中把“是否新增类型豁免”列为显式检查项。

完成标准：

- 高风险服务层的类型豁免范围持续缩小。
- 新核心逻辑默认处于严格类型检查之下。

### P1-2 `task_monitoring` 的任务注册表仍有丢更新竞态

现象：

- `core/utils/task_monitoring.py` 的计数本身通过 `cache.incr()` 做了原子化。
- 但任务名注册表仍然是 `cache.get()` -> 修改集合 -> `cache.set()` 的 read-modify-write。
- 当前测试主要验证单线程 / 单进程快照，不覆盖多 worker 并发首次写入不同 task name 的情况。

影响：

- 指标数值可能是对的，但“哪些任务出现在快照里”并不完全可信。
- 一旦注册表丢写，`health_ready` 等依赖快照枚举的地方会表现出“部分任务从监控里消失”的问题。

证据：

- `core/utils/task_monitoring.py`
- `tests/test_task_monitoring.py`
- `core/views/health.py`

建议：

- 把任务名注册从集合读改写，换成真正的原子方案：
  - Redis set / hash 原子写
  - 或单独的 append-only key 设计
- 为并发首次注册补集成测试，而不是只测串行快照。

完成标准：

- 任务注册表不再依赖非原子的 `get/set` 回写。
- 监控快照在多 worker 并发下仍然稳定完整。

### P1-3 热点模块虽然已有拆分，但复杂度仍然集中

现象：

- `yaml_schema.py`、`arena/core.py`、`runs.py` 已经比旧版本明显收缩，说明拆分在起作用。
- 但当前仍有多处热点文件超过或逼近 `500` 行，且内部职责仍偏混合。

影响：

- 复杂度不是“没有下降”，而是还没降到足够安全的水平。
- 新逻辑如果继续往这些热点文件堆，后续维护成本会很快反弹。

重点对象：

- `gameplay/services/inventory/guest_items.py`
- `gameplay/services/raid/combat/runs.py`
- `guests/views/recruit.py`
- `trade/services/bank_service.py`
- `gameplay/services/arena/core.py`
- `gameplay/services/__init__.py`

建议：

- 下一轮拆分优先看“一个文件里同时承担规则计算、状态变更、任务调度、消息通知”的模块。
- 聚合导出层只保留稳定兼容入口，避免继续扩张。
- 给热点文件设明确预算，超过阈值必须在 PR 描述里解释原因。

完成标准：

- 热点文件继续收缩到职责明确的单元。
- 聚合层不再成为隐藏耦合的总入口。

## 6. P2：审计与观测治理闭环

### P2-1 技术审计文档已经出现与代码状态不一致的内容

现象：

- 当前文档旧版本仍保留了已解决问题和过期数字，例如：
  - `core/utils/yaml_schema.py` 仍写成 `1807` 行
  - `gameplay/services/arena/core.py` 仍写成 `757` 行
  - `gameplay/services/raid/combat/runs.py` 仍写成 `639` 行
- 跟踪模板中也混入了大量“已完成”条目，与“正文只保留当前问题”的目标冲突。

影响：

- 技术审计文档一旦和代码状态脱节，就会失去治理价值。
- 团队会分不清哪些风险仍在，哪些只是历史记录。

证据：

- `docs/technical_audit_2026-03.md`
- 当前仓库实际文件行数统计

建议：

- 审计文档只保留当前仍成立的问题；已完成事项迁到独立 changelog 或优化记录。
- 文档中的量化数字必须来自本轮实际命令输出，不接受手工沿用旧值。
- 在每次较大重构后，把“同步更新审计文档”作为收尾步骤，而不是可选动作。

完成标准：

- 审计文档与当前代码状态保持同步。
- 历史完成项与当前待办项分离，避免继续混杂。

## 7. 建议执行顺序

### 第一阶段：1-2 周内完成

- 逐一清点 `safe_apply_async()` 的关键调用点，补齐失败返回值处理。
- 为撤退、返程、生产完成、建筑升级完成这类状态推进链路补回归测试。
- 在开发文档和 PR 要求中收紧 infra-backed 验证规则。

### 第二阶段：2-4 周内完成

- 修复 `task_monitoring` 注册表的并发写入方案。
- 继续收敛资金、库存、聊天消费、异步状态推进相关 broad catch。
- 缩小 mypy 的高风险豁免范围。

### 第三阶段：持续推进

- 继续拆分热点模块和聚合导出层。
- 让审计文档、指标暴露和代码状态维持同频更新。

## 8. 当前待跟踪项模板

后续可按以下模板登记当前仍需推进的事项：

| 编号 | 主题 | 优先级 | 状态 | 负责人 | 目标完成时间 | 验证方式 |
| --- | --- | --- | --- | --- | --- | --- |
| P0-1 | 关键状态流补齐异步调度失败收口 | P0 | 待处理 | TBD | TBD | 新增 dispatch=False 回归测试；关键路径不再忽略返回值 |
| P0-2 | 高风险改动的真实依赖验证约束 | P0 | 待处理 | TBD | TBD | 文档、PR 规范、CI 说明同步更新 |
| P0-3 | broad catch 收敛专项 | P0 | 待处理 | TBD | TBD | 关键路径未知异常不再被吞掉 |
| P1-1 | mypy 高风险区治理 | P1 | 待处理 | TBD | TBD | 缩小 `ignore_errors` 清单 |
| P1-2 | task_monitoring 并发注册修复 | P1 | 待处理 | TBD | TBD | 并发写入测试通过；快照稳定完整 |
| P1-3 | 热点模块继续拆分 | P1 | 待处理 | TBD | TBD | 热点文件行数和职责继续下降 |
| P2-1 | 审计与指标文档同步机制 | P2 | 待处理 | TBD | TBD | 当前问题与历史完成项分离维护 |

## 9. 本次审计结论

这个项目当前的主要问题，不再是“完全缺少工程化”，而是“封装、门禁和治理闭环还没有完全落到调用方和流程上”。你已经有了统一 helper、集成测试、健康检查和技术审计，但其中仍有几处关键漏口：

1. `helper` 的契约没有被所有关键调用点真正执行。
2. 默认测试路径和生产语义之间仍有明确距离。
3. 审计文档和指标体系还没有完全做到与代码状态同步演进。

下一阶段最值得优先做的三件事：

1. 先把关键状态推进链路做硬，别再把一致性寄希望于 scanner 和下次刷新。
2. 让高风险改动默认接受真实依赖验证，而不只靠 hermetic 套件。
3. 把技术审计、指标和代码状态真正收成一个闭环。
