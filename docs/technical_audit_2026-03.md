# 项目技术审计（2026-03）

最近更新：2026-03-19（已按当前工作区重跑全量 pytest、目标 mypy，并校正文档事实）

本文档只记录 2026-03-18 这轮整仓扫描后仍成立的问题、风险和待跟踪项。历史上已经修复、或者本轮核对后确认不再成立的结论，已从正文移除，避免旧问题继续污染当前判断。

相关文档：

- [架构设计](architecture.md)
- [开发指南](development.md)
- [兼容入口清单](compatibility_inventory_2026-03.md)
- [数据流边界](domain_boundaries.md)

## 1. 审计范围与证据

### 1.1 本轮实际扫描范围

本轮覆盖了下列区域：

- 配置与基础设施：`config/`、`Makefile`、`.github/workflows/ci.yml`、`pyproject.toml`、`.coveragerc`
- 核心业务：`battle/`、`gameplay/`、`guests/`、`guilds/`、`trade/`
- 共用能力：`core/`、`common/`
- 实时与异步：`websocket/`、`tasks/`、Celery 调度封装
- 模板与静态资源：`templates/`、各 app `templates/`、`static/js/`、`static/css/`
- 测试体系：`tests/`、`tests/conftest.py`
- 文档：`README.md`、`docs/architecture.md`

### 1.2 本轮确认的事实

- `python scripts/check_import_cycles.py` 执行通过，结果为 `OK: no top-level import cycles detected.`
- `python -m pytest -q tests/test_settings_base.py tests/test_settings_testing.py tests/test_asgi.py tests/test_health.py` 执行通过，结果为 `30 passed in 5.72s`
- `python -m pytest -q tests/test_settings_base.py tests/test_single_session_middleware.py` 执行通过，结果为 `12 passed in 7.26s`
- `python -m pytest -q tests/test_websocket_session_guard.py tests/test_websocket_consumers.py` 执行通过，结果为 `17 passed in 6.52s`
- `python -m pytest -q tests/test_integration_service_guards.py` 执行通过，结果为 `7 passed in 0.05s`
- `python -m pytest -q tests/test_raid_scout_refresh.py tests/test_mission_views.py -k 'retreat_scout or scout_refresh'` 执行通过，结果为 `11 passed, 18 deselected in 8.51s`
- `pytest -q tests/test_message_views.py tests/test_map_views.py tests/test_trade_views.py tests/test_guest_view_error_boundaries.py tests/test_guest_item_view_validation.py` 执行通过，结果为 `133 passed in 47.33s`
- `pytest -q tests/test_notification_utils.py` 执行通过，结果为 `2 passed in 0.07s`
- `pytest -q tests/test_recruitment_views.py` 执行通过，结果为 `7 passed in 7.99s`
- `pytest -q` 于 2026-03-19 在当前工作区重新执行通过，结果为 `1633 passed, 9 skipped in 225.55s`
- `mypy core gameplay/views/core.py gameplay/views/inventory.py gameplay/views/jail.py gameplay/views/map.py gameplay/views/messages.py gameplay/views/missions.py gameplay/views/production.py gameplay/views/recruitment.py gameplay/views/technology.py gameplay/views/work.py trade/views.py guests/views/recruit.py` 执行通过，结果为 `Success: no issues found in 64 source files`
- 本轮没有重新在 `DJANGO_TEST_USE_ENV_SERVICES=1` 下跑完真实 MySQL / Redis / Channels / Celery 全套门禁
- 本轮追加定向扫描确认：
  - `gameplay` / `guests` / `trade` 热路径中 `transaction.atomic` 与 `select_for_update()` 命中约 `322` 处
  - `core` / `gameplay` / `guests` / `trade` / `websocket` / `accounts` 中裸 `except Exception` / `except:` 仍约 `210` 处
  - 页面 view 入口中通过 `prepare_manor_for_read(...)` 执行读侧资源投影约 `19` 处

### 1.3 仓库规模快照

- 业务与配置目录下 Python 文件约 `676` 个
- migrations 文件约 `199` 个
- `tests/` 下测试 Python 文件约 `194` 个
- 主业务/基础设施热点目录中裸 `except Exception` / `except:` 仍约 `210` 处
- 页面 view 入口中通过 `prepare_manor_for_read(...)` 执行读侧资源投影约 `19` 处
- `gameplay` / `guests` / `trade` 热路径中 `transaction.atomic` 与 `select_for_update()` 命中约 `322` 处

体量热点示例：

- 视图/服务：
  - `guests/views/recruit.py`：`466` 行
  - `gameplay/views/production.py`：`527` 行
  - `gameplay/views/jail.py`：`507` 行
  - `gameplay/views/missions.py`：`455` 行
  - `gameplay/services/buildings/forge.py`：`533` 行
  - `gameplay/services/recruitment/recruitment.py`：`591` 行
  - `gameplay/services/raid/scout.py`：`684` 行
  - `trade/services/auction/rounds.py`：`526` 行
  - `trade/services/market_service.py`：`467` 行
  - `battle/services.py`：`305` 行
- 模板/前端：
  - `guests/templates/guests/detail.html`：`1155` 行
  - `templates/landing.html`：`717` 行
  - `gameplay/templates/gameplay/warehouse.html`：`601` 行
  - `trade/templates/trade/partials/_market.html`：`485` 行
  - `static/js/chat_widget.js`：`603` 行
- 测试：
  - `tests/test_inventory_guest_items.py`：`974` 行
  - `tests/test_trade_auction_rounds.py`：`871` 行
  - `tests/test_trade_views.py`：`820` 行
  - `tests/conftest.py`：`266` 行

## 2. 总体判断

当前项目已经明显不是“个人练手级别”的小项目，功能覆盖和系统复杂度都很高；但工程治理、边界管理和验证体系没有同步提升到相同水平。

这轮扫描后的核心判断是：

1. 项目具备持续交付功能的能力，但复杂度控制已经开始落后于业务规模。
2. 最主要的问题不是“少功能”或“少测试”，而是边界持续塌陷，导致视图层、服务层、模型层、模板层都在增厚。
3. 项目依赖大量 best-effort 降级、锁补丁、状态字段和回退逻辑来维持可用性，这会继续抬高后续迭代成本。
4. 默认测试绿灯和 CI 绿灯，当前仍强于真实生产语义的保障能力。
5. 项目不是“没有工程意识”，而是工程意识主要体现在局部 hardening；一旦跨到分布式降级、异步调度失败和前端组织边界，治理强度就明显掉档。
6. 后续重构和修复必须强调全局意识，不能只在单点上“看起来更整洁”，却把复杂度、异常语义或降级责任转移到别处，形成“拆东墙补西墙”式优化。

结论一句话概括：

- 这是一个“明显有开发能力，但治理已经开始跟不上复杂度增长”的项目。

本轮额外强调：

- 审计不认可只改善局部观感、却恶化全局一致性的重构。
- 任何拆分、收敛、收窄异常、统一 helper 的改动，都必须同时检查调用链上下游、基础设施真实语义、降级策略和测试模型是否一起成立。
- 如果一个问题在 A 模块消失，却以另一种形式转移到 B 模块、跨模块边界或真实运行环境里，这不算修复，只算风险搬家。

执行要求：

1. 做局部重构时，必须同时回看同类调用点和同类基础设施依赖，确认不是只修一个入口。
2. 做异常收窄、缓存降级、锁策略调整时，必须对照真实后端异常类型和生产部署形态，而不是只对本地 mock 成立。
3. 新增的 helper、子模块和适配层，必须说明它消除了什么复杂度，不能只是把复杂度从一个大文件搬到多个薄包装里。
4. 审计结论优先看全局语义是否更稳，而不是单文件 diff 是否更好看。

## 2.1 后续优化的强制规则

以下规则不是建议，而是后续优化必须遵守的审计约束。任何违反这些规则的改动，即便局部 diff 更整洁，也应视为偏离优化目标。

### R1. 先定边界，再做拆分

- 禁止以“提取 helper / 子模块数量增加”作为重构完成标准。
- 拆分必须先回答清楚：这一层的职责是什么、输入输出是什么、它可以依赖谁、不能依赖谁。
- 优先按“业务动作 / 用例”组织模块，而不是按“工具函数类型”切碎文件。
- 如果主入口只是变成参数转发器、依赖注入集散地或兼容薄壳，这不算复杂度下降，只算复杂度搬家。

执行要求：

1. 重构前必须先写出目标边界：view、selector、service、infrastructure 各自负责什么。
2. 重构后必须能指出被消除的职责混杂点，而不是只展示文件拆分结果。
3. 对热点大模块，优先按“开始动作 / 完成动作 / 查询动作 / 补偿动作”分用例收口。

### R2. 先定错误语义，再谈统一异常处理

- 禁止继续把 `ValueError`、`RuntimeError`、裸 `Exception` 混合作为默认跨层语义。
- 必须明确区分三类错误：业务错误、基础设施错误、程序错误。
- view 层只负责映射异常到 HTTP / message / JSON，不负责猜测异常类别。
- service 层必须抛出语义明确的异常，不能把分类责任推给上层 helper。
- 禁止依赖字符串 marker 猜测未知异常是不是“基础设施问题”，除非这是临时兼容方案且有明确退役计划。

执行要求：

1. 新增统一异常映射前，先定义错误类型和允许的降级范围。
2. 业务错误必须可预期、可断言、可回归测试。
3. 程序错误必须直接暴露给测试与日志，不能伪装成“操作失败，请稍后重试”。

### R3. 读写职责必须分离

- selector 必须保持只读，不承担状态推进、副作用和补偿扫描。
- 页面渲染前如需读侧投影、缓存补偿、状态刷新，必须通过统一入口处理，不能让每个 view 自己拼一套降级语义。
- 不允许在页面请求热路径里继续扩散“读取前顺手推进状态”的隐式约定。
- 写操作必须由明确 service 入口承接，禁止在 template helper、selector、context builder 中偷偷推进业务状态。

执行要求：

1. 任何读路径副作用都必须有统一入口、统一日志和统一失败语义。
2. 页面层只能声明“需要的读模型”，不能各自决定“如何勉强读成功”。
3. 后续优化应逐步把 `prepare_manor_for_read(...)` 类能力继续上收，而不是继续在页面入口横向复制。

### R4. 基础设施故障策略必须平台统一

- 单会话、缓存、通知、在线状态、任务分发等基础设施故障，必须由统一策略决定 `fail-open` 还是 `fail-closed`。
- 禁止由单个业务模块私自决定全局故障语义。
- 涉及登录态、会话有效性、WebSocket 连接等链路时，默认必须优先评估可用性后果，不能把临时基础设施故障直接放大成全站用户侧事故。
- 任何“生产默认更严格”的策略变更，必须先证明不会把基础设施抖动升级为业务雪崩。

执行要求：

1. 后续所有基础设施降级规则必须在文档中集中声明。
2. HTTP 与 WebSocket 必须共用同一套会话可用性语义，避免通道间行为分裂。
3. 没有真实环境验证和回归测试前，不得把 fail-open 改成 production fail-closed。

### R5. 测试必须约束边界，而不只是追着补洞

- 后续重构不能只补“能跑过这次改动”的回归测试，必须补边界契约测试。
- 公开 service 入口、统一异常映射、统一读路径入口、基础设施降级策略，都必须有契约测试。
- 工作区全量测试不绿时，不应继续扩散重构范围。
- monkeypatch、兼容导出、模块路径等测试可达性本身也是工程契约，不能在重构后放任漂移。

执行要求：

1. 每次跨层重构至少补一类“错误语义 / 降级语义 / 模块边界”测试。
2. 全量 `pytest` 失败时，优先恢复绿灯，再继续新一轮结构优化。
3. integration / env-service 门禁应覆盖真实 cache / DB / channel layer / broker 语义，而不是只覆盖本地 mock。

### R6. 文档必须先于第二轮大拆分

- 在继续推进热点重构前，必须先固化模块边界、错误策略和基础设施降级规则。
- 没有边界文档和执行约束的“大拆分”，默认视为高风险操作。
- 优化计划必须服从审计结论；若计划与审计冲突，以审计为准，并同步修正文档。

执行要求：

1. 后续计划必须显式引用本节规则。
2. 每轮优化完成后，需要说明这轮改动符合了哪几条规则。
3. 如果某次改动只能作为临时兼容方案，必须写明退役条件和下一步收口点。

## 2.2 本轮根因判断

这轮复核后，审计认为当前高频问题的根因已经比“文件太大”或“异常太多”更清楚，主要集中在以下四点：

1. 系统仍未正式承认自己的边界：
   view、selector、service、infrastructure 之间的职责经常靠约定维持，一旦开始抽 helper 或子模块，就容易退化成“主入口转发 + 子模块回调拼装”。
2. 异常语义仍未形成正式契约：
   `ValueError`、`RuntimeError`、第三方基础设施异常和真实程序错误仍在多个入口混用，导致 view 层和包装层继续“猜这次炸的是哪一类错误”。
3. 基础设施策略仍然下沉到业务代码：
   单会话、缓存、通知、在线状态、异步 dispatch 等故障策略仍经常在业务模块里临时决定，而不是由统一的平台规则约束。
4. 测试仍以回归补洞为主，边界契约测试不足：
   这使得“代码能过测”并不等于“模块边界更清晰”或“错误语义更稳定”，很多问题只是暂时符合旧测试模型。

审计结论：

- 后续整改不能再把“拆文件”“抽 helper”“统一入口”本身当成结果。
- 真正需要建立的是：显式边界、显式异常类型、显式平台故障策略、显式契约测试。

## 3. P1 问题

### P1-1 视图层和服务层边界持续坍塌，`gameplay` 已经接近超级 app

当前最明显的问题不是单个文件太长，而是很多热点入口同时承载了多种变化原因。

证据：

- `guests/views/recruit.py` 同时处理锁包装、缓存失效、AJAX 片段渲染、消息回传、异常映射和业务动作
- `gameplay/views/production.py` 主文件已减薄，但 `production_page_context.py` 仍集中装配马房/畜牧/冶炼/锻造四类页面读模型，生产域入口族仍偏厚
- `gameplay/views/missions.py` 已把上下文与写动作下沉，但 `mission_page_context.py` 仍在一个入口聚合 Mission、Guest、Troop、Item、SkillBook、进行中 run、任务卡等多个域的数据
- `trade/page_context.py` 已接管交易页资源投影和页面装配，但 `trade/views.py` 的钱庄护院存取仍直接调到 `gameplay.services.manor.troop_bank`
- 热路径中的函数内 import 已显著减少，但跨域 page context / handler 仍承担较重 orchestration，说明边界治理还没有真正封板
- `gameplay/services/raid/scout.py` 在一个服务文件中同时承担领域判定、行锁、状态推进、任务分发、消息补偿和刷新兜底
- `gameplay/services/buildings/forge.py`、`gameplay/services/recruitment/recruitment.py`、`gameplay/services/raid/scout.py` 都已经是多职责聚合模块

具体落点：

- `guests/views/recruit.py`
- `gameplay/views/production.py`
- `gameplay/views/missions.py`
- `trade/views.py`
- `gameplay/services/buildings/forge.py`
- `gameplay/services/recruitment/recruitment.py`
- `gameplay/services/raid/scout.py`

风险：

- 入口层与应用层混在一起，导致任一功能微调都容易触发横向回归
- `gameplay` 正在扮演“总线层”，跨域依赖继续集中到一个 app
- 即便主文件变薄，复杂度仍可能转移到跨域 page context / handler 层，review 看到的 diff 面积会继续低估真实影响面
- 视图层继续兼任 orchestration 后，review 中看似“局部修改”的 diff，真实影响面往往跨多个 app
- 重构难度会继续上升，因为任何拆分都必须先穿透巨型 orchestrator

完成标准：

- view 只做请求解析、权限和响应装配
- selector / presenter 只做读侧装配
- service 成为明确的唯一写入口
- `gameplay` 不再承担其它 app 的默认协调层角色

### P1-2 读路径资源投影仍分散，页面读取和状态推进没有完全分离

这项问题在本轮有实质改善，但还没有完全收口。

证据：

- selector 中对 `sync_resource_production(manor, persist=False)` 的直接调用已移除
- 页面读侧资源投影已收敛到 `gameplay/views/read_helpers.py:prepare_manor_for_read(...)`
- `prepare_manor_for_read(...)` 在识别为“预期基础设施故障”时只记 warning 并继续页面渲染
- 代码中仍有约 `19` 处页面 view 入口通过该 helper 触发读侧资源投影
- 同类调用仍散落在 `home`、`map`、`inventory`、`missions`、`production`、`technology`、`trade`、`guests` 多个页面入口

具体落点：

- `gameplay/views/core.py`
- `gameplay/views/inventory.py`
- `gameplay/views/map.py`
- `trade/views.py`
- `guests/views/roster.py`
- `gameplay/views/missions.py`
- `gameplay/views/production.py`

风险：

- 页面读取前仍需显式执行资源状态投影，读路径纯度还不够高
- 页面渲染、副作用、缓存刷新耦合，后续性能优化和一致性分析会越来越难
- 同一个读操作在不同调用场景下可能产生不同业务影响
- 数据库轻微抖动时，用户仍可能拿到“页面能打开但状态是降级投影后的半旧数据”体验

完成标准：

- selector 变成真正的只读组件
- 资源刷新与状态推进由专门入口显式触发
- 页面请求不再悄悄承担业务推进职责

### P1-3 并发控制模型仍是“多种半方案叠加”，没有形成统一口径

项目对并发问题不是没处理，而是处理方式过于分散：数据库锁、缓存锁、状态字段、任务补偿、定时兜底同时存在，但缺少统一模型。

证据：

- `battle/services.py:lock_guests_for_battle` 先在事务内把门客状态标记为 `DEPLOYED`，退出事务后执行战斗，最后再开事务释放
- `common/utils/celery.py` 默认把任务分发视为 best-effort，失败后靠返回值和补偿路径兜底
- `core/middleware/single_session.py` 在单会话校验不可用时选择放行请求
- `accounts/utils.py` 的登录锁在 cache 不可用时会回退到进程内 `_LOCAL_LOGIN_LOCKS`，只对单进程有效
- `gameplay/services/raid/scout.py` 在侦察去程、返程和撤退返程的任务分发失败时，仍以日志 + 补偿路径兜底为主
- `gameplay/services/manor/refresh.py`、`gameplay/services/manor/core.py` 已把 `mission/scout/raid` 的到期工作纳入读侧刷新补偿，能缓解一部分异步 dispatch 失败后的状态漂移
- `trade/services/market_purchase_helpers.py`、`guilds/services/member.py`、`guests/services/training.py` 等关键写路径大量依赖 `select_for_update`
- `core/utils/cache_lock.py`、`core/utils/rate_limit.py`、`core/utils/locked_actions.py` 各自承担不同种类的“轻锁”
- `gameplay` / `guests` / `trade` 热路径里 `transaction.atomic` 与 `select_for_update()` 命中约 `322` 处，说明并发控制已经高度分散
- `gameplay/services/raid/scout.py` 自己就显式承认任务派发失败后可能停留在 outbound / returning 状态，系统正确性仍强依赖补偿

具体落点：

- `battle/services.py`
- `common/utils/celery.py`
- `core/middleware/single_session.py`
- `core/utils/cache_lock.py`
- `core/utils/locked_actions.py`
- `trade/services/market_purchase_helpers.py`
- `guilds/services/member.py`
- `guests/services/training.py`

风险：

- 不同链路对“锁失败时该 fail-open 还是 fail-closed”没有统一标准
- `Guest.status` 继续承担业务锁职责，仍然存在卡死与补偿复杂度
- 多进程 / 多实例部署下，部分“降级后仍可工作”的锁语义实际上已经从分布式约束退化成单进程自保
- 异步 dispatch 失败后的状态漂移虽然已有部分读侧自愈，但治理口径仍然分散，仍可能在低频链路中停留过久
- 调试并发问题时，需要同时理解 DB 锁、缓存锁、状态机、异步任务与补偿扫描
- 当前大量事务与行锁更像“到处补洞”，而不是围绕统一状态机或写模型建立的可解释约束

完成标准：

- 为数据库锁、缓存锁、状态锁、异步补偿分别定义职责
- 为关键链路建立统一的 fail-open / fail-closed 规则
- 将 battle / mission / raid / recruitment 的并发控制抽象到同一治理口径

### P1-4 默认测试门禁与生产语义差距仍然太大，真实外部服务覆盖偏薄

当前默认测试流明确不是生产语义门禁，但这项问题已有一部分治理动作落地。

证据：

- `Makefile` 明确写明 `make test` 只跑 hermetic 套件，不验证真实 `select_for_update`、Redis 语义和真实 Channels 语义
- `Makefile` 已提供固定双门禁入口 `make test-gates`，并在未设置 `DJANGO_TEST_USE_ENV_SERVICES=1` 时拒绝跳过真实服务 gate
- `config/settings/testing.py` 默认改成 SQLite + LocMem + InMemoryChannelLayer + memory Celery
- `tests/conftest.py` 现在会在“显式只跑 integration 测试但未开启 `DJANGO_TEST_USE_ENV_SERVICES=1`”时直接失败，而不是给出误导性的 skip
- `tests/conftest.py` 中对外部 DB / cache / channel layer / broker 探测失败时大量 `pytest.skip`
- 当前真正标记 `integration` 的测试文件包括：
  - `tests/test_integration_external_services.py`
  - `tests/test_health_integration.py`
  - `tests/test_raid_concurrency_integration.py`
  - `tests/test_work_service_concurrency.py`
- CI 虽然有 integration job，但覆盖面仍然明显小于项目复杂度

具体落点：

- `Makefile`
- `config/settings/testing.py`
- `tests/conftest.py`
- `.github/workflows/ci.yml`
- `tests/test_raid_concurrency_integration.py`
- `tests/test_work_service_concurrency.py`

风险：

- 默认测试全绿很容易被误读成“真实语义已验证”
- 并发、缓存、Broker、Channel Layer 相关问题会继续依赖线上或灰度环境暴露
- integration 覆盖面仍明显小于高风险写路径总量，现有真实服务 gate 还谈不上“充分”

完成标准：

- 真实外部服务 gate 成为固定流程，而不是补充流程
- 扩大真实环境测试覆盖，不再只盯少数并发案例

### P1-5 类型检查仍在回避高风险区域，门禁强度不够

当前 mypy 配置更像“让 CI 可运行”，不是“让类型系统真正约束风险”。

证据：

- `pyproject.toml` 全局关闭 `disallow_untyped_defs`
- 关闭 `warn_return_any`
- 开启 `ignore_missing_imports`
- 对 `*.views`、`*.admin`、`*.management.commands.*`、`gameplay.models.*` 等高变更区域直接 `ignore_errors = true`
- `core.views.health`、`gameplay.views.recruitment`、`gameplay.views.technology`、`gameplay.views.work` 之外，现已额外把 `gameplay.views.core`、`gameplay.views.inventory`、`gameplay.views.map`、`gameplay.views.messages`、`gameplay.views.missions`、`gameplay.views.production`、`gameplay.views.jail`、`trade.views`、`guests.views.recruit` 拉入真实 mypy 门禁
- 当前真正被强类型门禁覆盖的是少数 carve-out 模块，整体更像“局部试点”而不是“主路径约束”

具体落点：

- `pyproject.toml`

风险：

- 变更最频繁、最容易出入口错误的区域，恰恰被排除在类型门禁之外
- 项目规模变大后，这类“局部豁免”会越来越像永久豁免
- 类型系统在高风险区域提供不了足够的回归保护

完成标准：

- 收缩 `ignore_errors` 覆盖面
- 先把热点视图、关键服务和高复杂模型纳入硬门禁
- 将 mypy 从“文档性规则”升级为“真实阻断规则”

### P1-6 广谱吞异常和降级路径过多，系统在用“别炸”代替“可证明正确”

当前项目在基础设施、实时、任务、缓存、限流、登录、监控等多条链路上广泛使用 best-effort 降级。

证据：

- `core` / `gameplay` / `guests` / `trade` / `websocket` / `accounts` 中裸 `except Exception` / `except:` 仍约 `210` 处
- 本轮已先把 `gameplay/views/recruitment.py`、`gameplay/services/manor/refresh.py`、`guests/views/recruit.py`、`gameplay/selectors/recruitment.py`、`gameplay/selectors/home.py`、`gameplay/selectors/sidebar.py` 中的 `11` 处 broad `except Exception` 收缩为更具体的异常边界
- 本轮新增 `core/utils/infrastructure.py` 与 `core/utils/view_error_mapping.py`，先把基础设施异常分类和第一批 view 入口异常映射收口到统一 helper
- 已接入第一批 view 入口的高频路径包括 `trade/view_helpers.py`、`gameplay/views/messages.py`、`gameplay/views/map.py`、`guests/views/recruit.py`、`guests/views/common.py`
- `common/utils/celery.py` 默认吞掉分发异常，只返回 `False`
- `config/asgi.py` 在 DEBUG 下可直接禁用 WebSocket routing 并继续启动
- `core/views/health.py`、`core/utils/task_monitoring.py`、`trade/services/cache_resilience.py` 大量使用 best-effort 路径
- `core/middleware/single_session.py` 在校验失败时允许保留已认证请求
- `core/utils/infrastructure.py` 仍允许通过 `redis`、`timeout`、`channel layer` 等 runtime marker 猜测基础设施故障
- `core/utils/view_error_mapping.py` 默认已不再把 `ValueError` 视为业务错误，但 `LEGACY_VALUE_ERROR_VIEW_EXCEPTIONS` 仍在部分老入口维持兼容
- `core/utils/infrastructure.py` 已停止把整类 `RuntimeError` 纳入缓存基础设施异常集合，但仍允许通过 runtime marker 兼容识别历史 backend 错误文本
- `trade/view_helpers.py`、`guests/views/recruit.py` 等入口已经开始直接依赖 `classify_view_error(...)` 的分类结果；只要 legacy 兼容口径还在，错误包装就仍有扩散风险

具体落点：

- `common/utils/celery.py`
- `config/asgi.py`
- `core/views/health.py`
- `core/utils/task_monitoring.py`
- `trade/services/cache_resilience.py`
- `core/middleware/single_session.py`
- `core/utils/infrastructure.py`
- `core/utils/view_error_mapping.py`

风险：

- 问题更容易被延迟暴露，而不是尽早暴露
- 状态漂移、任务漏发、缓存不一致和安全策略退化更难追踪
- 代码阅读者很难判断每个降级策略的边界是否合理
- 如果只在局部把 `except` 写法改得更好看，却没有同步统一 HTML / JSON / 锁包装入口的异常映射，复杂度仍会以另一种形式回流到上层
- 如果 legacy 入口继续把 `ValueError` 视为业务错误，view 层仍会在一部分链路上继续“猜这次炸的是哪一类”
- 如果 runtime marker 兼容长期不退役，缓存/通知/在线状态仍可能对历史文本格式形成隐式耦合
- 如果新入口继续沿用 legacy 分类集合，而不是显式领域异常，很多实现错误仍可能被错误包装成 400 / 用户提示

完成标准：

- 将基础设施异常、业务异常、用户输入异常彻底分层
- 为关键链路定义哪些必须 fail-closed
- 把“降级策略”从分散写法升级成统一治理规则
- 先完成高频入口的小一统，再逐步替换第二梯队老入口，避免“大一统框架”反向制造新的耦合
- 逐步停止把 `ValueError` 作为跨层契约，建立显式的领域异常与基础设施异常类型
- 将第三方 cache / channel / broker / task 异常翻译收口到适配器层，停止在业务层和 view 层继续做 runtime marker 猜测

## 4. P2 问题

### P2-1 热点模块继续增厚，God module 风险仍在累积

即使不把所有热点都称为 God module，目前也已经有一批高耦合文件处于危险区。

证据：

- `guests/views/recruit.py`：`466` 行
- `gameplay/views/production.py`：`527` 行
- `gameplay/views/jail.py`：`507` 行
- `gameplay/views/missions.py`：`455` 行
- `gameplay/services/buildings/forge.py`：`533` 行
- `gameplay/services/recruitment/recruitment.py`：`591` 行
- `gameplay/services/raid/scout.py`：`684` 行
- `trade/services/auction/rounds.py`：`526` 行
- `guests/models.py`：`490` 行
- `gameplay/models/manor.py`：`433` 行
- `gameplay/services/buildings/forge.py` 虽已拆出 `forge_blueprints.py`、`forge_decompose.py`、`forge_runtime.py`，但主入口仍大量通过回调、`Any` 和参数转发来拼装流程

风险：

- 单文件承载多条变化路径，任何局部重构都会被迫触碰太多上下文
- review 成本和回归成本持续增大
- 新问题更容易用 helper 和 wrapper 再包一层，而不是正面拆分
- 如果继续按“工具函数类型”切文件，而不是按“业务动作”收口，热点模块会从 God file 退化成 God orchestrator

完成标准：

- 将热点模块按读写、配置、事务、渲染、通知、调度拆开
- 以“变化原因”而不是“文件太长”作为拆分标准
- 对 `forge`、`raid` 这类热点服务，优先按图纸合成 / 装备分解 / 开始锻造 / 完成锻造、或去程 / 返程 / 撤退 / 补偿等业务动作收口，而不是继续增加 callback 式薄包装层

### P2-2 模板和前端组织同样在增厚，不只是后端在积债

当前前端主要问题不是技术栈老旧，而是服务端模板和页面脚本都在持续变厚。

证据：

- `guests/templates/guests/detail.html`：`1155` 行
- `templates/landing.html`：`717` 行
- `gameplay/templates/gameplay/warehouse.html`：`601` 行
- `trade/templates/trade/partials/_market.html`：`485` 行
- `static/js/chat_widget.js`：`603` 行
- `guests/templates/guests/detail.html` 仍内嵌大段页面样式
- `package.json` 仅提供 Tailwind CSS 构建脚本，没有 ESLint、前端单测或 E2E 门禁
- `templates/base.html` 同时承载导航、消息、在线状态、聊天组件和脚本装配
- `trade/templates/trade/partials/_market.html` 里存在内联 `onclick` 导航切换

具体落点：

- `templates/base.html`
- `templates/landing.html`
- `guests/templates/guests/detail.html`
- `gameplay/templates/gameplay/warehouse.html`
- `trade/templates/trade/partials/_market.html`
- `static/js/chat_widget.js`

风险：

- 模板层缺少清晰的组件边界
- 页面逻辑继续在 HTML 与 JS 间分散增长
- 前端回归主要靠人工目测和后端联调时顺手发现，缺少独立工程门禁
- 前端重构成本会越来越像后端热点模块

完成标准：

- 将高复杂页面拆成更稳定的 partial / component 边界
- 将内联交互和页面状态逻辑从模板中抽离
- 降低基模板的“全局大杂烩”程度

### P2-3 测试资产很多，但结构治理一般，超大测试文件继续累积

测试数量多，不等于测试资产可维护。

证据：

- `tests/` 下测试 Python 文件约 `194` 个
- `tests/test_inventory_guest_items.py`：`974` 行
- `tests/test_trade_auction_rounds.py`：`871` 行
- `tests/test_trade_views.py`：`820` 行
- `tests/conftest.py`：`266` 行
- 测试里 `monkeypatch` / `Mock` / `patch` 搜索命中接近 `1947` 次

当前已确认不是问题的点：

- `pytest.ini` 已经配置 `testpaths = tests`

仍然成立的问题：

- 超长测试文件说明很多测试仍是持续补洞，而不是按领域重构
- `tests/conftest.py` 已经承担相当多环境切换和共享设施职责
- 测试代码本身也在累积复杂度

完成标准：

- 继续按业务域拆分超长测试文件
- 将工厂、fixture、builder 再下沉，降低单文件体积
- 为 integration 与 hermetic 两条测试道建立更清晰的目录和职责边界

### P2-4 coverage 配置仍在主动绕开部分高变更入口

当前 coverage 配置已经比很多项目好，但仍有几个长期盲区。

证据：

- `.coveragerc` 直接忽略了：
  - `*/templatetags/*`
  - `*/tests/*`
  - `tests/*`
  - `manage.py`
- `management/commands` 没有被忽略，但 `templatetags` 这类实际入口被长期排除

具体落点：

- `.coveragerc`

风险：

- 覆盖率数字比真实入口保障更好看
- 模板过滤器与部分边界层逻辑容易长期无压

完成标准：

- 重新评估 coverage 盲区是否仍合理
- 关键入口不要因历史方便被永久排除

## 5. 建议执行顺序

### 第一阶段：先稳边界

1. 先选 `trade/views.py`、`gameplay/views/production.py`、`gameplay/views/missions.py` 三个热点入口，拆出只读 context builder 与独立写动作入口
2. 清理这些热点入口中的函数内 import，明确 `gameplay` 与其它 app 的交互边界，禁止继续把动态 import 当边界工具
3. 明确页面层允许依赖的对象类型，避免 view 再继续兼任 orchestrator
4. 对 `forge`、`raid` 这种已开始拆分但仍高度耦合的服务，停止继续做 callback 式拆分，改按业务动作重组模块

第一阶段封板结论（`2026-03-19`）：

1. 热点入口样板已落地：`trade/views.py`、`gameplay/views/production.py`、`gameplay/views/missions.py` 已拆出只读 context builder；`guests/views/recruit.py`、`gameplay/views/mission_action_handlers.py`、`gameplay/views/production_forge_handlers.py` 已完成第一层写动作收口。
2. 热点链路中的“把运行时 import 当边界工具”已显著收缩：`trade`、`production`、`missions`、`recruit`、`forge`、`raid/scout` 这几条第一阶段主链路里，原先最重的热路径动态 import 和 importer 壳已基本清掉，只保留少数用于打破循环依赖的延迟导入。
3. `forge`、`raid/scout` 已停止继续做 callback 式空转拆分：`forge_runtime.py`、`forge_blueprints.py`、`forge_decompose.py`、`gameplay/services/raid/scout.py`、`gameplay/services/raid/combat/*` 已按业务动作重组，`run_wiring.py` 这类纯依赖打包层已删除。
4. 第一阶段到此视为完成，但不等于 P1 全部问题已根治：统一写模型、真实外部服务测试、显式异常层次、类型门禁等仍属第二阶段及以后要继续推进的工作。

### 第二阶段：再稳并发与测试

1. 为 mission / raid / recruitment 先定义统一写模型：谁负责加锁、谁负责状态推进、谁负责异步补偿、谁负责最终一致性
2. 优先为 `select_for_update`、cache lock、Channels、Celery dispatch 补真实外部服务测试，不再只覆盖少数并发样例
3. 停止继续在读路径里补偿异步失败；确需补偿时，必须先声明补偿边界和退役条件

### 第三阶段：收紧门禁

1. 先建立显式异常层次：领域异常、基础设施异常、程序错误，停止把 `ValueError` 当默认跨层语义
2. 将 cache / channel / task / broker 的第三方异常翻译收口到适配器层，停止在 view / service 层继续做 runtime marker 猜测
3. 收缩 broad `except Exception`，先从 `trade`、`raid`、`websocket` 这几条高频链路开始
4. 收缩 mypy 忽略范围，重新评估 coverage 盲区，让门禁真正覆盖高变更入口

### 第四阶段：治理模板与文档

1. 在后端边界稳定后，再拆最大模板和页面脚本，避免前端拆分反向固化错误后端边界
2. 保持 `docs/architecture.md`、README 与审计文件持续跟随真实目录结构与运行语义
3. 保持审计文档只记录当前事实，不保留历史胜利叙事

## 6. 跟踪表

| 编号 | 主题 | 优先级 | 当前状态 | 主要证据 |
| --- | --- | --- | --- | --- |
| P1-1 | 视图/服务边界坍塌 | P1 | 部分完成 | 第一阶段热点入口已完成样板收口：`trade/views.py`、`gameplay/views/production.py`、`gameplay/views/missions.py`、`guests/views/recruit.py`、`gameplay/services/raid/combat/*`、`gameplay/services/buildings/forge*.py`；项目级边界治理仍待第二阶段继续 |
| P1-2 | 读路径资源投影仍分散 | P1 | 部分完成 | `trade/page_context.py`、`gameplay/views/production_page_context.py`、`gameplay/views/mission_page_context.py` 已完成热点读侧装配；项目范围仍存在多处 `prepare_manor_for_read(...)` |
| P1-3 | 并发治理模型分散 | P1 | 部分完成 | `guests/views/recruit_action_runtime.py`、`gameplay/views/mission_action_handlers.py`、`gameplay/views/map.py`、`gameplay/services/raid/scout.py` 已收敛局部锁/调度边界；统一写模型仍待第二阶段定义 |
| P1-4 | 默认测试与生产语义偏离 | P1 | 部分完成 | `Makefile`、`config/settings/testing.py`、`tests/conftest.py` |
| P1-5 | 类型门禁过弱 | P1 | 部分完成 | `pyproject.toml`、`gameplay/views/core.py`、`gameplay/views/inventory.py`、`gameplay/views/map.py`、`gameplay/views/messages.py`、`gameplay/views/missions.py`、`gameplay/views/production.py`、`gameplay/views/jail.py`、`trade/views.py`、`guests/views/recruit.py` |
| P1-6 | 广谱吞异常与 fail-open | P1 | 部分完成 | 第一阶段主链路中的典型 `fail-open` 已收缩，如 `gameplay/services/buildings/forge.py`、`gameplay/services/raid/scout.py`；项目范围裸 `except Exception` / `except:` 仍较多，异常层次仍待第三阶段 |
| P2-1 | 热点文件持续增厚 | P2 | 未解决 | 多个 400-700 行热点模块 |
| P2-2 | 模板与前端增厚 | P2 | 未解决 | `detail.html`、`warehouse.html`、`_market.html`、`chat_widget.js` |
| P2-3 | 测试结构治理一般 | P2 | 未解决 | `tests/` 约 `194` 个 Python 文件，超长测试文件持续存在 |
| P2-4 | coverage 仍有盲区 | P2 | 未解决 | `.coveragerc` |

## 7. 当前评分

综合评分：`6.2/10`

分项参考：

- 功能完成度：`8/10`
- 业务复杂度承载能力：`6.6/10`
- 架构治理：`4.5/10`
- 工程纪律：`5.8/10`
- 测试可信度：`6.2/10`
- 可维护性：`5.5/10`
- 文档可信度：`6/10`

当前最应该做的，不是继续加新抽象层，而是：

1. 把边界重新划清；
2. 把读写职责分开；
3. 把并发控制口径统一；
4. 把真实语义门禁立起来；
5. 把已经漂移的文档拉回代码现实。
