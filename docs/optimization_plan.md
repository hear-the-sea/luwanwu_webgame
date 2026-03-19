# 项目全方位优化计划

本文档给出 `web_game_v5` 的分阶段优化路线，并标记首批已落地项。

## 2026-03-19 审计对齐说明

自 2026-03-19 起，本计划必须服从 [技术审计](technical_audit_2026-03.md) 第 `2.1` 节“后续优化的强制规则”。

执行约束：

1. 不再以“抽 helper / 拆子模块数量”作为重构完成标准，必须证明职责边界更清晰。
2. 所有统一异常处理、统一读路径、统一降级策略改动，必须先定义错误语义和 fail-open / fail-closed 口径。
3. 页面读路径、副作用补偿、基础设施降级，不允许继续在 view 层横向复制。
4. 工作区全量测试不绿时，优先恢复绿灯，不继续扩散重构范围。
5. 若本计划与审计结论冲突，以审计为准，并同步修正文档。

## 2026-03-09 当前执行面

## 2026-03-18 新增执行批次

### 本批目标

- 收口页面读路径中的资源投影入口，停止每个 view 自己定义一套降级语义。
- 将单会话校验 unavailable 时的策略显式配置化，并与平台级故障策略统一评估。
- 提高真实外部服务门禁的可发现性，让 skip/fail 消息直接给出执行命令。

### 本批执行顺序

1. 新增统一的页面读路径 helper，并替换核心页面调用点。
2. 新增 `SINGLE_SESSION_FAIL_OPEN` 配置，HTTP / WebSocket 共用同一策略。
3. 为单会话策略、测试门禁提示和平台级故障语义补回归测试。

### 本批已完成

- 页面资源读路径开始收敛到统一 helper，减少 view 层散落的 ad-hoc `try/except`。
- 单会话校验 unavailable 时支持显式 fail-open / fail-closed；基础配置现已改为默认 fail-closed，需要更宽松策略时必须显式打开。
- integration gate 的 skip / fail 消息补上了直接可执行的本地命令提示。
- `gameplay/services/buildings/forge.py` 已继续下沉：蓝图合成、装备分解、运行期锻造流程拆入独立子模块，`forge.py` 保留缓存、配置与兼容出口。
- `get_recruitment_equipment_keys()` 的导入异常已从广谱吞异常收窄为 `ImportError`。

### 本轮目标

- 先做低风险、可回归、能持续削减复杂度的收敛工作。
- 每轮只推进一个可验证的小主题，避免“大爆炸式重构”。
- 每完成一个主题，都要求补文档、补测试、补最小验证命令。
- 所有后续重构都必须证明边界更清晰、错误语义更稳定，而不是仅仅把复杂度分散到更多文件。

### 执行顺序

1. 模板加载工具收敛：合并重复 helper，减少查询工具分叉。
2. `battle/views.py` / `gameplay/views/production.py` 上下文拼装下沉到 selector/helper。
3. 拆分 `guests/services/recruitment.py` 为缓存、抽取、落库、通知四层。
4. 拆分 `gameplay/services/buildings/forge.py` 为配置、蓝图、分解、排程四层。
5. 收缩 `gameplay/services/__init__.py` 兼容出口，限制新增代码继续从聚合层导入。

### 本轮已完成的收敛项

- `gameplay/utils/template_loader.py` 已向 `core/utils/template_loader.py` 收敛，保留兼容 API，减少重复查询实现。
- `battle/view_helpers.py` 已抽离战报视图中的展示辅助逻辑，并合并掉落/损失标签查询。
- `gameplay/views/production_helpers.py` 已抽离锻造页分类、排序、图纸标注等纯逻辑。
- `guests/services/recruitment_templates.py` 已抽离招募模板缓存、稀有度搜索与模板选择逻辑。
- `gameplay/services/buildings/forge_config_helpers.py` 已抽离铁匠铺配置归一化逻辑。
- `gameplay/services/arena/helpers.py` 已抽离竞技场纯计算与轮次辅助逻辑。
- `gameplay/services/arena/snapshots.py` 已抽离竞技场报名快照构建与快照代理逻辑。
- `trade` 高频写链路已开始退出 legacy `ValueError` 兼容：`TradeValidationError` 已接入交易行/钱庄/拍卖/钱庄护院主链路，`trade/view_helpers.py` 已停止把裸 `ValueError` 视为已知业务错误。
- `gameplay/services/resources.py` 已把 `spend_resources_locked()` 的“资源不足”从字符串契约升级为显式资源异常，`trade/shop/technology/arena/buildings` 等直接调用点已同步改为按异常类型收口，而不是继续猜 `"资源不足"` 文本。
- 本轮额外补了错误语义契约测试：覆盖 `trade` 视图对业务异常 / 基础设施异常 / 裸 `ValueError` 的区分，以及资源服务显式异常的回归。

### 2026-03-19 异常语义收口说明

本批改动对应审计规则 `R2`、`R5` 的局部推进，不代表 `P1-6` 已整体封板。

本批已满足：

1. `trade` 高频入口的业务错误、基础设施错误、程序错误边界比改动前更清晰，view 不再继续依赖 legacy `ValueError` 集合作为默认业务契约。
2. 公开 service 入口与 view 映射已经补了边界契约测试，能明确断言哪些错误会被映射为用户提示，哪些错误必须继续上抛。
3. `arena` 链路已完成一轮同类收口：报名、撤销、兑换、门客选择等 service/helper 不再默认抛裸 `ValueError`，而是改为显式 `Arena*Error` / 资源异常；`gameplay/views/arena.py` 已同步改成按领域异常映射。
4. 针对异常迁移的残留兼容点已补尾：`ItemNotFoundError` 已补回 `loot box` 奖励和 `battle salvage` 装备回收的显式容错分支，`arena` 兑换数量归一化也已补上非法输入契约，避免新旧异常语义混用造成回归。

本批仍未完成：

1. 项目范围内仍有大量老链路继续使用 `ValueError` 作为跨层业务语义，不能把这轮结果表述成“审计要求已全部满足”。
2. `core/utils/view_error_mapping.py` 的 legacy 兼容集合仍在其它入口存活，后续要继续按高频链路逐步退役。
3. `production`、`mission`、`recruit`、`jail` 等入口仍有 `GameError + ValueError` 混用，下一轮应继续优先处理高频 view/service 主链路。

## 目标

- 降低核心模块复杂度，减少大文件和兼容层长期膨胀。
- 提升可观测性，让线上问题能快速定位到请求、任务、模块。
- 继续强化类型、测试、配置校验，降低回归成本。
- 在不打断现有业务迭代的前提下，逐步推进重构。

## 阶段 1：低风险高收益（本轮优先）

- 日志链路补全：为应用日志统一接入 `request_id`，访问日志独立配置。
- 视图解耦：将任务视图中的纯辅助逻辑拆出，降低单文件职责密度。
- 回归测试：为日志配置、任务辅助函数补充轻量测试。
- 文档沉淀：把优化目标和顺序固化为可执行清单。
- 工具收敛：减少同类 helper 的重复实现，优先统一模板加载、缓存 key、轻量通用查询工具。

### 阶段 1 封板结果（`2026-03-19`）

- 热点入口边界已完成一轮系统收口：`trade`、`production`、`missions` 已拆出只读 page context，`recruit`、`mission`、`forge` 的写动作入口已下沉为独立 handler/runtime。
- `forge` 与 `raid/scout` 已从“callback/bundle 空转拆分”转向按业务动作组织模块，`run_wiring.py` 已删除，`forge_runtime.py`、`recruit_action_runtime.py` 等职责边界已固定。
- 页面读路径已继续上收：`trade/page_context.py`、`gameplay/views/*` 主要页面入口、`guests/views/roster.py` 已统一改走 `get_prepared_manor_for_read(...)` 请求级 helper，页面层不再重复拼装“取 manor + 读侧投影 + 降级语义”样板。
- 默认测试/覆盖率门禁已补齐一轮可信度缺口：`pytest.ini` 现已覆盖 `guests/tests/`，`.coveragerc` 不再长期排除 `templatetags`，相关契约测试已补齐。
- 第一批 `guests` 侧稳定入口已退出 `*.views.*` 的 mypy 总豁免：`guests.views.recruit_runtime`、`guests.views.recruit_responses` 已进入真实类型门禁，当前门禁命令已可通过。
- 第一阶段的目标已视为完成，后续不再继续在这一阶段追加大纵深重构；剩余统一写模型、异常层次、真实外部服务测试等工作，转入第二阶段及以后继续推进。

### 本轮已完成

- `config/settings/logging_conf.py`：接入 `RequestIDFilter`，并为 `access` logger 配置独立 handler。
- `gameplay/views/mission_helpers.py`：抽离任务视图辅助逻辑。
- `gameplay/views/missions.py`：改为消费 helper，降低文件复杂度。
- `tests/test_logging_configuration.py`：新增日志配置回归测试。
- `tests/test_mission_helper_functions.py`：新增任务辅助函数回归测试。
- `trade/page_context.py`、`gameplay/views/production_page_context.py`、`gameplay/views/mission_page_context.py`：热点页面读侧装配已统一下沉。
- `guests/views/recruit_action_runtime.py`、`gameplay/views/mission_action_handlers.py`、`gameplay/views/production_forge_handlers.py`：热点写动作入口已从 view 主文件下沉。
- `gameplay/services/buildings/forge_runtime.py`、`gameplay/services/raid/scout.py`、`gameplay/services/raid/combat/*`：第一阶段主链路中的 callback/importer/bundle 空转层已明显收缩。
- `gameplay/services/raid/combat/travel.py`：补齐防守保护态 helper 的时间参数标注后，`guests.views.recruit_runtime` / `guests.views.recruit_responses` 的新增 mypy 门禁已解除阻塞。
- `gameplay/views/read_helpers.py`、`gameplay/views/core.py`、`gameplay/views/map.py`、`gameplay/services/raid/combat/runs.py`：`raid/scout` 读前刷新已开始通过显式 helper 触发，`get_active_raids()` 不再偷偷承担补偿刷新职责。

### 本轮新增启动项

- `gameplay/utils/template_loader.py`：开始收敛到 `core/utils/template_loader.py` 的统一实现。
- `battle/views.py`：开始向 `battle/view_helpers.py` 下沉展示辅助逻辑。
- `gameplay/views/production.py`：开始向 `gameplay/views/production_helpers.py` 下沉纯上下文拼装逻辑。
- `guests/services/recruitment.py`：开始拆分模板缓存与模板选择逻辑。
- `gameplay/services/buildings/forge.py`：开始拆分配置归一化逻辑。
- `gameplay/services/arena/core.py`：开始拆分纯 helper 与报名快照逻辑。

## 阶段 2：并发与测试基线

- 以 [第二阶段统一写模型基线](write_model_boundaries.md) 作为本阶段前置约束，先固化 `mission / raid / guest recruitment` 的主写入口、after-commit follow-up 和 refresh command 边界。
- 为 `select_for_update`、请求级锁、任务派发与补偿刷新补真实外部服务测试，不再只依赖 hermetic 套件和局部 mock。
- 继续把 `raid/scout`、`mission`、`guest recruitment` 的补偿职责从页面读路径外迁，禁止新增“读取前顺手修状态”的入口。
- 第二阶段完成标准不再是“又拆出几个 helper”，而是写路径的正确性来源、补偿边界和真实门禁都变得可说明、可测试。

### 第二阶段当前进展（`2026-03-19`）

- `raid/scout` 读侧已经完成一轮显式化：`HomeView`、`MapView`、`raid_status_api` 会在列出活动状态前显式调用统一 helper；`get_active_raids()` 已退回纯读 accessor。
- `arena` 报名/赛事/兑换/详情页已接入统一的 `get_prepared_manor_for_read(...)` 入口，页面 selector 不再各自决定资源读侧投影触发时机。
- 这轮改动对应审计规则 `R3`、`R5` 的局部推进：副作用不再藏在 accessor 里，并已补入口契约测试。
- 第二阶段仍未封板：页面读路径仍然存在显式补偿调用，真实 MySQL / Redis / Channels / Celery gate 也还没有补齐。

## 阶段 3：类型与边界治理

- 逐步缩小 `pyproject.toml` 中 mypy 的 `ignore_errors` 范围。
- 优先覆盖 selector、service、utility 层，再逐步推进到 views。
- 约束新模块必须带类型标注，避免继续产生新的类型盲区。
- 建立显式异常分层，逐步减少跨层泛用 `ValueError` / `RuntimeError` / 裸 `Exception`。
- 为 view / selector / service / infrastructure 建立可测试的职责边界。

## 阶段 4：性能与数据一致性

- 为关键页面增加查询次数基线测试，重点覆盖任务、仓库、交易、竞技场。
- 统一高频缓存 key、TTL 和失效策略，减少隐式缓存分叉。
- 继续梳理 Celery 任务的“吞异常但兜底扫描”模式，补 metrics/告警。
- 统一基础设施故障的 fail-open / fail-closed 口径，禁止各模块各自定义全局策略。

## 阶段 5：测试与发布质量

- 将超大测试文件按业务域拆分，例如 `tests/test_views.py`。
- 增加并发行为回归用例，覆盖锁、库存、撤退、报名等关键路径。
- 为 YAML 配置加载继续补 schema 化校验与负例测试。
- 为统一异常映射、统一读路径入口、基础设施降级策略补边界契约测试。
- 保持全量 `pytest` 绿灯，红灯时先收口再继续结构改造。

## 阶段 6：迁移与运维治理

- 评估 `gameplay`、`guests` 的历史 migration，择机进行 squash。
- 增加结构化日志、关键任务监控和失败告警。
- 完善运行手册，形成开发 / 测试 / 上线统一流程。
