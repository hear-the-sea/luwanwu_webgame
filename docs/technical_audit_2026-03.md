# 项目技术审计与优化清单（2026-03）

本文档只保留当前仍成立的问题、缺口和待跟踪项。已经完成并有代码/测试证据支撑的优化、重构和历史问题，均已从正文删除，不再混入当前审计结论。

最近更新：2026-03-17（第三十五批推进后重写正文：已删除完成项流水，只保留仍未闭环的问题与当前有效证据）

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
- 多轮 targeted `pytest` / `flake8` / `mypy` 已覆盖本轮拆分热点，但这些只证明当前拆分未打破默认环境下的语义，不等于真实外部服务语义已全部验证

当前无法宣称已闭环的部分：

- `tests/test_integration_external_services.py` 虽然已经补上 `mission` / `guild` 链路，但尚未在 `DJANGO_TEST_USE_ENV_SERVICES=1` 的真实 MySQL / Redis / Channels / Celery 环境下执行确认
- `mypy` 仍不是全项目高信噪比硬门禁，核心区域仍有豁免残留

## 2. 当前状态判断

整体上，项目已经脱离最危险阶段：高频事故项、明显的事务一致性问题、若干伪 facade 和跨域直连已经被实质收口。

当前真正剩下的，不再是“哪里还有明显 P0 bug”，而是三类结构性问题：

1. 仍有少量兼容入口和 monkeypatch 面没有退场，继续放大会拖慢后续真实重构。
2. 少量跨 app 边界和 `Guest` 相关玩法规则仍未彻底收口，存在复杂度回潮风险。
3. 默认门禁虽然全绿，但真实外部服务语义的集成门禁还没有完全跑通。

## 3. 剩余高优先级问题

### P1-1 去兼容层化还没有收尾

现状：

- `gameplay.services`、`gameplay.services.inventory`、`gameplay.services.recruitment`、`guests.services` 的大部分包根兼容导出已经移除。
- 但仍有少量兼容入口留在仓内，详见 [兼容入口清单](compatibility_inventory_2026-03.md)。

当前剩余缺口：

- `gameplay.admin.enqueue_global_mail_backfill` 仍保留包级 re-export
- `gameplay.services.raid.combat` 仍保留包根 re-export 以及 `random` / `LOOT_*` monkeypatch 面
- `battle.combatants` 仍是兼容 shim
- `gameplay.services.utils.__init__` 仍通过 star-export / 聚合导出暴露包根能力
- `websocket.__init__` 仍通过 `__getattr__` 维持懒加载兼容面

完成标准：

- 新代码不再新增 facade、懒加载导出和“只转发不收口”的兼容层
- 剩余兼容入口都能在清单里看到消费者、保留原因和退场条件
- 仓内测试逐步改为 patch 真实子模块，而不是继续绑定包根兼容口

### P1-3 cross-app 边界仍有残留耦合

重点区域：

- `guests/models.py`
- `trade/services/bank_service.py`
- `trade/services/market_service.py`
- `guilds/services/*`

当前剩余缺口：

- `Guest` 模型虽然已经迁出大量战斗、成长、工资、回血规则，但仍有少量玩法兼容属性/包装行为残留，需要继续外迁
- `trade` 域虽然已经建立 `trade_platform.py` / `market_platform.py`，但仍需防止后续逻辑重新长回服务层直连
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

- `gameplay/services/missions_impl/execution.py`
- `gameplay/services/raid/combat/runs.py`
- `trade/services/bank_service.py`

问题不在于“文件行数大”，而在于这些文件仍同时承载规则、状态推进、副作用和调度，后续需求一旦继续堆进去，复杂度会很快反弹。

完成标准：

- orchestrator 只保留编排职责
- 规则、状态转换、副作用发送、任务调度继续拆到清晰边界
- 新问题不再持续从同一批“大而全”文件里反复长出来

## 5. 当前待跟踪项

| 编号 | 主题 | 优先级 | 当前未完成点 | 当前证据 |
| --- | --- | --- | --- | --- |
| P1-1 | 去兼容层化 | P1 | 仍有少量兼容入口未退场，详见兼容入口清单 | 包根导出已大幅收缩，但 `raid.combat`、`battle.combatants`、`gameplay.services.utils`、`websocket.__init__` 等仍在 |
| P1-3 | cross-app 边界收口 | P1 | `Guest` 少量残留规则、`trade` / `guilds` 边界回潮风险仍在 | 平台层已建立，但热点服务仍需持续防回流 |
| P1-4 | 门禁重构 | P1 | 真实外部服务 integration 门禁未完成最终执行确认，mypy 豁免仍未清零 | 默认 `flake8` / `pytest` / `check` 已绿，真实 env services 验证仍缺 |
| P2-2 | 热点模块继续拆分 | P2 | `missions_impl/execution.py`、`raid/combat/runs.py`、`bank_service.py` 仍偏重 | 主流程已收缩，但职责密度仍高 |

## 6. 建议执行顺序

1. 先按 [兼容入口清单](compatibility_inventory_2026-03.md) 继续删除剩余 facade / patch 面。
2. 再继续压缩 `Guest` 残留玩法规则和 `trade` / `guilds` 边界回潮点。
3. 最后把真实外部服务 integration 门禁跑通，并继续缩减 `mypy` 豁免。

## 7. 当前结论

项目现在的核心问题，已经不是“还有没有明显事故点”，而是“剩余兼容面会不会继续阻碍真实收口”和“默认绿灯会不会再次掩盖真实语义缺口”。

综合评分暂维持：`8.9/10`

拉到 `9.0+` 的前提不是继续堆完成记录，而是把剩余兼容入口、跨域残留和真实 integration 门禁彻底收掉。
