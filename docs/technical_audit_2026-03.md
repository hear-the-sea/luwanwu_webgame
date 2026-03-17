# 项目技术审计与优化清单（2026-03）

本文档只保留当前仍成立的问题、缺口和待跟踪项。已经完成并有代码/测试证据支撑的优化、重构和历史问题，均已从正文删除，不再混入当前审计结论。

最近更新：2026-03-18（第六十一批校正文档：本轮继续将 `market_service.py` 的挂单/购买/取消/过期/查询依赖装配下沉到独立 facade，市场链路定向回归继续通过；当前文档只保留仍未完成的问题、缺口和待跟踪项）

相关文档：

- [优化计划](optimization_plan.md)
- [架构设计](architecture.md)
- [开发指南](development.md)
- [兼容入口清单](compatibility_inventory_2026-03.md)

## 1. 当前有效证据

当前仍有效、且可作为结论依据的验证结果只有这些：

- 全量 `flake8` 通过：`python -m flake8 --jobs=1 accounts battle gameplay guests guilds trade core websocket config tests`
- 默认非集成测试通过：`python -m pytest -q -m "not integration"`，结果为 `1559 passed, 9 deselected`
- Django 基础检查通过：`python manage.py check`
- deploy 检查可执行完成：`DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS=localhost DJANGO_SECRET_KEY=test-secret-key REDIS_PASSWORD=ci-test-dummy python manage.py check --deploy`
- 本轮 `market` 定向验证通过：`python -m pytest tests/test_market_service.py tests/test_market_notification_helpers.py tests/test_market_purchase_helpers.py tests/test_trade_market_rules_loader.py -q`
- 本轮 `trade` 真实市场流程回归通过：`python -m pytest tests/test_trade.py -k "listing or market or purchase or cancel" -q`
- 多轮 targeted `pytest` / `flake8` / `mypy` 已覆盖本轮拆分热点，但这些只证明当前拆分未打破默认环境下的语义，不等于真实外部服务语义已全部验证

当前无法宣称已闭环的部分：

- `tests/test_integration_external_services.py` 虽然已经补上 `mission` / `guild` 链路，但尚未在 `DJANGO_TEST_USE_ENV_SERVICES=1` 的真实 MySQL / Redis / Channels / Celery 环境下执行确认
- `mypy` 仍不是全项目高信噪比硬门禁，核心区域仍有豁免残留

## 2. 当前状态判断

整体上，项目已经脱离最危险阶段：高频事故项、明显的事务一致性问题、若干伪 facade 和跨域直连已经被实质收口。

当前真正剩下的，不再是“哪里还有明显 P0 bug”，而是两类结构性问题：

1. 少量跨 app 边界和 `Guest` 相关玩法规则仍未彻底收口，存在复杂度回潮风险。
2. 默认门禁虽然全绿，但真实外部服务语义的集成门禁还没有完全跑通。

## 3. 剩余高优先级问题

### P1-3 cross-app 边界仍有残留耦合

重点区域：

- `guests/models.py`
- `trade/services/market_commands.py`
- `trade/services/market_platform.py`
- `guests/services/recruitment*`
- `guilds/services/*`

当前剩余缺口：

- `Guest` 模型虽然已经迁出大量战斗、成长、工资、回血规则，但仍有少量玩法兼容属性/包装行为残留，需要继续外迁
- `trade` 域的 `market_service.py` 已进一步收薄到 facade 级，但 `market_commands.py`、`market_platform.py` 与其周边装配点仍需防止后续逻辑重新长回跨层直连
- `guests` 域的 `guests/models.py` 与 `guests/services/recruitment*.py` 一带仍保留较多规则与兼容包装，后续需求仍有回流风险
- `guilds` 域虽然已有 `guild_platform.py` / `member_notifications.py`，但仍需持续约束边界，不让消息、资源、公告逻辑重新耦回 `gameplay`

完成标准：

- `Guest` 不再承担高变化率玩法规则和跨域编排
- `trade` / `guilds` 的热点服务只通过窄接口协作，不再深入别的 app 内部实现
- 新增功能优先挂在显式规则模块或平台边界，而不是继续回填到 model / 大服务文件

### P1-4 门禁重构仍未真正闭环

现状：

- 默认 `flake8` 和默认非集成 `pytest` 已恢复全绿。
- 代码里已经补了更多 integration 用例，但“写了 integration 测试”和“真实外部服务下跑通”不是一回事。

当前剩余缺口：

- `mission` / `raid` / `trade` / `guild` 的关键链路还缺统一、稳定的真实外部服务门禁执行记录
- `mypy` 仍有豁免区域，离“核心服务层受类型约束”还有距离
- hermetic 测试与真实语义测试的职责边界虽然在文档和实现上开始分离，但还没有完全固化到团队默认工作流

完成标准：

- 在真实 MySQL / Redis / Channels / Celery 环境下跑通关键 integration 测试
- 继续缩减 `pyproject.toml` 中的 `ignore_errors`
- CI / Makefile 中明确区分默认测试、关键 integration、lint、mypy 的职责

## 4. P2：热点模块复杂度仍需继续压缩

当前仍需持续收口的热点文件：

- `guests/models.py`
- `guests/services/recruitment*.py`
- `trade/services/market_commands.py`
- `trade/services/market_platform.py`

问题不在于“文件行数大”，而在于这些文件仍同时承载规则、状态推进、副作用和请求/UI 编排，后续需求一旦继续堆进去，复杂度会很快反弹。当前仍最值得继续压的，主要是 `guests/models.py` 的兼容属性与规则残留、`guests/services/recruitment*.py` 的规则收口，以及 `trade` 域 `market_commands.py` / `market_platform.py` 一带的剩余装配与边界治理。

完成标准：

- orchestrator 只保留编排职责
- 规则、状态转换、副作用发送、任务调度继续拆到清晰边界
- 新问题不再持续从同一批“大而全”文件里反复长出来

### P2-3 广谱吞异常与降级路径仍然过多

现状：

- 仓内大量服务/任务/视图逻辑仍使用 `except Exception` 兜底，问题不只在“有降级”，而在于很多降级已经变成默认设计习惯。
- 当前最该优先治理的异常热点主要落在 `core/utils/task_monitoring.py`、`trade/services/market_expiration.py`、`trade/services/cache_resilience.py`、`trade/services/bank_supply_runtime.py` 等入口与基础设施边界。
- 异常压力已经明显从主流程编排层转移到 task / infra helper 层，但这些边界的异常分层与降级策略还没有真正固化。

当前剩余缺口：

- 业务异常、基础设施异常、可恢复降级异常还没有系统性分层，很多地方仍然是“先吞掉再记日志”；task 和基础设施 helper 侧还没有完成高信噪比治理。
- 一些关键经济/结算/通知链路对异常采取 best-effort 策略，短期提升了可用性，但也增加了状态失真和问题滞后的风险。
- 目前缺少“哪些链路允许 fail-open、哪些链路必须 fail-closed”的统一边界文档和代码约束。

完成标准：

- 关键链路不再直接使用裸 `except Exception` 作为常规控制流。
- 基础设施异常、幂等重试异常、用户输入异常分别归类到明确的异常层级。
- 对经济结算、战斗结算、库存扣减、工资/奖励发放等链路明确 fail-open / fail-closed 策略，并在代码与测试中固化。
- 降级日志之外，补足可观测性指标，避免“日志里报过但线上语义已漂移”的隐性失败。

### P2-4 View / Template 层复杂度仍在继续累积

现状：

- 虽然部分逻辑已向 service / selector 拆分，但若干热点视图和模板仍然过重，已经开始承担过多拼装、展示规则和交互细节。
- 结构审查时，`gameplay/views/jail.py`、`gameplay/views/production.py` 等仍属于高密度入口。
- 模板侧也存在明显热点，如 `guests/templates/guests/detail.html`、`gameplay/templates/gameplay/warehouse.html`、`gameplay/templates/gameplay/recruitment_hall.html` 等。

当前剩余缺口：

- View 层仍混有输入校验、锁、缓存失效、消息回写、AJAX 片段拼装等多重职责。
- Template 层仍承担大量条件渲染、局部状态组合和样式细节，后续功能继续追加时容易变成“没人敢动的大模板”。
- 当前模板复用和片段拆分策略还不够稳定，页面复杂度增长时缺少明确的上限控制。

完成标准：

- View 只保留请求编排、权限与响应装配，业务决策继续下沉到 service / selector / presenter。
- 大模板按稳定片段和职责拆分，避免继续在单文件内堆叠内联样式、复杂条件和批量 UI 分支。
- AJAX / 页面复用场景收口到明确的 partial / presenter 约定，减少同一页面多处重复拼装逻辑。
- 前端展示复杂度的增长不再主要表现为模板文件持续膨胀。

## 5. 当前待跟踪项

| 编号 | 主题 | 优先级 | 当前未完成点 | 当前证据 |
| --- | --- | --- | --- | --- |
| P1-3 | cross-app 边界收口 | P1 | `Guest` 少量残留规则、`trade` / `guilds` 边界回潮风险仍在 | 平台层已建立，但热点服务仍需持续防回流 |
| P1-4 | 门禁重构 | P1 | 真实外部服务 integration 门禁未完成最终执行确认，mypy 豁免仍未清零 | 默认 `flake8` / `pytest` / `check` 已绿，真实 env services 验证仍缺 |
| P2-2 | 热点模块继续拆分 | P2 | `guests/models.py`、`guests/services/recruitment*.py`、`market_commands.py`、`market_platform.py` 仍是当前最值得继续压的厚点 | `market_service.py` 已进一步退到 facade 级；当前剩余复杂度更多集中在 Guest 残留规则和 trade 服务层规则链 |
| P2-3 | 异常治理与降级边界 | P2 | 广谱 `except Exception` 仍多，异常热点已从主 orchestrator 迁移到 task / infra helper | `core/utils/task_monitoring.py`、`trade/services/market_expiration.py`、`trade/services/cache_resilience.py`、`trade/services/bank_supply_runtime.py` 等仍存在较多通用兜底异常 |
| P2-4 | View / Template 复杂度控制 | P2 | 热点视图和大模板继续膨胀，展示拼装职责仍偏重 | `gameplay/views/production.py`、`gameplay/views/jail.py`、`guests/templates/guests/detail.html` 等仍属高密度入口 |

## 6. 建议执行顺序

1. 先继续压缩 `Guest` 残留玩法规则，以及 `guests/models.py` / `guests/services/recruitment*.py` 这条招募链路剩余的规则链和兼容包装。
2. 然后继续清理 `trade` 域 `market_commands.py` / `market_platform.py` 一带的装配、缓存与副作用混合职责。
3. 同步治理 view / task / infra helper 层的广谱 `except Exception`，把 fail-open / fail-closed 边界重新写清。
4. 最后把真实外部服务 integration 门禁跑通，并继续缩减 `mypy` 豁免。

## 7. 当前结论

项目现在的核心问题，已经不是“还有没有明显事故点”，而是“跨域复杂度会不会回潮”和“默认绿灯会不会再次掩盖真实语义缺口”。

综合评分上调为：`9.3/10`

进一步拉到 `9.4+` 的前提，不再是继续拆主 orchestrator，而是把 `Guest` 残留规则、`trade` 剩余服务层边界、异常治理和真实 integration 门禁彻底收掉。
