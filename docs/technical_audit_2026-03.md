# 项目技术审计（2026-03）

最近更新：2026-03-18

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
- 本轮没有重新完整跑完全量 `pytest`
- 本轮没有重新在 `DJANGO_TEST_USE_ENV_SERVICES=1` 下跑完真实 MySQL / Redis / Channels / Celery 全套门禁

### 1.3 仓库规模快照

- 业务与配置目录下 Python 文件约 `667` 个
- migrations 文件约 `199` 个
- `tests/` 下测试文件约 `190` 个
- 代码中裸 `except Exception` 约 `262` 处
- 页面 view 入口中显式调用 `project_resource_production_for_read(manor)` 约 `17` 处

体量热点示例：

- 视图/服务：
  - `guests/views/recruit.py`：`573` 行
  - `gameplay/views/production.py`：`502` 行
  - `gameplay/views/jail.py`：`507` 行
  - `gameplay/views/missions.py`：`448` 行
  - `gameplay/services/buildings/forge.py`：`716` 行
  - `gameplay/services/recruitment/recruitment.py`：`710` 行
  - `gameplay/services/raid/scout.py`：`684` 行
  - `trade/services/auction/rounds.py`：`526` 行
  - `trade/services/market_service.py`：`406` 行
  - `battle/services.py`：`305` 行
- 模板/前端：
  - `guests/templates/guests/detail.html`：`1155` 行
  - `templates/landing.html`：`717` 行
  - `gameplay/templates/gameplay/warehouse.html`：`601` 行
  - `trade/templates/trade/partials/_market.html`：`488` 行
  - `static/js/chat_widget.js`：`603` 行
- 测试：
  - `tests/test_inventory_guest_items.py`：`974` 行
  - `tests/test_trade_auction_rounds.py`：`871` 行
  - `tests/test_trade_views.py`：`820` 行
  - `tests/conftest.py`：`244` 行

## 2. 总体判断

当前项目已经明显不是“个人练手级别”的小项目，功能覆盖和系统复杂度都很高；但工程治理、边界管理和验证体系没有同步提升到相同水平。

这轮扫描后的核心判断是：

1. 项目具备持续交付功能的能力，但复杂度控制已经开始落后于业务规模。
2. 最主要的问题不是“少功能”或“少测试”，而是边界持续塌陷，导致视图层、服务层、模型层、模板层都在增厚。
3. 项目依赖大量 best-effort 降级、锁补丁、状态字段和回退逻辑来维持可用性，这会继续抬高后续迭代成本。
4. 默认测试绿灯和 CI 绿灯，当前仍强于真实生产语义的保障能力。

结论一句话概括：

- 这是一个“明显有开发能力，但治理已经开始跟不上复杂度增长”的项目。

## 3. P1 问题

### P1-1 视图层和服务层边界持续坍塌，`gameplay` 已经接近超级 app

当前最明显的问题不是单个文件太长，而是很多热点入口同时承载了多种变化原因。

证据：

- `guests/views/recruit.py` 同时处理锁包装、缓存失效、AJAX 片段渲染、消息回传、异常映射和业务动作
- `gameplay/views/production.py` 同时处理锻造、分解、图纸合成、分页和页面状态装配
- `gameplay/views/missions.py` 在一个页面上下文里直接拉取 Mission、Guest、Troop、Item、SkillBook 多个域的数据
- `trade/views.py` 的钱庄护院存取仍直接调到 `gameplay.services.manor.troop_bank`
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
- 代码中仍有约 `17` 处页面 view 入口显式调用 `project_resource_production_for_read(manor)`
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
- `trade/services/market_purchase_helpers.py`、`guilds/services/member.py`、`guests/services/training.py` 等关键写路径大量依赖 `select_for_update`
- `core/utils/cache_lock.py`、`core/utils/rate_limit.py`、`core/utils/locked_actions.py` 各自承担不同种类的“轻锁”

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
- 调试并发问题时，需要同时理解 DB 锁、缓存锁、状态机、异步任务与补偿扫描

完成标准：

- 为数据库锁、缓存锁、状态锁、异步补偿分别定义职责
- 为关键链路建立统一的 fail-open / fail-closed 规则
- 将 battle / mission / raid / recruitment 的并发控制抽象到同一治理口径

### P1-4 默认测试门禁与生产语义差距仍然太大，真实外部服务覆盖偏薄

当前默认测试流明确不是生产语义门禁，但项目规模已经大到不能长期依赖这种默认。

证据：

- `Makefile` 明确写明 `make test` 只跑 hermetic 套件，不验证真实 `select_for_update`、Redis 语义和真实 Channels 语义
- `config/settings/testing.py` 默认改成 SQLite + LocMem + InMemoryChannelLayer + memory Celery
- `tests/conftest.py` 中对外部 DB / cache / channel layer / broker 探测失败时大量 `pytest.skip`
- 当前真正标记 `integration` 的测试文件只有：
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
- 本地 `make test-integration` 在环境未配好时偏向 `skip`，不是强失败

完成标准：

- 真实外部服务 gate 成为固定流程，而不是补充流程
- 本地 integration 环境缺失时要有更强的失败提示，而不是轻描淡写地跳过
- 扩大真实环境测试覆盖，不再只盯少数并发案例

### P1-5 类型检查仍在回避高风险区域，门禁强度不够

当前 mypy 配置更像“让 CI 可运行”，不是“让类型系统真正约束风险”。

证据：

- `pyproject.toml` 全局关闭 `disallow_untyped_defs`
- 关闭 `warn_return_any`
- 开启 `ignore_missing_imports`
- 对 `*.views`、`*.admin`、`*.management.commands.*`、`gameplay.models.*` 等高变更区域直接 `ignore_errors = true`

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

- 代码中裸 `except Exception` 约 `262` 处
- `common/utils/celery.py` 默认吞掉分发异常，只返回 `False`
- `config/asgi.py` 在 DEBUG 下可直接禁用 WebSocket routing 并继续启动
- `core/views/health.py`、`core/utils/task_monitoring.py`、`trade/services/cache_resilience.py` 大量使用 best-effort 路径
- `core/middleware/single_session.py` 在校验失败时允许保留已认证请求

具体落点：

- `common/utils/celery.py`
- `config/asgi.py`
- `core/views/health.py`
- `core/utils/task_monitoring.py`
- `trade/services/cache_resilience.py`
- `core/middleware/single_session.py`

风险：

- 问题更容易被延迟暴露，而不是尽早暴露
- 状态漂移、任务漏发、缓存不一致和安全策略退化更难追踪
- 代码阅读者很难判断每个降级策略的边界是否合理

完成标准：

- 将基础设施异常、业务异常、用户输入异常彻底分层
- 为关键链路定义哪些必须 fail-closed
- 把“降级策略”从分散写法升级成统一治理规则

## 4. P2 问题

### P2-1 热点模块继续增厚，God module 风险仍在累积

即使不把所有热点都称为 God module，目前也已经有一批高耦合文件处于危险区。

证据：

- `guests/views/recruit.py`：`573` 行
- `gameplay/views/production.py`：`502` 行
- `gameplay/views/jail.py`：`507` 行
- `gameplay/views/missions.py`：`448` 行
- `gameplay/services/buildings/forge.py`：`716` 行
- `gameplay/services/recruitment/recruitment.py`：`710` 行
- `gameplay/services/raid/scout.py`：`684` 行
- `trade/services/auction/rounds.py`：`526` 行
- `guests/models.py`：`490` 行
- `gameplay/models/manor.py`：`433` 行

风险：

- 单文件承载多条变化路径，任何局部重构都会被迫触碰太多上下文
- review 成本和回归成本持续增大
- 新问题更容易用 helper 和 wrapper 再包一层，而不是正面拆分

完成标准：

- 将热点模块按读写、配置、事务、渲染、通知、调度拆开
- 以“变化原因”而不是“文件太长”作为拆分标准

### P2-2 平台层和 facade 清理仍不彻底，概念数量偏多

这轮已经清掉了一层明显的伪边界，但“平台/包装层容易继续长出来”的风险还在。

本轮已完成：

- `trade/services/market_platform.py` 已删除
- `trade/services/market_service.py` 已改为直接绑定真实依赖，不再经由 `market_platform` 转发

仍然成立的问题：

- 项目整体仍存在“为了隔离而隔离”的命名层倾向
- 这类层次在 trade 清掉一层后，后续仍可能在其它热点链路继续反弹

当前落点：

- `trade/services/market_service.py`
- 其它热点 orchestrator / facade 风格模块

风险：

- 继续增加“名字像边界，实际只是转发”的中间层
- 让调用链更长，但不减少真实耦合
- 文档容易和代码再次漂移

完成标准：

- 只保留真正隔离外部依赖或跨域协议的 facade
- 删除只做转发或命名包装的平台层

### P2-3 模板和前端组织同样在增厚，不只是后端在积债

当前前端主要问题不是技术栈老旧，而是服务端模板和页面脚本都在持续变厚。

证据：

- `guests/templates/guests/detail.html`：`1155` 行
- `templates/landing.html`：`717` 行
- `gameplay/templates/gameplay/warehouse.html`：`601` 行
- `trade/templates/trade/partials/_market.html`：`488` 行
- `static/js/chat_widget.js`：`603` 行
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
- 前端重构成本会越来越像后端热点模块

完成标准：

- 将高复杂页面拆成更稳定的 partial / component 边界
- 将内联交互和页面状态逻辑从模板中抽离
- 降低基模板的“全局大杂烩”程度

### P2-4 测试资产很多，但结构治理一般，超大测试文件继续累积

测试数量多，不等于测试资产可维护。

证据：

- `tests/` 下测试文件约 `190` 个
- `tests/test_inventory_guest_items.py`：`974` 行
- `tests/test_trade_auction_rounds.py`：`871` 行
- `tests/test_trade_views.py`：`820` 行
- `tests/conftest.py`：`244` 行
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

### P2-5 coverage 配置仍在主动绕开部分高变更入口

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

### P2-6 文档漂移已经开始影响可信度，连审计文档本身都有过时结论

本轮扫描确认，文档层已经出现明显的结构漂移。

证据：

- `docs/architecture.md` 仍写“前端是 Django Templates + Bootstrap 5”，而当前前端实际以自定义 CSS + Tailwind 输出为主
- `docs/architecture.md` 仍大量使用 `settings.py`、`views.py`、`models.py`、`websocket/consumers.py` 这种单文件结构描述，但代码早已拆成包
- 本文件旧版本中对 `pytest.ini`、平台层删除状态、热点模块状态的描述已有部分过时，因此本轮已重写

具体落点：

- `docs/architecture.md`
- `README.md`
- `docs/technical_audit_2026-03.md`

风险：

- 新开发者会从错误的结构假设出发理解代码
- 文档越写越多，但和代码越走越远
- 审计文档如果不持续校正，会失去价值

完成标准：

- 先修正架构文档中的结构与栈描述
- 建立“架构文档必须跟随目录结构调整”的最小维护纪律

## 5. P3 问题

### P3-1 仓库中的生成资产和手写资产边界不够清晰

这不是最高优先级问题，但已经影响理解成本。

证据：

- `static/css/tailwind.css`：`125147` 字节
- `static/css/style.css`：`58914` 字节
- 大量页面样式同时存在于 Tailwind 产物和手写 CSS 中
- 文档层对前端栈的描述仍停留在旧模型

风险：

- 新样式究竟应该进 `src/input.css` 还是 `static/css/style.css`，约束不够清楚
- 生成物与源码边界不清，会进一步放大前端维护成本

完成标准：

- 明确前端样式来源约定
- 在开发文档中说明哪些文件是源码、哪些文件是构建产物

## 6. 建议执行顺序

### 第一阶段：先稳边界

1. 收口高复杂 view / selector / service 的职责边界
2. 明确 `gameplay` 与其它 app 的交互边界
3. 停止新增“只转发不隔离”的 platform / facade

### 第二阶段：再稳并发与测试

1. 为 battle / mission / raid / recruitment 梳理统一的并发控制口径
2. 扩大真实外部服务测试覆盖
3. 让 integration 缺环境时更明确失败，而不是大量 skip 掩盖

### 第三阶段：收紧门禁

1. 收缩 mypy 忽略范围
2. 重新评估 coverage 盲区
3. 降低广谱 `except Exception` 的使用频率

### 第四阶段：治理模板与文档

1. 拆分最大模板和页面脚本
2. 更新 `docs/architecture.md` 与 README 中的结构说明
3. 保持审计文档只记录当前事实，不保留历史胜利叙事

## 7. 跟踪表

| 编号 | 主题 | 优先级 | 当前状态 | 主要证据 |
| --- | --- | --- | --- | --- |
| P1-1 | 视图/服务边界坍塌 | P1 | 未解决 | `guests/views/recruit.py`、`gameplay/views/production.py`、`gameplay/views/missions.py` |
| P1-2 | 读路径资源投影仍分散 | P1 | 部分完成 | selector 已移除直接同步；view 入口仍约 `17` 处调用 `project_resource_production_for_read(...)` |
| P1-3 | 并发治理模型分散 | P1 | 未解决 | `battle/services.py`、`common/utils/celery.py`、`core/middleware/single_session.py` |
| P1-4 | 默认测试与生产语义偏离 | P1 | 未解决 | `Makefile`、`config/settings/testing.py`、`tests/conftest.py` |
| P1-5 | 类型门禁过弱 | P1 | 未解决 | `pyproject.toml` |
| P1-6 | 广谱吞异常与 fail-open | P1 | 未解决 | 裸 `except Exception` 约 `262` 处 |
| P2-1 | 热点文件持续增厚 | P2 | 未解决 | 多个 400-700 行热点模块 |
| P2-2 | 平台层清理仍需持续 | P2 | 部分完成 | `trade/services/market_service.py` 已脱离 `market_platform`，但同类伪边界风险仍存在 |
| P2-3 | 模板与前端增厚 | P2 | 未解决 | `detail.html`、`warehouse.html`、`_market.html`、`chat_widget.js` |
| P2-4 | 测试结构治理一般 | P2 | 未解决 | `tests/` 约 `190` 文件，超长测试文件持续存在 |
| P2-5 | coverage 仍有盲区 | P2 | 未解决 | `.coveragerc` |
| P2-6 | 文档漂移 | P2 | 未解决 | `docs/architecture.md`、README、旧版审计文档 |
| P3-1 | 前端构建资产边界不清 | P3 | 未解决 | `static/css/tailwind.css`、`static/css/style.css` |

## 8. 当前评分

综合评分：`6.2/10`

分项参考：

- 功能完成度：`8/10`
- 业务复杂度承载能力：`7.5/10`
- 架构治理：`5.5/10`
- 工程纪律：`5.5/10`
- 测试可信度：`6/10`
- 可维护性：`5.5/10`
- 文档可信度：`5/10`

当前最应该做的，不是继续加新抽象层，而是：

1. 把边界重新划清；
2. 把读写职责分开；
3. 把并发控制口径统一；
4. 把真实语义门禁立起来；
5. 把已经漂移的文档拉回代码现实。
