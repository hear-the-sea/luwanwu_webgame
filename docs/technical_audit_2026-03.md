# 项目技术审计与优化清单（2026-03）

本文档基于 2026-03-17 的代码复核、针对性回归测试与部署门禁检查整理，只保留当前代码里仍然成立的问题。已经闭环且有代码/测试证据支撑的事项，已从正文和待跟踪列表移除，避免历史问题继续混入当前审计结果。

最近更新：2026-03-17（第九批推进：再核销 2 项剩余条目）

相关文档：

- [优化计划](optimization_plan.md)：已有的分阶段重构路线图
- [架构设计](architecture.md)：系统模块划分与数据流
- [开发指南](development.md)：开发、测试与运行方式

## 1. 审计范围与方法

本次复核覆盖：

- Django 配置层：`config/settings/*`、`config/asgi.py`
- 核心通用能力：`core/*`、`common/utils/celery.py`
- 关键业务路径：`gameplay`、`guests`、`trade`、`guilds`、`websocket`
- 会话与部署链路：`accounts/*`、`docker/*`、`Dockerfile`
- 质量门禁：`pyproject.toml`、`Makefile`、`.github/workflows/ci.yml`
- 测试结构与代表性回归：`tests/*`

本轮实际执行的验证：

- 逐项复核文档中标记为 `✅ 已完成` 的条目，对照实现与回归测试确认是否真正闭环
- `pytest -q tests/test_mission_launch_resilience.py tests/test_mission_refresh_async.py tests/test_raid_scout_refresh.py tests/test_world_chat_consumer.py tests/test_websocket_world_chat_history_internals.py tests/test_websocket_consumers.py tests/test_context_processors.py tests/test_gameplay_tasks.py tests/test_global_mail_tasks.py tests/test_guilds_tasks.py tests/test_health.py tests/test_asgi.py tests/test_work_service_concurrency.py tests/test_guests_defection.py tests/test_trade.py tests/test_trade_auction_bidding.py tests/test_trade_tasks.py tests/test_raid_combat_runs.py`
- `python -m mypy gameplay/services/online_presence_backend.py gameplay/services/raid/combat/refresh_flow.py`
- `DJANGO_DEBUG=0 DJANGO_ALLOWED_HOSTS=localhost DJANGO_SECRET_KEY=test-secret-key REDIS_PASSWORD=ci-test-dummy python manage.py check --deploy`

当前抽样结果：

- 针对性回归测试 `183 passed, 1 skipped`
- `check --deploy` 可正常进入 Django deploy checks 并执行完成
- 唯一告警为测试用 `SECRET_KEY` 过短，不属于本次代码回归问题
- 新增 helper 模块已通过 targeted mypy 检查，说明“拆分后立即纳入门禁”这条路径已开始落地
- 本轮复核确认：所有 `P0` 条目已闭环；`P1-7`、`P2-5` 已关闭；当前剩余问题集中在类型门禁和热点模块复杂度

## 2. 当前状态快照

整体判断：

- 优点：关键状态一致性、通知解耦、补偿链路、部署门禁、会话治理和完成态幂等保护已经明显收口。
- 现状：当前主要短板已经从“状态机会不会出错”转移为“高风险代码能否被持续约束”和“热点流程文件能否持续收缩”。
- 风险：剩余问题虽然不再是大面积 `P0` 事故源，但仍会持续拉低维护效率和后续演进稳定性。

本轮已核销并从正文移除的条目：

- `P0-1` 到 `P0-7`：任务启动半完成、侦察撤退语义、聊天补偿守恒、dispatch 失败收口、CI deploy gate、任务结算通知、帮会成员事务治理均已闭环。
- `P1-1`、`P1-2`、`P1-3`、`P1-5`、`P1-6`、`P1-8`、`P1-9`、`P1-10`、`P1-11`、`P1-12`、`P1-13`、`P1-14`、`P1-15`：高风险验证要求、任务监控并发计数、帮会产出补偿、训练/打工/生产/叛逃并发硬化、拍卖与交易链路语义错误、全服邮件补偿、单会话治理等已完成。
- `P1-7`：世界聊天限流已从 fixed-window 升级为 sliding-window，桶边界穿透问题已关闭。
- `P2-1`、`P2-3`、`P2-4`：DEBUG 下 WebSocket 路由告警、默认容器启动链路、nginx readiness 代理配置均已对齐。
- `P2-5`：HTTP 活跃态与 WS 连接态已拆成独立 zset 来源，再统一汇总在线人数。

## 3. 优先级总览

建议按以下优先级推进：

| 优先级 | 主题 | 目标 |
| --- | --- | --- |
| P1 | 高风险区类型门禁 | 让 mypy 真正约束核心服务层，而不是只覆盖低风险模块 |
| P2 | 热点模块持续拆分 | 降低“大而全”流程文件继续长出状态边界问题的概率 |

## 4. P1：仍需收口的高优先级项

### P1-4 mypy 仍不是高信噪比门禁

现象：

- 全局仍是宽松模式：
  - `disallow_untyped_defs = false`
  - `ignore_missing_imports = true`
- 高风险区域仍在 `ignore_errors` 清单里，包括：
  - `gameplay.models.*`
  - `gameplay.services.raid.*`
  - `guests.services.*`
  - `*.views`
- 虽然 `gameplay.services.buildings.*` 等模块已经进入 stricter override，但最复杂的状态机和服务层仍未被真正约束。

影响：

- 最容易出现事务边界、并发和状态语义问题的模块，仍可以在类型层面“裸奔”。
- 当前 mypy 更像“项目已接入类型检查”，还不是“关键路径可依赖的回归门禁”。

证据：

- `pyproject.toml`

建议：

- 下一轮缩减豁免名单时优先处理 `gameplay.services.raid.*` 和 `guests.services.*`，不要继续先做边角模块。
- 保持“新增核心模块禁止进入 `ignore_errors`”这条治理规则，同时把老的高风险豁免逐步拆掉。
- 对已经拆出的 helper 模块优先补标注，借此把 strict 范围往核心流程推进。

完成标准：

- 高风险区的类型豁免范围继续缩小。
- mypy 结果能真正拦截核心服务层的回归，而不只是装饰性绿灯。

## 5. P2：复杂度与数据面治理

### P2-2 热点模块仍然把规则、状态、调度和通知揉在一起

现象：

- 多个热点文件已开始拆分，但职责仍偏混合，典型如：
  - `gameplay/services/missions_impl/execution.py`
  - `gameplay/services/raid/combat/runs.py`
  - `trade/services/bank_service.py`
  - `gameplay/services/inventory/guest_items.py`
- 本轮虽然已新增：
  - `gameplay/services/inventory/soul_fusion_helpers.py`
  - `trade/services/rate_calculations.py`
  - `gameplay/services/raid/combat/raid_inputs.py`
  - `gameplay/services/raid/combat/refresh_flow.py`
- 但主流程文件体量和职责密度仍然偏高。

影响：

- 只要继续往这些“大而全”文件堆逻辑，本轮已经修掉的事务边界和补偿问题就容易换个位置重新长出来。
- 复杂度不是抽象审美问题，而是直接提高状态机再次退化的概率。

建议：

- 下一轮拆分优先按职责边界切，而不是按“顺手提个 helper”切：
  - 规则计算
  - 状态持久化
  - 任务调度
  - 通知与观测
- 对超过团队可读阈值的主流程文件，建立持续拆分清单，不再接受无限增长。

完成标准：

- 热点模块的事务边界和副作用边界继续变清晰。
- 新问题不再持续从同一类“大而全”文件里长出来。

## 6. 建议执行顺序

### 第一阶段：1 周内完成

- 缩小 `gameplay.services.raid.*`、`guests.services.*` 的 mypy 豁免范围。
- 继续把已拆出的 raid / online-presence helper 模块纳入 strict 检查，并从大包级 `ignore_errors` 中逐步剥离。

### 第二阶段：1-2 周内完成

- 继续拆分 `execution.py`、`runs.py` 等热点文件，把规则、持久化、调度、副作用进一步解耦。

### 第三阶段：持续推进

- 对拆分后的新模块同步补类型标注和门禁，避免复杂度只是平移。
- 观察运行期 degraded counter 和关键状态流，确认剩余问题不是“代码看起来对了”而是“运行上也稳定了”。

## 7. 当前待跟踪项

| 编号 | 主题 | 优先级 | 状态 | 验证方式 |
| --- | --- | --- | --- | --- |
| P1-4 | mypy 高风险区治理 | P1 | 🔄 部分完成 | 新增 `online_presence_backend.py`、`refresh_flow.py` 已进入 strict；`gameplay.services.raid.*`、`guests.services.*` 仍存在包级豁免 |
| P2-2 | 热点模块职责继续拆分 | P2 | 🔄 部分完成 | `runs.py` 已继续抽出 `refresh_flow.py`；`execution.py`、`bank_service.py`、`guest_items.py` 仍偏大 |

## 8. 达成 9 分以上的条件

如果目标是把综合评分稳定拉到 `9.0/10` 以上，剩余要求已经不再是清理 `P0`，而是把最后几个“会长期侵蚀可维护性”的问题彻底收口：

- `P1-4` 必须闭环，不能继续让高风险服务层长期处于弱门禁状态。
- `P2-2` 需要继续推进，直到 `execution.py`、`bank_service.py`、`guest_items.py` 这类热点文件也被实质性拆解。
- 新增的拆分和门禁必须带测试或运行证据，避免“复杂度治理”和“类型治理”只停留在文档层。
- 需要有一轮真实运行期验证，确认：
  - 关键 degraded counter 没有持续增长
  - 关键状态流不再出现新的复杂度回潮

一句话标准：

- `9 分以上` 不再取决于有没有大事故项，而取决于“剩余高风险治理是不是也变成了可持续、可验证的工程约束”。

## 9. 本次审计结论

项目当前已经明显脱离了最危险的阶段。任务启动半完成、侦察状态机、聊天补偿守恒、任务结算通知、dispatch 失败假阳性、deploy gate、生产完成幂等、叛逃原子性、单会话治理、默认容器与 readiness 链路这批真正会引发事故的点，本轮复核均已确认闭环并从审计正文移除。

当前剩余问题，更多是“怎样把现在的正确实现持续守住”：

1. 类型门禁还没真正压到最复杂的服务层。
2. 少数热点文件仍然承担过多职责，后续仍有再次退化风险。

综合评分：`8.5/10`

一句话结论：项目的关键状态机、聊天风控和在线态数据面已经进入“基本可信”区间，下一步最该做的是继续把类型门禁压到核心服务层，并把剩余热点流程文件拆到足够清晰。
