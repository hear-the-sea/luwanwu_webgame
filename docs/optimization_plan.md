# 项目优化计划

本文档只保留当前仍然有效的优化路线、阶段状态和后续执行顺序，不再记录已经失效的批次流水账。

相关文档：

- [技术审计](technical_audit_2026-03.md)
- [架构设计](architecture.md)
- [开发指南](development.md)
- [第二阶段统一写模型基线](write_model_boundaries.md)

## 1. 执行约束

自 `2026-03-19` 起，本计划必须服从 [技术审计](technical_audit_2026-03.md) 中的重构规则。

执行约束：

1. 不再以“抽 helper / 拆文件数量”作为优化完成标准，必须证明边界更清晰。
2. 统一异常处理、统一读路径、统一降级策略，必须先定义错误语义和平台口径。
3. 页面读路径、副作用补偿、基础设施降级，不允许继续在 view 层横向复制。
4. 全量 `pytest` 不绿时，优先恢复绿灯，不继续扩散重构范围。
5. 每轮只推进一个可验证主题，并同步补测试与文档。

## 2. 当前状态

### 2.1 已完成阶段

`阶段 1：先稳边界` 已完成。

当前已经稳定下来的结果：

- 热点页面入口已完成一轮边界收口，读侧 page context 与写动作入口已开始分离。
- `mission`、`production`、`trade`、`recruit`、`forge` 等热点链路已从 view 主文件中下沉出 page context 或 action handler。
- 页面读路径已开始统一到请求级 helper：`trade/page_context.py`、`gameplay/views/core.py`、`gameplay/views/map.py`、`gameplay/views/inventory.py`、`gameplay/views/messages.py`、`gameplay/views/work.py`、`gameplay/views/technology.py`、`gameplay/views/recruitment.py`、`gameplay/views/arena.py`、`gameplay/views/mission_page_context.py`、`gameplay/selectors/production.py`、`guests/views/roster.py` 已接入 `get_prepared_manor_for_read(...)`。
- `raid/scout` 读侧刷新已从 accessor 中显式化；`get_active_raids()` 已退回纯读查询。
- 默认测试、覆盖率与部分 mypy 门禁已补齐第一轮可信度缺口。
- 2026-03-21 已补齐阶段 1 封板验证：`make test` 全量通过（`1852 passed, 28 deselected`），并完成热点包导入链复核；`gameplay.views`、`gameplay.selectors`、`guests.views`、`guilds.views` 已退出包根聚合导入用法，相关 `__init__.py` 已收口为无副作用最小包标记。

阶段 1 已封板，后续不再继续把“拆 view / 抽 helper”本身作为主要目标。

### 2.2 当前主线

当前主线已切换到 `阶段 3：类型与异常边界治理`。

`阶段 2：并发与测试基线` 已完成封板。当前稳定下来的阶段 2 结论如下：

- `mission / raid / guest recruitment` 的统一写模型已按 [第二阶段统一写模型基线](write_model_boundaries.md) 固定下来；写链路的 `view / action handler`、`write command`、`after-commit follow-up`、`refresh / finalize command` 边界已可清楚说明。
- `HomeView`、`MapView`、`raid_status_api` 已退出 GET 读路径中的 `raid/scout` 补偿刷新；显式刷新统一收口到 `POST /gameplay/api/map/status/refresh/` 和 `gameplay.services.raid.refresh_raid_activity()`，不再由 view 内联拼接活动补偿。
- `raid / scout` 的发起、撤退、返程完成、refresh 补偿边界已拆到稳定服务入口；`mission` 与 `guest recruitment` 的主写入口、refresh 契约和 finalize 竞争语义也都已有服务层与 integration 测试约束。
- `refresh_manor_state(...)` 已收紧为默认只处理建筑/资源读侧投影；活动补偿只会在显式 `include_activity_refresh=True` 或显式 refresh API / worker 链路中运行，不再默认挂回页面读路径。
- `2026-03-22` 已再次完成阶段 2 封板验证：`tests/test_map_views.py`、`tests/test_core_views.py` 共 `61 passed`，用于约束首页/地图读路径与显式刷新入口不回退。
- `2026-03-22` 已再次完成阶段 2 real-services gate：`DJANGO_TEST_USE_ENV_SERVICES=1 make test-critical` 共 `20 passed, 3 skipped`，覆盖 `raid / scout / mission / guest recruitment / work service` 的关键并发与任务派发语义。
- 阶段 2 的关键 real-services 套件会继续保留在 `make test-critical`、`make test-real-services` 与 `make test-gates` 中，后续作为回归门禁持续维护，不再把阶段 2 当作主线开发主题。
- 阶段 3 的异常边界治理已开始落到 `guest recruitment` 与 `mission` follow-up 链路：`finalize_guest_recruitment()` 不再把 `AssertionError` 等内部契约/程序错误伪装成 `FAILED` 招募结果，当前只会把显式 `RecruitmentError` 落成 durable 失败态；`recruitment_followups` 也已退出“导入失败/消息发送失败一律吞掉”的 broad catch，任务模块导入的编程错误会继续冒泡，招募完成通知只对显式消息/基础设施异常降级。与此同时，`mission` 的 `import_launch_post_action_tasks()`、`refresh_command` 与相关 task follow-up 导入逻辑也开始区分“目标模块缺失”与“模块内部嵌套依赖损坏”两类 ImportError，只对前者降级；`launch_resilience` 也开始只对基础设施类 launch/report/dispatch 故障降级，编程错误不再统一吃掉；`send_mission_report_message()` 也已改为只对显式消息/通知基础设施异常降级，战报消息创建与通知中的编程错误会继续冒泡；`build_mission_drops_with_salvage()` 这类纯业务奖励计算也已退出 broad catch，salvage 计算契约错误不再被静默降级为“少发奖励”，并已补服务契约测试约束这些边界。
- `troop recruitment` 生命周期也已开始按阶段 3 收口异常语义：`gameplay/services/recruitment/lifecycle.py` 的 `complete_troop_recruitment` 导入 fallback 现在只在 `gameplay.tasks` 目标模块缺失时降级，嵌套依赖损坏和其它导入故障会继续冒泡；募兵完成通知已拆分为站内信创建与 WebSocket 推送两段，只有显式消息/通知基础设施故障继续 fail-open，编程错误会继续暴露。`guests/services/recruitment_shared.py` 的聚贤庄缓存失效 helper 也已去掉多余 broad catch，不再把参数/程序错误吞成静默 debug。
- `2026-03-22` 已补一轮阶段 3 聚焦验证：`tests/test_troop_recruitment_service.py`、`tests/test_recruitment_hall_cache.py` 共 `16 passed`，用于约束护院募兵生命周期与聚贤庄缓存失效 helper 的异常边界不回退。
- `raid/scout` 的 follow-up 与 refresh 任务导入边界也已开始按阶段 3 收口：`gameplay/services/raid/scout_followups.py` 不再把侦察结果消息链中的编程错误统一吞成 best-effort 成功，当前只对显式站内信/数据库基础设施故障做降级；`dispatch_scout_task()` 与 `scout_refresh.resolve_scout_refresh_tasks()` 也开始区分“`gameplay.tasks.pvp` 目标模块缺失”和“模块内部嵌套依赖损坏/其它导入故障”，只对前者回退，后者继续冒泡。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_raid_scout_refresh.py` 共 `18 passed`，用于约束 `raid/scout` follow-up 与 refresh 任务导入的异常边界不回退。
- `gameplay/services/raid/scout_followups.py` 的侦察消息 follow-up 实现层也已继续退出 broad catch：当前已补齐 `SCOUT_MESSAGE_DELIVERY_EXCEPTIONS` 显式异常常量，并直接用 `except SCOUT_MESSAGE_DELIVERY_EXCEPTIONS` 承接站内信降级；`AssertionError("broken scout message contract")`、`RuntimeError("message backend down")` 一类编程/模糊 runtime 错误会继续冒泡，不再依赖“先 `except Exception` 再 helper 判断”的旧写法。
- `raid` 主写链路的任务导入边界也已继续按阶段 3 收口：`gameplay/services/raid/combat/refresh_flow.py`、`gameplay/services/raid/combat/run_side_effects.py` 与 `gameplay/services/raid/combat/battle.py` 现在开始区分“`gameplay.tasks` 目标模块缺失”和“模块内部嵌套依赖损坏/其它导入故障”，只对前者做同步回退或 best-effort 降级；`process_raid_battle_task`、`complete_raid_task` 相关导入中的编程错误不再被统一伪装成刷新/返程成功。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_raid_combat_runs.py`、`tests/test_raid_combat_battle.py` 共 `46 passed`，用于约束 `raid` refresh / dispatch / finalize 的任务导入异常边界不回退。
- `raid` 的消息与缓存降级口径也已继续按阶段 3 收口：`gameplay/services/raid/combat/start.py` 发送来袭警报时不再把 `AssertionError` 等编程错误统一吞成出征成功，当前只对显式消息/数据库基础设施故障做 fail-open；`gameplay/services/raid/utils.py` 的近期攻击缓存 helper 也已改为只对显式缓存基础设施故障降级，缓存调用契约错误会继续冒泡。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_raid_combat_runs.py`、`tests/test_raid_utils_cache.py` 共 `36 passed`，用于约束 `raid` 来袭消息与近期攻击缓存 helper 的异常边界不回退。
- `gameplay/services/raid/combat/start.py` 的来袭告警 helper 也已继续退出 broad catch：当前已补齐 `RAID_INCOMING_MESSAGE_EXCEPTIONS` 显式异常常量，并直接用 `except RAID_INCOMING_MESSAGE_EXCEPTIONS` 承接站内信降级；`AssertionError("broken incoming message contract")`、`RuntimeError("message backend down")` 一类编程/模糊 runtime 错误会继续冒泡，不再依赖“先 `except Exception` 再 helper 判断”的旧写法。
- `gameplay/services/raid/utils.py` 的近期攻击 cache helper 也已继续退出 broad catch：`_safe_cache_get/_safe_cache_set/_safe_cache_delete` 当前直接改成显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 白名单，只对显式缓存基础设施故障做 best-effort fallback；`RuntimeError("cache set failed")`、`RuntimeError("cache delete failed")` 一类 runtime marker / 契约错误会继续冒泡，避免 `raid` 的共享读辅助逻辑继续靠“先 `except Exception` 再 helper 判断”的旧写法掩盖缓存调用问题。
- `arena` 的消息降级口径也已开始按阶段 3 收口：`gameplay/services/arena/exchange_helpers.py`、`gameplay/services/arena/lifecycle_helpers.py` 与 `gameplay/services/arena/match_helpers.py` 不再把竞技场兑换提示、结算奖励消息和战报消息里的编程错误统一吞成 best-effort 成功，当前只对显式消息/数据库基础设施故障做 fail-open；相关 helper 的异常边界开始与 `mission / raid / recruitment` 保持一致。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_arena_exchange_helpers.py`、`tests/test_arena_services.py`、`tests/test_arena_message_boundaries.py` 共 `33 passed`，用于约束 `arena` 兑换、结算与战报消息的异常边界不回退。
- `arena` 的批处理主入口也已开始按阶段 3 收口：`gameplay/services/arena/core.py` 的 `start_ready_tournaments()` 与 `run_due_arena_rounds()` 已去掉 broad catch，不再把批处理编排里的 `AssertionError` 等编程错误吞成“记录日志后继续处理”，当前会让异常继续冒泡，避免后台任务静默掩盖竞技场轮次编排问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_arena_services.py`、`tests/test_arena_exchange_helpers.py`、`tests/test_arena_message_boundaries.py` 共 `35 passed`，用于约束 `arena` 批处理主入口与消息边界不回退。
- `gameplay/tasks/arena.py` 的批处理任务入口也已继续按阶段 3 收口：`scan_arena_tournaments()` 当前只会聚合显式数据库基础设施故障并在末尾抛出失败阶段摘要，不再把 `AssertionError("broken arena start contract")` 一类编程错误吞成汇总 `RuntimeError`；这样批处理层仍保留“多阶段基础设施故障尽量扫完”的编排语义，但不会继续掩盖竞技场任务入口自身的契约错误。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/tasks/arena.py tests/test_arena_tasks.py` 已通过；`pytest tests/test_arena_tasks.py -q` 为 `3 passed`，用于约束 `arena` 批处理任务入口的数据库故障聚合与编程错误直接冒泡边界不回退。
- `arena` 的比赛解析边界也已继续按阶段 3 收口：`gameplay/services/arena/match_helpers.py` 的 `resolve_match_locked()` 不再把 `simulate_report()` 的所有异常统一改写成“待系统重试”；当前只会把显式 `BattlePreparationError` 转成可重试的 `ArenaMatchResolutionError` 语义，`AssertionError` 等编程错误会继续冒泡，避免竞技场对战编排静默掩盖 battle 契约错误。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_arena_services.py`、`tests/test_arena_exchange_helpers.py`、`tests/test_arena_message_boundaries.py`、`tests/test_arena_round_helpers.py` 共 `40 passed`，用于约束 `arena` 批处理主入口、消息边界与比赛解析异常边界不回退。
- `arena` 的消息降级口径也已继续退出 runtime marker 猜测：`gameplay/services/arena/exchange_helpers.py`、`gameplay/services/arena/lifecycle_helpers.py` 与 `gameplay/services/arena/match_helpers.py` 当前只对显式 `MessageError` 与数据库基础设施故障做 best-effort 降级，不再把 `RuntimeError("message backend down")` 一类 runtime marker 继续当作消息基础设施错误，避免竞技场消息链静默掩盖契约问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_arena_exchange_helpers.py`、`tests/test_arena_message_boundaries.py`、`tests/test_arena_services.py`、`tests/test_arena_round_helpers.py` 共 `44 passed`，用于约束 `arena` 消息降级口径退出 runtime marker 猜测后不回退。
- `gameplay/services/arena/exchange_helpers.py` 的兑换成功消息 helper 也已继续退出 broad catch：当前已补齐 `ARENA_MESSAGE_DELIVERY_EXCEPTIONS` 显式异常常量，并直接用 `except ARENA_MESSAGE_DELIVERY_EXCEPTIONS` 承接站内信降级；`AssertionError("broken arena exchange message contract")`、`RuntimeError("message backend down")` 一类编程/模糊 runtime 错误会继续冒泡，不再依赖“先 `except Exception` 再 helper 判断”的旧写法。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/services/arena/exchange_helpers.py tests/test_arena_exchange_helpers.py tests/test_arena_services.py` 已通过；`pytest tests/test_arena_exchange_helpers.py tests/test_arena_services.py -q` 为 `34 passed`，用于约束 `arena exchange` 成功消息 helper 的显式消息/数据库异常白名单与编程错误冒泡边界不回退。
- `gameplay/services/arena/lifecycle_helpers.py` 与 `gameplay/services/arena/match_helpers.py` 的结算/战报消息 helper 也已继续退出 broad catch：当前已分别补齐 `ARENA_SETTLEMENT_MESSAGE_EXCEPTIONS` 与 `ARENA_BATTLE_MESSAGE_EXCEPTIONS` 显式异常常量，并直接用 `except ...` 承接消息降级；`AssertionError("broken arena settlement message contract")`、`AssertionError("broken arena battle message contract")` 与 `RuntimeError("message backend down")` 一类编程/模糊 runtime 错误会继续冒泡，不再依赖旧的 broad catch + helper 判断。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/services/arena/lifecycle_helpers.py gameplay/services/arena/match_helpers.py gameplay/services/raid/scout_followups.py tests/test_arena_message_boundaries.py tests/test_raid_scout_refresh.py` 已通过；`pytest tests/test_arena_message_boundaries.py tests/test_raid_scout_refresh.py -q` 为 `34 passed`，用于约束 `arena` 结算/战报消息 helper 与 `scout follow-up` 站内信的显式消息/数据库异常白名单和编程错误冒泡边界不回退。
- `raid` 的战斗后置副作用边界也已继续按阶段 3 收口：`gameplay/services/raid/combat/battle.py` 不再把 `_send_raid_battle_messages()` 与 `_dismiss_marching_raids_if_protected()` 的编程错误统一吞成“记录日志后继续”；当前只对显式消息/基础设施故障做降级，但仍会在返程完成任务派发后把编程错误继续冒泡，避免战斗结果已落库时静默掩盖消息与保护清理契约错误。
- `gameplay/services/raid/combat/battle.py` 的 battle/capture 后置实现层也已继续细化语义：`_apply_capture_reward()` 当前直接改成显式 `RAID_CAPTURE_DEGRADED_EXCEPTIONS` 白名单，不再保留 broad catch；`process_raid_battle()` 里保留的两处 broad catch 现在也只承担“派发返程任务后再把编程错误继续抛出”的语义，基础设施故障仍记录 `degraded/component`，但 `AssertionError("broken raid message contract")`、`AssertionError("broken raid cleanup contract")` 这类编程错误不再被额外标记成 degraded infrastructure。
- `raid` 的目标失效遣返边界也已继续收紧：`gameplay/services/raid/combat/travel.py` 的 `_retreat_raid_run_due_to_blocked_target()` 不再吞掉消息发送里的编程错误，`resolve_complete_raid_task()` 也只对显式缺少 `gameplay.tasks` 模块做降级，嵌套依赖导入失败与其它契约错误会继续冒泡。
- `raid` 的俘获奖励边界也已继续收紧：`gameplay/services/raid/combat/capture.py` 的 `_delete_captured_guest_gear()` 不再把删装备阶段的编程错误统一吞掉，当前只对显式数据库/基础设施故障做降级；`gameplay/services/raid/combat/battle.py` 的 `_apply_capture_reward()` 也已统一为仅对显式基础设施故障 fail-open，`AssertionError` 等契约错误会继续冒泡，避免俘获奖励链路静默掩盖 gear / capture 契约问题。
- `gameplay/services/raid/combat/capture.py` 的删装备 helper 也已继续退出 broad catch：`_delete_captured_guest_gear()` 当前直接改成显式 `except DATABASE_INFRASTRUCTURE_EXCEPTIONS` 白名单，不再依赖“先 `except Exception` 再 helper 判断”的旧降级写法；`AssertionError("broken gear delete contract")` 与其它非数据库类编程错误会继续冒泡。
- `raid` 的刷新与派发边界也已继续按阶段 3 收口：`gameplay/services/raid/combat/refresh_flow.py` 与 `gameplay/services/raid/combat/run_side_effects.py` 已去掉 import 路径上的 broad catch，当前只对显式缺少 `gameplay.tasks` 模块做同步回退/降级，`AssertionError` 等编程错误会直接冒泡，避免后台刷新与任务派发静默掩盖导入契约错误。
- `raid` 与 `scout` 的消息/派发入口也已继续收紧 runtime marker 兼容：`gameplay/services/raid/combat/start.py` 与 `gameplay/services/raid/scout_followups.py` 的消息发送当前只对显式 `MessageError` 与数据库基础设施故障做降级，不再把 `RuntimeError(\"message backend down\")` 一类 runtime marker 猜测继续当作消息基础设施错误；同时 `dispatch_scout_task()` 已去掉导入路径上的 broad catch，仅对显式缺少 `gameplay.tasks.pvp` 模块做降级，嵌套依赖导入失败与编程错误会继续冒泡。
- `raid/scout` 的刷新 helper 与近期攻击缓存配置边界也已继续按阶段 3 收口：`gameplay/services/raid/scout_refresh.py` 的 `resolve_scout_refresh_tasks()` 已去掉导入路径上的 broad catch，仅对显式缺少 `gameplay.tasks.pvp` 模块做同步回退；`gameplay/services/raid/utils.py` 的 `_recent_attacks_cache_ttl_seconds()` 也不再吞掉任意配置读取异常，当前只对非法 TTL 值做默认值兜底，设置访问契约错误会继续冒泡，避免缓存策略配置问题被静默掩盖。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_raid_scout_refresh.py`、`tests/test_raid_utils_cache.py`、`tests/test_raid_combat_runs.py` 共 `68 passed`，用于约束 `raid/scout` refresh 任务导入与近期攻击缓存配置边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/services/raid/combat/start.py gameplay/services/raid/combat/capture.py tests/test_raid_combat_runs.py tests/test_raid_combat_battle.py` 已通过；`pytest tests/test_raid_combat_runs.py tests/test_raid_combat_battle.py -q` 为 `69 passed`，用于约束 `raid` 来袭告警与俘获装备清理 helper 的显式消息/数据库异常白名单和编程错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/services/raid/combat/battle.py tests/test_raid_combat_battle.py` 已通过；`pytest tests/test_raid_combat_battle.py -q` 为 `37 passed`，用于约束 `raid battle` 后置消息/清理补偿的 degraded 标记只保留给显式基础设施故障，编程错误继续派发返程任务后冒泡但不误记为 degraded infrastructure。
- `troop recruitment` 与 `mission` 的完成通知口径也已继续退出 runtime marker 猜测：`gameplay/services/recruitment/lifecycle.py` 的募兵完成站内信和 WebSocket 通知当前只对显式 `MessageError` 与已知通知基础设施故障做降级，不再把 `RuntimeError("message backend down")`、`RuntimeError("ws backend down")` 一类 runtime marker 继续当作可吞错误；同文件的 `schedule_recruitment_completion()` 也已去掉导入路径上的 broad catch，仅对显式缺少 `gameplay.tasks` 模块做跳过调度。`gameplay/services/missions_impl/finalization_helpers.py` 的任务战报消息与通知也同步退出 runtime marker 兼容，继续把模糊 runtime 包装和编程错误暴露出来。
- `gameplay/services/missions_impl/finalization_helpers.py` 的实现层也已继续退出 broad catch：任务战报站内信创建与 WebSocket 推送当前都改成显式 `MessageError` / 基础设施异常分支，不再依赖“先 `except Exception` 再 helper 判断”的旧降级写法；`RuntimeError("message backend down")`、`RuntimeError("ws backend down")`、`AssertionError("broken mission notify contract")` 一类编程或契约错误会继续冒泡，但不会回滚已提交的任务完成结果。
- `gameplay/services/recruitment/lifecycle.py` 的实现层也已继续退出 broad catch：募兵完成后的站内信创建与 WebSocket 推送当前都改成显式 `MessageError` / 基础设施异常分支，不再依赖“先 `except Exception` 再 helper 判断”的旧降级写法；`RuntimeError("message backend down")`、`RuntimeError("ws backend down")`、`AssertionError("broken troop notify contract")` 一类编程或契约错误会继续冒泡，但不会回滚已提交的募兵完成结果。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_troop_recruitment_service.py`、`tests/test_mission_refresh_async.py` 共 `32 passed`，用于约束 `troop recruitment` 与 `mission` 完成通知边界退出 runtime marker 猜测后不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_mission_refresh_async.py` 共 `17 passed`，用于约束任务战报消息/通知实现层退出 broad catch 后的基础设施降级与 runtime/契约错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_troop_recruitment_service.py`、`tests/test_schedule_resilience.py` 共 `40 passed`，用于约束募兵生命周期通知降级与调度导入边界不回退。
- `gameplay/services/utils/notifications.py` 这个 WebSocket 通知总入口也已继续退出 runtime marker 兼容：`notify_user()` 当前只对显式通知基础设施异常做返回 `False` 的降级，不再把 `RuntimeError("notification backend down")` 一类模糊 runtime 包装继续当作 channels 基础设施错误吞掉，避免调用侧被总入口静默掩盖契约问题。
- `mission` 启动韧性边界也已继续退出 runtime marker 猜测：`gameplay/services/missions_impl/launch_resilience.py` 的战报准备与完成任务派发当前只对显式数据库/基础设施故障做降级，不再把 `RuntimeError("report backend unavailable")`、`RuntimeError("dispatch backend unavailable")` 一类 runtime marker 继续当作可吞错误，避免启动主链静默掩盖调度契约问题。
- `raid` 主战斗链上的 runtime marker 兼容也已继续收口：`gameplay/services/raid/combat/battle.py`、`gameplay/services/raid/combat/capture.py`、`gameplay/services/raid/combat/travel.py` 当前只对显式 `MessageError` 与已知数据库/基础设施故障做降级，不再把 `RuntimeError("redis down")`、`RuntimeError("redis timed out")`、`RuntimeError("message backend down")` 一类 runtime marker 继续当作可吞错误，避免来袭消息、俘获奖励和战后清理静默掩盖契约问题。
- `trade / guests / 页面错误映射` 的剩余 runtime marker 兼容也已继续收口：`trade/tasks.py`、`trade/selector_builders.py`、`guests/tasks.py` 与 `guests/services/recruitment_followups.py` 当前都只对显式数据库/基础设施异常或 `MessageError` 做降级，不再把 `RuntimeError("... backend unavailable")`、`RuntimeError("message backend down")` 一类模糊 runtime 包装继续当作可吞错误；`core/utils/view_error_mapping.py` 也同步移除了页面错误分类里的 runtime marker 开关，避免页面层继续把模糊运行时包装误判成基础设施故障。
- `trade/services/market_notification_helpers.py` 与 `core/utils/infrastructure.py` 也已同步完成语义下沉：通用 `is_expected_infrastructure_error()` 不再接受 runtime marker 猜测，cache 兼容被收口到 `is_expected_cache_infrastructure_error()` 这类 cache 专用 helper；交易消息 helper 当前只对显式 `MessageError` 与数据库基础设施故障做 fail-open，不再把 `RuntimeError("message backend down")` 一类模糊 runtime 包装吞成交易成功后的静默降级。
- `trade/services/market_notification_helpers.py` 的实现层也已继续退出 broad catch：交易站内信与卖家通知 helper 当前都改成显式 `MessageError` / 基础设施异常分支，`RuntimeError("notify backend down")`、`AttributeError("bad payload")` 一类编程或契约错误会继续冒泡，不再依赖“先 `except Exception` 再 helper 判断”的旧降级写法。
- `trade` 的拍卖通知链也已继续按阶段 3 收口：`trade/services/auction/bidding.py` 的出局提醒，以及 `trade/services/auction/rounds.py` 的中标消息/推送，当前只对显式 `MessageError`、数据库基础设施异常与通知基础设施异常做降级；中标消息的“直接发货” fallback 也不再把 `RuntimeError("message backend down")` 一类模糊 runtime 包装当成可吞错误，避免拍卖消息与发货补偿静默掩盖契约问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_trade_auction_bidding.py` 共 `10 passed`，用于约束拍卖出局提醒的消息/通知降级边界退出 broad catch 后不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_trade_auction_bidding.py`、`tests/test_trade_auction_rounds.py` 共 `36 passed`，用于约束拍卖出局提醒、中标消息与 direct grant fallback 的异常边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_market_notification_helpers.py` 共 `12 passed`，用于约束交易消息/通知 helper 的基础设施降级与 runtime/契约错误冒泡边界不回退。
- `common/utils/celery.py` 的任务派发适配层也已开始按阶段 3 收口：`safe_apply_async()` 与 `safe_apply_async_with_dedup()` 当前只对显式 broker / cache 基础设施异常做 fail-open，`AssertionError`、序列化契约错误和其它编程错误会继续冒泡；dedup gate 的 cache rollback 也不再把编程错误吞成静默 `False`，避免任务派发入口继续把非基础设施故障伪装成“派发失败但可忽略”。
- `common/utils/celery.py` 的 dedup rollback 语义也已继续细化：`safe_apply_async()` 现已改成直接捕获显式 broker 白名单异常，不再走“先 `except Exception` 再 isinstance 判断”的旧路径；`safe_apply_async_with_dedup()` 的 dedup gate 回滚也已改由 `finally` 驱动，确保 broker 基础设施故障、派发契约错误和其它意外异常都会先释放 dedup key 再继续返回/冒泡，而 rollback 自身仍只对白名单内的 cache 基础设施故障做 debug 级降级。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_common_celery_utils.py`、`tests/test_common_utils.py`、`tests/test_gameplay_tasks.py`、`tests/test_guests.py` 共 `65 passed`，用于约束通用任务派发、dedup gate rollback 与 guest training / recruitment 调度边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy common/utils/celery.py tests/test_common_celery_utils.py tests/test_common_utils.py tests/test_gameplay_tasks.py tests/test_guests.py` 已通过；`pytest tests/test_common_celery_utils.py tests/test_common_utils.py tests/test_gameplay_tasks.py tests/test_guests.py -q` 为 `72 passed`，用于约束通用任务派发入口的 broker 白名单、dedup key `finally` 回滚与 rollback cache 基础设施降级边界不回退。
- `core/utils/rate_limit.py` 也已继续按阶段 3 收口：rate limit 当前只会把显式 cache 基础设施故障降级为 503 / busy 响应，不再把 `AssertionError` 一类 cache 调用契约错误统一吞成“系统繁忙”，避免页面层把 rate limit helper 的编程错误误判成缓存基础设施抖动。
- `core/utils/cache_lock.py` 也已继续按阶段 3 收口：缓存锁当前只会把显式 cache 基础设施故障当作 fallback / fail-closed 条件，`cache.add/get/delete` 与 Redis 原子释放里的 `AssertionError` 一类契约错误会继续冒泡，不再被静默降级成本地锁或 compare-delete fallback，避免锁适配层掩盖缓存契约问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_cache_lock_utils.py`、`tests/test_rate_limit.py`、`tests/test_rate_limit_safe_methods.py`、`tests/test_common_celery_utils.py`、`tests/test_common_utils.py`、`tests/test_gameplay_tasks.py`、`tests/test_guests.py` 共 `93 passed`，用于约束缓存锁、rate limit 与通用任务派发适配层的异常边界不回退。
- `gameplay/services/utils/cache.py` 与 `gameplay/services/utils/messages.py` 这两个共享 cache/message helper 也已继续按阶段 3 收口：它们当前只对显式 cache 基础设施异常做 best-effort 降级，不再把 `RuntimeError("cache down")`、`RuntimeError("cache get failed")`、`RuntimeError("cache add failed")` 一类 runtime marker 继续当作缓存故障吞掉，避免共享 helper 静默掩盖缓存契约错误并向上层传播错误的“缓存只是抖动”语义。
- `gameplay/services/utils/cache.py` 的实现层也已继续退出 broad catch：首页统计、聚贤庄上下文、庄园缓存失效、`cached(...)` 装饰器与 `get_or_set(...)` 当前都改成显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 白名单，不再依赖“先 `except Exception` 再 helper 判断”的旧降级写法；`RuntimeError("cache delete failed")`、`RuntimeError("cache set failed")` 一类编程或契约错误会继续冒泡，避免共享 cache helper 继续掩盖调用契约问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_cache_utils.py`、`tests/test_message_attachments.py`、`tests/test_recruitment_hall_cache.py`、`tests/test_recruitment_views.py` 共 `30 passed`，用于约束共享 cache/message helper 的 runtime marker 兼容继续收口后不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_cache_utils.py` 共 `7 passed`，用于约束共享 cache helper 实现层退出 broad catch 后的基础设施降级与 runtime/契约错误冒泡边界不回退。
- `gameplay/selectors/stats.py` 与 `gameplay/services/online_presence.py` 这两个全局统计/在线态入口也已继续按阶段 3 收口：当前只对显式 cache / Redis 基础设施异常做降级，不再把 `RuntimeError("cache read failed")`、`RuntimeError("cache write failed")`、`RuntimeError("redis down")` 一类 runtime marker 继续当作可吞错误；页面全局统计与在线态 middleware 会继续暴露模糊 runtime 包装和其它编程错误，避免全站读路径把契约问题误判成基础设施抖动。
- `gameplay/services/online_presence.py` 与 `gameplay/services/ranking.py` 的 cache helper 实现层也已继续退出 broad catch：在线态 touch 去抖缓存与玩家排名缓存当前都改成显式 cache 基础设施异常白名单，只对显式 cache 故障做 best-effort；`AssertionError("broken presence cache delete contract")`、`AssertionError("broken ranking cache contract")` 这类缓存调用契约错误会继续冒泡，避免全局在线态/排名读路径静默掩盖 helper 契约问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_context_processors.py` 共 `16 passed`，用于约束全局统计 selector 与在线态 middleware 的异常边界退出 runtime marker 猜测后不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_read_helpers.py`、`tests/test_core_views.py`、`tests/test_map_views.py` 共 `64 passed`，用于约束请求级读路径 helper 与首页/地图读路径的基础设施降级和编程错误冒泡边界不回退。
- `gameplay/services/manor/refresh.py` 的庄园读刷新节流边界也已继续按阶段 3 收口：缓存节流当前只对显式 cache 基础设施异常降级为本地 fallback，不再把 `RuntimeError("cache down")` 一类 runtime marker 继续当作可吞错误；庄园首页读刷新会继续暴露模糊 runtime 包装和缓存调用契约错误，避免页面读路径把节流 helper 的编程问题误判成缓存抖动。
- `gameplay/services/manor/refresh.py` 的实现层也已继续退出 broad catch：`refresh_manor_state(...)` 的 cache throttle gate 当前直接对显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 做本地 fallback，不再依赖“先 `except Exception` 再 helper 判断”的旧降级写法；`RuntimeError("cache down")` 一类编程或契约错误会继续冒泡，避免总刷新入口继续掩盖 cache gate 调用问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_gameplay.py -k refresh_manor_state` 共 `10 passed`，用于约束庄园读刷新节流 helper 的基础设施降级与 runtime/契约错误冒泡边界不回退。
- `gameplay/views/read_helpers.py` 的请求级读路径 helper 也已继续退出 broad catch：`prepare_manor_for_read()` 当前直接对显式 `DATABASE_INFRASTRUCTURE_EXCEPTIONS` 做统一降级，不再依赖“先 `except Exception` 再 helper 判断”的旧写法；`RuntimeError("cache backend unavailable")` 一类编程或模糊 runtime 错误会继续冒泡，避免首页/地图/仓库等高频页面入口继续掩盖读投影契约问题。
- `gameplay/services/raid/utils.py` 的近期攻击缓存 helper 也已继续退出 runtime marker 猜测：当前只对显式 cache 基础设施异常做 best-effort 降级，不再把 `RuntimeError("cache down")` 一类 runtime marker 继续当作缓存故障吞掉，避免踢馆保护检查把缓存契约错误误判成短暂缓存抖动。
- `gameplay/services/technology_runtime.py` 的科技刷新节流边界也已继续按阶段 3 收口：`refresh_technology_upgrades()` 的 cache throttle gate 当前只对显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 做本地 fallback，不再把 `RuntimeError("cache down")` 一类模糊 runtime 包装继续当作缓存故障吞掉；科技刷新主链会继续暴露 cache 调用契约错误，避免把刷新 helper 的编程问题误判成可接受的缓存抖动。
- `core/utils/cache_lock.py` 与 `core/utils/rate_limit.py` 这两个公共 cache 适配层也已继续退出 runtime marker 猜测：缓存锁与 rate limit 当前只对显式 cache 基础设施异常做 fallback / 503 降级，不再把 `RuntimeError("cache down")` 一类 runtime marker 继续当作缓存故障吞掉，避免锁与限流入口把缓存契约错误误判成基础设施抖动。
- `core/utils/task_monitoring.py` 的任务指标缓存层也已继续退出 runtime marker 猜测：任务注册、计数读取、重置与 degraded counter 当前只对显式 cache 基础设施异常做本地 fallback / 静默忽略，不再把 `RuntimeError("cache down")` 一类模糊 runtime 包装吞成“监控系统抖动”，避免任务指标链路静默掩盖缓存调用契约错误。
- `core/utils/task_monitoring_registry.py` 的 Redis registry helper 也已继续同步收口：默认 Redis client 获取、set index 读取与 marker 扫描当前只对显式 cache 基础设施异常降级返回 `None`，不再把 `RuntimeError("cache down")` 一类模糊 runtime 包装吞成“任务指标 registry 暂不可用”，避免底层 registry helper 继续掩盖 Redis 调用契约错误。
- `core/utils/task_monitoring.py` 与 `core/utils/task_monitoring_registry.py` 的实现层也已继续退出 broad catch：任务指标注册、原子计数、reset fallback、degraded counter 与 Redis registry helper 当前都改成显式 cache 基础设施异常白名单，只对显式 cache 故障做 fallback / best-effort；编程错误与模糊 runtime 包装会继续冒泡，避免任务监控 helper 继续靠“先兜住再判断”掩盖调用契约问题。
- `core/views/health.py` 的 ready 结果缓存边界也已继续收口：健康检查结果缓存的读写当前只对显式 cache 基础设施异常做 best-effort 跳过，不再因为缓存后端瞬时抖动把 `/health/ready` 自身打成 500；与此同时，`RuntimeError("cache down")` 这类模糊 runtime 包装仍会继续冒泡，避免健康检查缓存层静默掩盖缓存调用契约错误。
- `core/views/health.py` 的 cache ready 检查实现层也已继续退出 broad catch：`_check_cache_ready()` 现在只会把显式 cache 基础设施异常映射成健康检查失败，`AssertionError("broken cache contract")`、`AssertionError("broken cache delete contract")` 这类缓存调用契约错误会继续冒泡，不再被 `/health/ready` 静默伪装成普通缓存不可用。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_health.py` 共 `25 passed`，用于约束 `/health/ready` 的缓存 payload 读写与 cache roundtrip helper 退出 broad catch 后的基础设施降级/契约错误冒泡边界不回退。
- `gameplay/services/manor/core.py` 的建筑升级完成通知与庄园改名 follow-up 也已继续按阶段 3 收口：`finalize_building_upgrade()` 现在把站内信创建与 WebSocket 推送拆成两段，只对显式 `MessageError`、数据库基础设施异常与通知基础设施异常降级，`RuntimeError("message backend down")`、`RuntimeError("ws backend down")` 这类模糊 runtime 包装会继续冒泡；`rename_manor()` 的更名成功消息也已移到 `transaction.on_commit(...)`，避免 follow-up 异常回滚已经提交的庄园名称变更，同时保留同样的显式降级/契约冒泡边界。
- `gameplay/services/manor/core.py` 与 `gameplay/services/technology_helpers.py` 的通知实现层也已继续退出 broad catch：建筑升级完成、科技研究完成与庄园更名成功消息当前都改成显式异常白名单，只对 `MessageError`、数据库基础设施异常与通知基础设施异常做 best-effort；`AssertionError("broken building message contract")`、`AssertionError("broken technology notify contract")`、`AssertionError("broken manor rename message contract")` 这类编程错误会继续冒泡，但不会回滚已提交的升级/更名结果。
- `guilds/services/member_notifications.py` 与 `guilds/services/member.py` 的公会成员 follow-up 也已开始按阶段 3 收口：入帮审批、拒绝、退帮、踢人等 after-commit 站内信当前只对显式 `MessageError` 与数据库基础设施故障做 best-effort；公告 follow-up 入口也不再把 `AssertionError("broken guild announcement contract")`、`RuntimeError("message backend down")` 一类编程/模糊 runtime 错误统一吞掉，公会 follow-up 契约错误会继续冒泡，但不会回滚已经提交的成员状态变更。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_guilds.py` 共 `26 passed`，用于约束公会成员站内信与公告 follow-up 退出 broad catch 后的基础设施降级/契约错误冒泡边界不回退。
- `guilds/services/guild.py` 与 `guilds/services/technology.py` 的事务外公告/消息 follow-up 也已继续按阶段 3 收口：解散帮会后的批量站内信，以及帮会科技升级后的系统公告当前都只对显式数据库基础设施故障做 best-effort 降级；`AssertionError("broken guild disband message contract")`、`AssertionError("broken guild tech announcement contract")` 这类编程错误会继续冒泡，但不会回滚已提交的解散/升级结果。
- `guilds/services/contribution.py`、`guilds/services/technology.py` 与 `guilds/services/warehouse.py` 也已开始按阶段 3 退出 legacy `ValueError` 业务语义：帮会捐赠、科技升级、仓库产出/兑换的业务失败现在统一改走显式 `GuildContributionError / GuildTechnologyError / GuildWarehouseError`；`guilds/views/helpers.execute_guild_action()` 也已优先收口 `GameError`（同时保留 `ValueError` 兼容兜底），避免 view 层继续把 `ValueError` 当作跨层业务语义。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_guild_view_helpers.py tests/test_guilds.py::TestGuildContribution tests/test_guilds_technology_service.py tests/test_guild_warehouse_service.py -q` 分别为 `15 passed`、`10 passed`、`3 passed`；`python -m mypy` 覆盖 `core/exceptions/guild.py`、`guilds/services/technology.py`、`guilds/services/contribution.py`、`guilds/services/warehouse.py` 已通过；并补充 `python -m mypy --check-untyped-defs guilds/services/technology.py` 通过，用于约束帮会业务异常收口与类型边界不回退。
- `guilds/tasks.py` 的任务补偿边界也已开始按阶段 3 收口：每日科技产出的失败列表缓存读写当前只对显式 cache 基础设施故障做 best-effort 降级，不再把 `AssertionError("broken failed-id cache contract")` 这类缓存调用契约错误静默吞掉；同一任务里的单项科技产出现在也只会把显式数据库基础设施故障记为 partial failure 并进入补偿重试，`AssertionError("broken guild production contract")` 一类配置/编程错误会继续冒泡，避免后台把生产契约错误伪装成普通可重试失败。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_guilds_tasks.py` 共 `15 passed`，用于约束公会科技产出补偿缓存与单项产出步骤退出 broad catch 后的基础设施降级/契约错误冒泡边界不回退。
- `guilds/tasks.py` 的其余后台入口也已继续按阶段 3 收口：`process_single_guild_production()`、`guild_tech_daily_production()`、`reset_guild_weekly_stats()`、`cleanup_old_guild_logs()` 与 `cleanup_invalid_guild_hero_pool()` 当前都改成只对白名单内的数据库 / Celery 派发基础设施故障触发 `retry`；`AssertionError("broken guild dispatch contract")`、`AssertionError("broken weekly reset contract")`、`AssertionError("broken hero pool cleanup contract")` 一类编程/契约错误会继续直接冒泡，不再被旧的 `except Exception: raise self.retry(...)` 统一伪装成后台可重试抖动。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy guilds/tasks.py tests/test_guilds_tasks.py` 已通过；`pytest tests/test_guilds_tasks.py -q` 为 `18 passed`，用于约束 `guilds` 后台入口的显式重试白名单、partial failure 补偿与编程错误不重试边界不回退。
- `gameplay/services/manor/provisioning.py` 的庄园初始化补偿链路也已继续按阶段 3 收口：初始免战牌发放与全服邮件补投当前只对显式数据库异常继续 best-effort，`RuntimeError("temporary inventory failure")`、`RuntimeError("global mail bug")` 一类运行时/编程错误会继续冒泡，避免新庄园初始化把补偿 helper 的契约问题静默伪装成“稍后重试即可”。
- `building / technology` 的调度与科技完成通知边界也已继续统一：`schedule_building_completion()`、`schedule_technology_completion_task()` 当前只会在 `gameplay.tasks` 目标模块缺失时降级跳过，嵌套依赖损坏和其它导入故障会继续冒泡；`send_technology_completion_notification()` 也已退出“一锅吞异常”，改为与建筑升级、募兵完成相同的两段式消息/通知口径，只对显式 `MessageError`、数据库基础设施异常与通知基础设施异常降级，模糊 runtime 与契约错误继续暴露。
- `production / forge` 的调度导入边界也已继续和 building/technology 对齐：`stable`、`ranch`、`smithy` 与 `forge_flow_helpers` 的 `schedule_*completion` 入口当前都只会在 `gameplay.tasks` 目标模块缺失时降级跳过，嵌套依赖损坏和其它导入故障不再被 broad catch 吞掉，避免生产/锻造链路把任务模块契约错误误判成可接受的“稍后补偿”场景。
- `production / forge` 的完成通知边界也已继续按阶段 3 收口：`gameplay/services/buildings/stable.py`、`ranch.py`、`smithy.py` 与 `forge_flow_helpers.py` 的事务外站内信 / WebSocket follow-up 当前都改成显式异常白名单，只对 `MessageError`、数据库基础设施异常与通知基础设施异常做 best-effort；`AssertionError("broken production message contract")`、`AssertionError("broken production notify contract")` 这类编程错误会继续冒泡，但不会回滚已经提交的生产完成结果。
- `gameplay/tasks/global_mail.py` 的异步补发入口也已继续按阶段 3 收口：失败庄园 ID 的 cache 读写当前只对显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 做 best-effort，单庄园补发循环也只对白名单内的 `MessageError` / 数据库基础设施故障记为 partial failure；`AssertionError("broken global mail delivery contract")`、`AssertionError("broken global mail failed-id cache get")`、`AssertionError("broken global mail failed-id cache delete")` 一类编程/契约错误会继续直接冒泡，不再被任务层 broad catch 静默吞掉。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/tasks/global_mail.py tests/test_global_mail_tasks.py` 已通过；`pytest tests/test_global_mail_tasks.py -q` 为 `9 passed`，用于约束 `global_mail` 异步补发任务的显式 cache/message/database 异常白名单、partial failure 语义与编程错误冒泡边界不回退。
- `common/utils/celery.py` 的 dedup gate 与 rollback cache 适配也已继续退出 runtime marker 猜测：任务派发入口当前只对显式 broker / cache 基础设施异常做 fail-open 或 rollback 降级，不再把 `RuntimeError("cache down")` 一类 runtime marker 继续当作 dedup cache 故障吞掉，避免任务派发入口把缓存契约错误误判成可忽略的基础设施抖动。
- `core/utils/infrastructure.py` 的 cache helper 总口子也已继续完成收口：`is_expected_cache_infrastructure_error()` 当前只认显式 cache 基础设施异常，不再对 runtime marker 做推断；runtime marker 相关 helper 仅保留为只读兼容工具，不再参与降级判定，避免底层公共判断继续把模糊 runtime 包装误判成缓存故障。
- `gameplay/services/ranking.py` 的玩家排名缓存 helper 也已继续退出 runtime marker 猜测：`get_player_rank()` 当前只对显式 cache 基础设施异常做 best-effort 降级，不再把 `RuntimeError("cache down")` 一类 runtime marker 继续当作缓存故障吞掉，避免全局侧边栏排名读路径把缓存契约错误误判成短暂缓存抖动。
- `gameplay/services/utils/messages.py` 的共享消息 cache helper 也已继续退出 broad catch：未读消息数缓存与消息清理节流里的 `cache.get/set/add/delete/delete_many` 当前都改成显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 白名单，只对显式缓存基础设施故障做 best-effort / fallback；`RuntimeError("cache set failed")`、`RuntimeError("cache delete failed")`、`RuntimeError("cache delete_many failed")` 这类编程或契约错误会继续冒泡，避免消息读写链路继续靠“先吞再判”掩盖缓存调用问题。
- `gameplay/selectors/recruitment.py` 的招募大厅 selector cache helper 也已继续退出 broad catch：招募大厅上下文缓存的 `cache.get/set` 当前都改成显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 白名单，只对显式缓存基础设施故障做 best-effort 降级；`RuntimeError("cache set failed")` 一类编程或契约错误会继续冒泡，避免 `guest recruitment` 读路径继续靠“先吞再判”掩盖缓存调用问题。
- `gameplay/selectors/home.py` 与 `gameplay/selectors/sidebar.py` 的首页/侧边栏 selector cache helper 也已继续退出 broad catch：首页资源时产缓存和侧边栏排名缓存的 `cache.get/set` 当前都改成显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 白名单，只对显式缓存基础设施故障做 best-effort 降级；`RuntimeError("cache set failed")`、`RuntimeError("cache write failed")` 一类编程或契约错误会继续冒泡，避免首页与全局侧边栏读路径继续靠“先吞再判”掩盖缓存调用问题。
- `gameplay/selectors/stats.py` 的全局统计 selector 实现层也已继续退出 broad catch：总用户数/在线人数缓存的 `cache.get/set/delete`、缓存 miss 回退与 Redis 在线人数读取当前都改成显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` / `INFRASTRUCTURE_EXCEPTIONS` 白名单，只对显式 cache / Redis 基础设施故障做 fallback；`RuntimeError("cache write failed")`、`RuntimeError("redis down")` 这类编程或契约错误会继续冒泡，避免全站统计读路径继续靠“先吞再判”掩盖缓存与 Redis 调用问题。
- `accounts/utils.py` 的单会话登录缓存/锁适配层也已继续退出 runtime marker 猜测：活动 session 缓存读写与登录锁 fallback 当前只对显式 cache 基础设施异常降级，不再把 `RuntimeError("cache down")` 一类 runtime marker 继续当作缓存故障吞掉，避免登录主链路把缓存契约错误误判成可接受的本地锁 fallback。
- `websocket/consumers/online_stats.py` 的在线人数 consumer 也已继续退出 runtime marker 猜测：广播去抖锁、在线人数缓存读写和总人数缓存 helper 当前只对显式 cache 基础设施异常做 fallback / best-effort 降级，不再把 `RuntimeError("cache down")` 一类 runtime marker 继续当作缓存故障吞掉；heartbeat / get_stats 里的重复 broad catch 也已收紧，避免在线态读路径静默掩盖契约错误。
- `websocket/consumers/world_chat.py` 的显示名缓存 helper 也已继续退出 runtime marker 猜测：世界频道用户显示名缓存当前只对显式 cache 基础设施异常做 best-effort 降级，不再把 `RuntimeError("cache down")` 一类 runtime marker 继续当作缓存故障吞掉，避免聊天读路径静默掩盖缓存契约错误。
- `websocket/backends/chat_history.py` 的聊天历史 Redis helper 也已继续退出 broad catch：消息落历史与补偿删除当前都改成显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 白名单，只对显式缓存基础设施故障抛 `WorldChatInfrastructureError` 触发 fail-closed；`RuntimeError("cache down")`、`RuntimeError("cache delete failed")` 一类编程或契约错误会继续冒泡，不再依赖“先吞再 helper 判断”的旧降级写法。
- `core/middleware/single_session.py` 的单会话校验链路也已继续退出 runtime marker 猜测：active-session 缓存读写、验证 marker 写入与 unavailable 包装当前只对显式数据库 / cache 基础设施异常降级，不再把 `RuntimeError("cache add down")` 一类 runtime marker 继续当作平台故障处理，避免单会话中间件把缓存契约错误误判成可 fail-open / fail-closed 的系统抖动。
- `accounts/login_runtime.py` 的登录限流缓存适配层也已继续退出 runtime marker 猜测：登录尝试计数、锁 TTL、锁读写与失败计数当前只对显式 cache 基础设施异常做 local fallback / fail-closed 降级，不再把 `RuntimeError("cache down")`、`RuntimeError("cache add down")` 一类 runtime marker 继续当作缓存故障吞掉，避免登录主链路把缓存契约错误误判成可接受的限流降级。
- `trade/services/cache_resilience.py` 这层交易通用 cache 适配也已继续退出 runtime marker 猜测：`best_effort_cache_get/set/add/delete()` 当前只对显式 cache 基础设施异常做 best-effort 降级，不再把 `RuntimeError("cache read failed")`、`RuntimeError("cache add failed")`、`RuntimeError("cache delete failed")` 一类 runtime marker 继续当作缓存故障吞掉，避免交易供给/拍卖链路静默掩盖缓存契约错误。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_message_attachments.py` 共 `14 passed`，用于约束消息缓存 helper 的基础设施降级与编程错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_recruitment_hall_cache.py` 共 `6 passed`，用于约束招募大厅 selector cache helper 的基础设施降级与 runtime/契约错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_home_selector_validation.py`、`tests/test_context_processors.py` 共 `23 passed`，用于约束首页/侧边栏 selector cache helper 的基础设施降级与 runtime/契约错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_context_processors.py` 共 `19 passed`，用于约束全局统计 selector 的 cache/Redis 基础设施降级与 runtime/契约错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_websocket_world_chat_history_internals.py` 共 `13 passed`，用于约束世界频道历史写入/补偿删除 helper 的基础设施降级与 runtime/契约错误冒泡边界不回退。
- `world chat` 的 WebSocket 主链也已继续按阶段 3 收口：`websocket/consumers/world_chat.py` 的本地 display-name cache helper 已改成只对显式缓存基础设施异常降级，不再走 broad catch + 运行时判断；`websocket/backends/chat_history.py` 的历史解析、Lua trim fallback 与尾部清理逻辑也已去掉“unexpected error 记录后继续吞掉”的 broad catch，当前只会跳过显式损坏的历史条目，`RuntimeError("history parse bug")`、`RuntimeError("trim bug")` 一类契约/编程错误会直接冒泡，避免世界频道主链把历史读写 helper 的内部错误静默伪装成普通历史降级。
- `single session` 的 HTTP / WebSocket 守卫链也已继续按阶段 3 收口：`core/middleware/single_session.py` 与 `websocket/consumers/session_guard.py` 当前都只对显式数据库 / cache 基础设施异常包装成 `SessionValidationUnavailable` / `WebSocketSessionValidationUnavailable`；`RuntimeError("cache add down")`、`AssertionError("broken session payload contract")`、`AssertionError("broken single-session cache read contract")` 这类运行时/契约错误会继续直接冒泡，避免单会话守卫把内部校验逻辑问题伪装成“后端暂时不可用”。
- `online presence` 的 HTTP touch 刷新链也已继续按阶段 3 收口：`gameplay/services/online_presence.py` 已去掉“失败后清理 touch key 再原样重抛”的 broad catch，当前改由显式基础设施异常降级 + `finally` 补偿清理驱动；`RuntimeError("redis down")`、`AssertionError("broken presence cache delete contract")` 一类运行时/契约错误仍会在回收 touch key 后继续冒泡，避免在线人数刷新 helper 静默掩盖 Presence/Cache 调用契约问题。
- `guests/views/equipment.py` 的装备页 gear-options 缓存 helper 也已继续退出 runtime marker 猜测：gear options 读写和装备变更后的缓存失效当前只对显式 cache 基础设施异常做 best-effort 降级，不再把 `RuntimeError("cache down")` 一类 runtime marker 继续当作缓存故障吞掉，避免门客装备页静默掩盖缓存契约错误。
- `guests/views/equipment.py` 的装备 / 卸装页面入口也已继续按阶段 3 收口：`equip_view()` 与 `unequip_view()` 当前仅保留显式 `GameError` 业务提示和 `DatabaseError` 页面降级，不再额外用 broad catch 包一层“unexpected view error”；`RuntimeError("boom")`、`ValueError("legacy equip")` 一类编程/契约错误会继续直接冒泡，避免门客装备页把服务调用契约问题伪装成普通页面失败。
- `trade` 的过期挂单与拍卖结算边界也已继续按阶段 3 收口：`trade/services/market_expiration.normalize_expire_limit()` 对非法 `limit` 参数不再抛裸 `ValueError`，改走显式 `TradeValidationError`；`trade/services/auction/rounds.settle_auction_round()` 对 `settle_slot_func` 返回值契约错误也不再吞成“可恢复的流拍补偿”，当前会直接抛显式 `AssertionError`，避免交易后台把内部结算契约错误伪装成普通业务失败。
- `trade/services/auction/rounds.py` 的拍卖通知与“结算失败后强制流拍恢复”边界也已继续收紧：`_safe_notify_user()` 当前只对显式通知基础设施故障做 best-effort 降级，`RuntimeError("ws backend down")` 一类模糊 runtime 包装会继续冒泡；`_send_winning_notification_vickrey()` 的消息创建 fallback 与 `_mark_slot_unsold_after_failure()` 的恢复补偿当前也都只对白名单内的消息/数据库基础设施故障降级，`AssertionError`、`RuntimeError("refund contract bug")` 这类编程/契约错误会继续冒泡，避免拍卖后台把通知/补偿 helper 的逻辑错误伪装成普通 unrecovered failure。
- `trade/services/auction/rounds.py` 的拍卖位结算外层也已继续按阶段 3 收口：`settle_auction_round()` 当前只对显式数据库基础设施故障走“强制流拍恢复”补偿；`RuntimeError("boom")` 一类编程错误不再被外层批处理统一吞成 recovered failure，而会让轮次保持 `SETTLING` 并继续冒泡，避免拍卖后台把 `_settle_slot()` 契约错误伪装成普通可恢复结算异常。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_trade_auction_rounds.py` 共 `29 passed`，用于约束拍卖结算通知、消息 fallback 与强制流拍恢复退出 broad catch 后的基础设施降级/契约错误冒泡边界不回退。
- `trade/tasks.py` 的后台入口也已继续按阶段 3 收口：商店日刷、过期挂单扫描、拍卖结算与新轮次创建当前都改成只对显式数据库基础设施故障做 partial failure / retry / fallback；`AssertionError("broken slot count contract")`、`AssertionError("broken create round contract")` 一类编程/契约错误会继续冒泡，避免交易后台任务把主链契约问题伪装成普通重试或静默降级。
- `trade/view_helpers.py` 的页面动作入口也已继续按阶段 3 收口：`execute_trade_action()` 当前不再通过 broad catch + `classify_view_error()` 动态分类所有异常，而是只对白名单内的 `GameError` / 数据库基础设施异常做页面提示；`RuntimeError("broken exchange contract")` 一类编程/契约错误会继续直接冒泡，避免交易页面层把服务调用契约问题伪装成普通交易失败。
- `map` 的 `refresh_raid_activity_api` 已退出 legacy `ValueError` 兼容：写入口默认只把显式 `GameError` 当已知业务错误，裸 `ValueError` 继续冒泡，避免 view 层把程序/契约错误伪装成 400。
- `map` 的目标庄园解析 helper 也已继续收紧：`gameplay/views/map._target_manor_or_error()` 在参数已通过 `safe_positive_int()` 归一化后，不再额外吞掉 `ValueError/TypeError`，查库阶段的异常改为继续冒泡。
- `core` 的 legacy view 装饰器也已退出 `ValueError` 业务语义：`core/decorators.handle_game_errors` 不再捕获裸 `ValueError`，避免新代码继续把 `ValueError` 当跨层业务错误。
- `core` 的错误消息清洗入口也已退出 `ValueError` 业务语义：`core/utils/validation.sanitize_error_message()` 不再直接回显裸 `ValueError` 文案，未显式归类的异常统一退回通用失败消息，避免程序错误泄漏到页面层。
- `core` 的 rate limit 工具也已开始退出裸 `ValueError`：`core/utils/rate_limit._validate_rate_limit_options()` 对非法 `limit/window_seconds` 配置不再抛 `ValueError`，改走显式内部调用契约错误 `AssertionError`。
- `resources` 服务也已开始退出裸 `ValueError`：`gameplay/services/resources._handle_unknown_resource()` 在 debug 下对未知资源类型改走显式内部调用契约错误 `AssertionError`，非 debug 环境继续记录错误并跳过非法资源，不再把该问题伪装成业务异常。
- `chat` 服务入口也已继续按阶段 3 收口：`gameplay/services/chat.consume_trumpet()` 当前只对显式库存不足与数据库基础设施故障返回业务失败；`ValueError`、`AssertionError`、`RuntimeError` 一类契约/编程错误会继续冒泡，不再被世界频道入口伪装成“扣除小喇叭失败，请稍后重试”。
- `chat` 的退款补偿边界也已继续按阶段 3 收口：`gameplay/services/chat.refund_trumpet()` 当前只对显式数据库/基础设施异常做 best-effort 失败返回，`RuntimeError("refund bug")` 一类运行时/编程错误会继续冒泡，避免世界频道补偿路径静默掩盖库存回补契约问题。
- `notifications / cache resilience` 共享 helper 也已继续按阶段 3 收口：`gameplay/services/utils/notifications.py` 与 `trade/services/cache_resilience.py` 已去掉“unexpected error 先记录再原样抛出”的 broad catch，当前只对显式通知/缓存基础设施异常执行降级或包装；`AssertionError("broken cache contract")`、`RuntimeError("bad payload")` 一类契约/编程错误会直接冒泡，避免共享 helper 继续制造额外的日志噪音并掩盖真正的错误边界。
- `battle` 的战利品分发 helper 也已继续收紧：`battle/rewards.py` 的 `_in_atomic_block()` 已去掉 broad catch，不再把事务状态探测里的 `RuntimeError("connection probe failed")` 一类运行时/契约错误静默降级成“按非事务路径发奖励”；战利品授予链路会继续暴露原始错误，避免 battle 奖励辅助层误判事务边界。
- `battle` 的兵种模板缓存失效 helper 也已继续收紧：`battle/troops.py` 的 `invalidate_troop_templates_cache()` 已去掉对 `load_troop_templates_from_yaml.cache_clear()` 的 broad catch，不再把 `RuntimeError("cache clear bug")` 一类 reload/契约错误静默吞掉；兵种模板缓存失效链路会继续暴露 helper 契约问题，避免 battle 配置刷新路径误报为普通 best-effort 成功。
- `battle/tasks.py` 的异步战报生成入口也已继续按阶段 3 收口：`generate_report_task()` 当前只对显式 `GameError` 做非重试退出、只对显式数据库基础设施故障触发 Celery retry；`RuntimeError("boom")`、`ValueError("bad input")` 一类编程/契约错误会继续冒泡，不再被后台任务统一伪装成“稍后重试”。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_battle_tasks_generate_report_task.py` 共 `7 passed`，用于约束战报生成任务的业务失败、基础设施重试与编程错误冒泡边界不回退。
- `gameplay/tasks/missions.py` 与 `gameplay/tasks/pvp.py` 这批旧 Celery 入口也已继续按阶段 3 收口：任务完成/扫描入口当前已补齐 `MissionTaskRetryRequested`、`PvpTaskRetryRequested` 等显式重试标记，并只对白名单内的数据库基础设施故障或显式重试请求调用 `self.retry(...)` / 继续 scan fallback；`AssertionError("broken mission finalize contract")`、`AssertionError("broken scout finalize contract")`、`AssertionError("broken raid finalize contract")` 一类编程/契约错误会继续直接冒泡，不再被旧的 `except Exception: raise self.retry(...)` 统一伪装成可重试后台故障。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/tasks/missions.py gameplay/tasks/pvp.py tests/test_gameplay_tasks.py` 已通过；`pytest tests/test_gameplay_tasks.py -q` 为 `28 passed`，用于约束 `mission / scout / raid` 任务入口的显式重试白名单、scan fallback 与编程错误不重试边界不回退。
- `gameplay/tasks/recruitment.py`、`gameplay/tasks/buildings.py`、`gameplay/tasks/production.py` 与 `gameplay/tasks/technology.py` 这批资源/升级 Celery 入口也已继续按阶段 3 收口：当前已补齐 `RecruitmentTaskRetryRequested`、`BuildingTaskRetryRequested`、`ProductionTaskRetryRequested`、`TechnologyTaskRetryRequested` 等显式重试标记，并让 `count_finalized_records()` 支持只吞显式基础设施白名单；这样募兵、建筑升级、马厩/牧场/冶炼/锻造产出与科技升级任务现在都只对白名单内的数据库基础设施故障或显式重试请求调用 `self.retry(...)` / 继续 scan fallback，`AssertionError("broken ... finalize contract")` 一类编程/契约错误会继续直接冒泡，不再被旧的 `except Exception: raise self.retry(...)` 或 scan helper 静默吞掉。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/tasks/_scheduled.py gameplay/tasks/recruitment.py gameplay/tasks/buildings.py gameplay/tasks/production.py gameplay/tasks/technology.py tests/test_gameplay_tasks.py` 已通过；`pytest tests/test_gameplay_tasks.py -q` 为 `37 passed`，用于约束 `troop recruitment / building / production / technology` 任务入口的显式重试白名单、scan fallback 与编程错误不重试边界不回退。
- `guests/tasks.py` 的训练、招募、被动回血与每日忠诚度后台入口也已继续按阶段 3 收口：这些入口当前已退出 `except Exception + _is_expected_task_error()` 的兜底模式，改成只对白名单内的数据库基础设施故障做 retry / scan fallback；`_process_defection_batch()` 里的叛逃通知也已收成显式 `MessageError + DATABASE_INFRASTRUCTURE_EXCEPTIONS` best-effort 白名单，`RuntimeError("message bug")`、`AssertionError("broken guest recruitment finalize contract")` 一类编程/契约错误会继续直接冒泡，不再被后台任务或叛逃消息补偿链静默吞掉。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy guests/tasks.py tests/test_gameplay_tasks.py tests/test_guests_defection.py tests/test_guest_loyalty_service.py` 已通过；`pytest tests/test_gameplay_tasks.py tests/test_guests_defection.py tests/test_guest_loyalty_service.py -q` 为 `52 passed`，用于约束 `guest training / guest recruitment / passive hp recovery / daily loyalty / defection message` 这批后台入口的基础设施重试、消息降级与编程错误冒泡边界不回退。
- `gameplay/services/raid/combat/travel.py` 的保护期遣返链路也已继续按阶段 3 收口：`resolve_complete_raid_task()` 已去掉无收益的导入 broad catch，当前只在 `gameplay.tasks` 目标模块缺失时降级；`_retreat_raid_run_due_to_blocked_target()` 的遣返通知也已改成显式 `MessageError + DATABASE_INFRASTRUCTURE_EXCEPTIONS` 白名单，`RuntimeError("message backend down")`、`AssertionError("broken blocked-target message contract")` 一类编程/契约错误会继续直接冒泡，不再依赖 broad catch + helper 判断。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/services/raid/combat/travel.py tests/test_raid_combat_battle.py` 已通过；`pytest tests/test_raid_combat_battle.py -k "resolve_complete_raid_task or retreat_raid_run_due_to_blocked_target" -q` 为 `5 passed`，用于约束 `raid` 保护期遣返链路的导入降级、消息降级与编程错误冒泡边界不回退。
- `gameplay/tasks/production.py` 的 `complete_work_assignments_task()` 与 `guests/signals.py` 的模板缓存失效 signal 也已继续按阶段 3 收口：打工任务入口已去掉无收益的 broad catch，`AssertionError("broken work completion contract")` 一类编程/契约错误会直接冒泡；`clear_guest_template_cache()` 当前也只对白名单内的缓存基础设施故障做 best-effort 降级，`AssertionError("broken guest template cache contract")` 一类编程错误会继续直接冒泡，不再被 signal 层静默吞掉。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/tasks/production.py guests/signals.py tests/test_gameplay_tasks.py tests/test_guest_recruitment_service.py` 已通过；`pytest tests/test_gameplay_tasks.py tests/test_guest_recruitment_service.py -k "complete_work_assignments_task or guest_template_signal" -q` 为后续这两条入口的回归约束补上了“编程错误冒泡 / 缓存基础设施降级”边界。
- `gameplay/tasks/_scheduled.py` 也已继续按阶段 3 收口：`count_finalized_records()` 当前不再保留“`expected_exceptions=None` 时吞任意异常”的历史兼容分支，所有 scan fallback 调用方都必须显式传入基础设施异常白名单；这样公共调度 helper 本身也不再携带 broad catch 兜底口子，进一步避免新任务入口误回退到“编程错误静默吞掉”的旧模式。
- `core/middleware/access_log.py` 也已继续按阶段 3 收口：访问日志 middleware 已去掉仅用于记录异常名的 broad catch，改为在 `finally` 里直接读取当前异常信息；这样既保留了“记录异常类型再继续抛出”的观测语义，也不再依赖额外的 `except Exception` 包裹请求主链。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy core/middleware/access_log.py tests/test_access_log_middleware.py` 已通过；`pytest tests/test_access_log_middleware.py -q` 为 `2 passed`，用于约束访问日志 middleware 的控制字符清洗与异常名记录语义不回退。
- `guests/management/commands/load_guest_templates.py` 的头像与英雄目录导入边界也已继续按阶段 3 收口：模板头像同步当前只对白名单内的 `OSError` 图片/存储失败做 best-effort 警告，`AssertionError("broken avatar contract")` 一类编程错误会继续直接冒泡；英雄目录聚合也已退出 broad catch，当前只对显式 `CommandError / OSError / UnicodeDecodeError / JSONDecodeError` 做逐文件降级，错误 payload 形状会按用户数据问题给出 warning，而代码契约错误不会再被管理命令静默吞掉。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy guests/management/commands/load_guest_templates.py tests/test_load_guest_templates_command.py` 已通过；`pytest tests/test_load_guest_templates_command.py -q` 为 `7 passed`，用于约束头像导入与英雄目录聚合链路的 recoverable 文件错误降级、坏 payload warning 与编程错误冒泡边界不回退。
- `阶段 3` 的类型门禁豁免面也已继续收缩：`guests.views.items`、`guests.views.skills`、`guests.views.roster`、`guests.views.equipment`、`guests.views.training` 与 `guests.management.commands.load_guest_templates` 已从通配型 `ignore_errors` 豁免里挪出，开始接受真实 `mypy` 检查；这样门客页的药品/技能/辞退/装备/培养入口，以及门客模板导入命令，不再只是“文档里说过跑过 mypy”，而是配置层面已经进入默认类型门禁覆盖范围。
- `阶段 3` 的类型门禁也已继续从“文档存在”落到“热点路径真实生效”：`core/utils/infrastructure.py` 新增 `combine_infrastructure_exceptions()`，并已为 `trade / guilds / gameplay / battle / core` 多个热点链路的异常白名单常量补齐 `InfrastructureExceptions` 显式类型，避免 `mypy` 把 `except SOME_EXCEPTIONS` 误判成普通对象元组；当前这些链路的消息、通知、缓存与任务异常白名单已能被静态检查直接约束。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy` 针对 `guilds/services/member_notifications.py`、`trade/services/market_notification_helpers.py`、`battle/tasks.py`、`core/views/health.py`、`trade/services/auction/bidding.py`、`trade/services/auction/rounds.py`、`gameplay/services/buildings/forge_flow_helpers.py`、`gameplay/services/technology_helpers.py`、`gameplay/services/buildings/smithy.py`、`gameplay/services/buildings/ranch.py`、`gameplay/services/buildings/stable.py`、`gameplay/services/manor/core.py`、`gameplay/services/utils/notifications.py`、`gameplay/services/chat.py`、`trade/services/cache_resilience.py`、`trade/tasks.py`、`core/utils/infrastructure.py` 均已通过；相关回归 `tests/test_market_notification_helpers.py`、`tests/test_trade_auction_bidding.py`、`tests/test_trade_auction_rounds.py`、`tests/test_trade_tasks.py`、`tests/test_guilds.py`、`tests/test_health.py`、`tests/test_battle_tasks_generate_report_task.py`、`tests/test_trade_bank_service.py`、`tests/test_guilds_technology_service.py`、`tests/test_notification_utils.py`、`tests/test_chat_service.py`、`tests/test_trade_cache_resilience.py` 共形成阶段 3 热点验证闭环。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy websocket/consumers/world_chat.py websocket/backends/chat_history.py tests/test_world_chat_consumer.py tests/test_websocket_world_chat_history_internals.py` 已通过；`tests/test_world_chat_consumer.py` 与 `tests/test_websocket_world_chat_history_internals.py` 共 `34 passed`，用于约束世界频道 WebSocket 主链、历史读写与补偿路径的基础设施降级/契约错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy core/middleware/single_session.py websocket/consumers/session_guard.py tests/test_single_session_middleware.py tests/test_websocket_session_guard.py` 已通过；`tests/test_single_session_middleware.py` 与 `tests/test_websocket_session_guard.py` 共 `15 passed`，用于约束单会话 HTTP middleware 与 WebSocket session guard 的基础设施 unavailable / 契约错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/services/online_presence.py tests/test_context_processors.py` 已通过；`pytest tests/test_context_processors.py -k online_presence_middleware -q` 为 `3 passed`，用于约束在线人数 HTTP touch 刷新链的基础设施降级、touch key 补偿清理与契约错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy trade/view_helpers.py tests/trade/test_trade_bank_views.py` 已通过；`pytest tests/trade/test_trade_bank_views.py -q` 为 `11 passed`，用于约束交易页动作 helper 的业务失败、基础设施降级与编程错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy trade/services/auction/rounds.py tests/test_trade_auction_rounds.py` 已通过；`pytest tests/test_trade_auction_rounds.py -q` 为 `30 passed`，用于约束拍卖结算外层的基础设施恢复补偿与编程错误冒泡边界不回退。
- `2026-03-22` 已启动一轮阶段 5“超大测试文件收缩”试点：`tests/test_trade_auction_rounds.py` 已收口为薄入口文件，并按“轮次生命周期 / 拍卖位结算 / 交付与通知”拆到 `tests/trade_auction_rounds/` 子模块；兼容入口路径保持不变，`pytest tests/test_trade_auction_rounds.py -q` 仍为 `30 passed`，用于约束测试资产拆分后原有回归覆盖不回退。
- `2026-03-22` 已继续推进阶段 5“超大测试文件收缩”第二个试点：`tests/test_inventory_guest_items.py` 已收口为薄入口文件，并按“重置类道具 / 升阶道具 / 灵魂融合”拆到 `tests/inventory_guest_items/` 子模块；兼容入口路径保持不变，`pytest tests/test_inventory_guest_items.py -q` 为 `16 passed`，用于约束测试资产拆分后原有回归覆盖不回退。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_guest_summon_card.py -q` 为 `22 passed`，用于约束门客召唤卡、资源包、宝箱配置与免战牌 `duration` 在 `effect_payload / choices / required_items / exclusive_template_keys / resources / gear_keys / skill_book_keys / *_chance / duration / silver_min / silver_max` 坏掉时改走显式 `ItemNotConfiguredError`，不再静默退化成空权重、免费召唤、“永不掉落”或运行时类型错误。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_treasury_move_service_contracts.py -q` 为 `2 passed`，用于约束藏宝阁移入/移回服务在绕过 view 层时也会把非正数量视为显式内部调用契约错误，而不是静默改库存。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_guest_recruitment_flow_helpers.py -q` 为 `25 passed`，用于约束 `guest recruitment` 的 `draw_count / duration / seed / cost / result_count / cooldown / daily limit` helper 在类型错误和非正数输入下改走显式 `AssertionError`，不再静默纠偏成 `1`、`0`、非法种子、静默归零结果数或默认限额。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_mission_sync_report.py -q` 为 `15 passed`，用于约束 `mission` 同步战报 helper 在 defense/offense 场景下不再静默吞掉坏掉的 `enemy_guests / enemy_troops / guest_level / drop_table / enemy_technology / guest_skills` 配置，而是改走显式 `AssertionError`。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_mission_finalization_helpers.py -q` 为 `7 passed`，用于约束 `mission` 结算 helper 在读取坏掉的 `report.losses / hp_updates / team entry / troop_loadout / report.drops` 载荷时改走显式 `AssertionError`，不再静默跳过或吞掉损坏战报数据。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_mission_salvage_side_filter.py -q` 为 `5 passed`，用于约束 `mission` 防守掉落补发 helper 在 `report.drops / drop_table` 配置损坏时改走显式 `AssertionError`，不再静默把坏配置当空表处理。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_mission_drops_service.py -q` 为 `12 passed`，用于约束 `mission` 掉落发放链在负数掉落、布尔值数量、坏 key 和缺失物品模板 key 场景下改走显式 `AssertionError`，不再静默少发或吞掉坏奖励。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_mission_refresh_async.py -q` 为 `30 passed`，用于约束 `mission` launch helper、refresh 配置 helper 与完成任务调度入口在 offense 场景下不再静默吞掉坏掉的 `enemy_guests / enemy_troops / enemy_technology / drop_table / MISSION_REFRESH_SYNC_MAX_RUNS / return_at` 配置，而是改走显式 `AssertionError` 或显式契约错误。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_mission_attempts_service.py -q` 为 `3 passed`，用于约束 `mission card` 对应的额外次数 service 在非正 `count`、坏掉的 `daily_limit` 与非法额外次数输入下改走显式 `AssertionError`，不再静默入库、累加或放宽次数上限。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_guest_view_error_boundaries.py -k "candidate_accept or magnifying_glass" -q` 为 `3 passed, 38 deselected`，用于约束 `guest recruitment` 页面动作运行时退出动态异常分类后，业务失败仍走 400、数据库/基础设施失败仍走 500、编程错误继续冒泡的边界不回退。
- `2026-03-23` 已继续补一轮阶段 3 聚焦验证：`pytest tests/test_guest_recruitment_finalize_helpers.py -q` 为 `8 passed`，用于约束 `guest recruitment` 完成链路的 capacity helper 在负数 `available_slots`、坏掉的 `guest_capacity / retainer_capacity` 以及“当前门客数已超过容量”的脏状态场景下改走显式 `AssertionError`，不再静默夹成 `0` 或继续吞坏容量状态。
- `2026-03-23` 已继续补一轮阶段 2/3 交界验证：`DJANGO_TEST_USE_ENV_SERVICES=1 REDIS_URL=redis://127.0.0.1:6379 REDIS_BROKER_URL=redis://127.0.0.1:6379/0 REDIS_RESULT_URL=redis://127.0.0.1:6379/0 REDIS_CHANNEL_URL=redis://127.0.0.1:6379/1 REDIS_CACHE_URL=redis://127.0.0.1:6379/2 python -m pytest tests/test_mission_concurrency_integration.py tests/test_guest_recruitment_concurrency_integration.py -q` 为 `6 passed, 1 skipped`，用于约束 `mission / guest recruitment` 当前这轮契约收口没有破坏关键并发状态机、行锁与真实 Redis 协同语义。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy guests/views/equipment.py tests/test_guest_item_view_validation.py` 已通过；`pytest tests/test_guest_item_view_validation.py -k gear_options_view -q` 为 `4 passed`，用于约束装备页 gear-options cache helper 的缓存基础设施降级与运行时/契约错误冒泡边界不回退。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy guests/views/equipment.py tests/test_guest_view_error_boundaries.py tests/test_guest_item_view_validation.py` 已通过；`pytest tests/test_guest_view_error_boundaries.py tests/test_guest_item_view_validation.py -k 'equip_view or unequip_view' -q` 为 `11 passed`，用于约束门客装备 / 卸装页面入口的业务失败、数据库降级与运行时/契约错误冒泡边界不回退。
- `guests/views/training.py` 的训练、经验道具与属性加点入口也已继续按阶段 3 收口：`TrainView.post()`、`use_experience_item_view()`、`allocate_points_view()` 当前仅保留显式 `GameError` 业务提示与 `DatabaseError` 页面降级，不再额外用 broad catch 包装“unexpected view error”；`RuntimeError("boom")`、`ValueError("legacy train")` 一类编程/契约错误会继续直接冒泡，避免门客培养页把服务调用契约问题伪装成普通页面失败。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy guests/views/training.py tests/test_guest_view_error_boundaries.py tests/test_guest_item_view_validation.py` 已通过；`pytest tests/test_guest_view_error_boundaries.py -k "train or use_experience_item_view or allocate_points_view" -q` 为 `11 passed`，`pytest tests/test_guest_item_view_validation.py -k "use_experience_item_view" -q` 为 `3 passed`，用于约束门客训练 / 经验道具 / 属性加点页面入口的业务失败、数据库降级与运行时/契约错误冒泡边界不回退。
- `gameplay/views/messages.py` 的附件领取入口也已继续按阶段 3 收口：`claim_attachment_view()` 当前仅保留显式 `GameError` 业务失败与 `DatabaseError` 页面/JSON 降级，不再额外用 broad catch 包装全部异常；`RuntimeError("boom")` 一类编程/契约错误会继续直接冒泡，避免消息页把附件领取链路的内部错误伪装成普通领取失败。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy gameplay/views/messages.py tests/test_message_views.py` 已通过；`pytest tests/test_message_views.py -q` 为 `13 passed`，用于约束消息附件领取入口的业务失败、数据库降级与运行时错误冒泡边界不回退。
- `guests/views/items.py`、`guests/views/skills.py` 与 `guests/views/roster.py` 的药品、学技、遗忘技能与辞退入口也已继续按阶段 3 收口：这些页面入口当前仅保留显式 `GameError` 业务提示与 `DatabaseError` 页面/JSON 降级，不再额外用 broad catch 包装“unexpected view error”；`RuntimeError("boom")`、`ValueError("legacy dismiss")` 一类编程/契约错误会继续直接冒泡，避免门客页把服务调用契约问题伪装成普通页面失败。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy guests/views/items.py guests/views/skills.py guests/views/roster.py tests/test_guest_view_error_boundaries.py tests/test_guest_item_view_validation.py` 已通过；`pytest tests/test_guest_view_error_boundaries.py -k "use_medicine_item_view or learn_skill_view or forget_skill_view or dismiss_guest_view" -q` 为 `13 passed`，`pytest tests/test_guest_item_view_validation.py -k "use_medicine_item_view or learn_skill_view or forget_skill_view" -q` 为 `6 passed`，用于约束门客药品 / 技能 / 辞退页面入口的业务失败、数据库降级与运行时/契约错误冒泡边界不回退。
- `core/utils/rate_limit.py` 也已继续按阶段 3 收口：`_safe_identifier()` 不再把 `key_func` 的任意异常吞成默认标识 fallback，`_get_rate_limit_count()` 也已去掉 broad catch，当前只对显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 返回 503 / busy 响应；`RuntimeError("boom")`、`RuntimeError("cache down")`、`AssertionError("broken cache contract")` 一类编程/契约错误会继续直接冒泡，避免限流入口把 key 生成或 cache 调用问题误判成普通缓存抖动。
- `core/utils/infrastructure.py` 的可选依赖导入 helper 也已继续按阶段 3 收口：`_append_optional_exception()` 当前只会忽略显式 `ImportError` / `AttributeError`，模块内部的 `RuntimeError("broken optional import contract")` 一类编程/契约错误会继续直接冒泡，不再被底层公共 helper 静默吞掉。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy core/utils/rate_limit.py core/utils/infrastructure.py tests/test_rate_limit.py tests/test_rate_limit_safe_methods.py tests/test_infrastructure_utils.py` 已通过；`pytest tests/test_rate_limit.py tests/test_rate_limit_safe_methods.py tests/test_infrastructure_utils.py -q` 为 `26 passed`，用于约束公共限流 helper 与基础设施异常白名单构建 helper 的基础设施降级和编程错误冒泡边界不回退。
- `core/utils/cache_lock.py` 也已继续按阶段 3 收口：缓存锁的 atomic release、compare-delete fallback、ownership check、delete 与 acquire 入口当前都改成显式 `CACHE_INFRASTRUCTURE_EXCEPTIONS` 白名单；`RuntimeError("cache down")`、`AssertionError("broken cache get contract")`、`AssertionError("broken cache delete contract")` 一类运行时/契约错误会继续直接冒泡，不再依赖 broad catch + helper 判断，避免公共锁适配层继续掩盖 cache 调用契约问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy core/utils/cache_lock.py tests/test_cache_lock_utils.py` 已通过；`pytest tests/test_cache_lock_utils.py -q` 为 `13 passed`，用于约束公共缓存锁适配层的 fallback、fail-closed 与编程错误冒泡边界不回退。
- `core/views/health.py` 也已继续按阶段 3 收口：channel layer、Celery broker / workers / beat / roundtrip 这些 ready check 当前都改成只对白名单内的 `HealthCheckFailure` 与显式基础设施异常做 503 降级；`AssertionError("broken channel layer contract")`、`AssertionError("broken roundtrip forget contract")`、缓存 roundtrip 清理里的契约错误会继续直接冒泡，`health` 页不再依赖 broad catch 把编程错误统一伪装成普通健康检查失败。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy core/views/health.py tests/test_health.py` 已通过；`pytest tests/test_health.py -q` 为 `27 passed`，用于约束 ready 检查缓存、channel layer、Celery roundtrip 与内部契约错误冒泡边界不回退。
- `websocket/consumers/world_chat.py` 的发送主链补偿语义也已继续按阶段 3 细化：世界频道在“已消费小喇叭后发布失败”时仍会执行退款 / 删除历史的补偿，但当前只会在显式基础设施故障上记录 `WORLD_CHAT_REFUND` degradation；`RuntimeError("bug")` 一类编程/契约错误虽然仍会补偿后继续冒泡，却不再被额外标记成 degraded infrastructure，避免把主链内部 bug 误报成普通后端抖动。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`python -m mypy websocket/consumers/world_chat.py tests/test_world_chat_consumer.py tests/test_websocket_world_chat_history_internals.py` 已通过；`pytest tests/test_world_chat_consumer.py tests/test_websocket_world_chat_history_internals.py -q` 为 `34 passed`，用于约束世界频道发送主链的基础设施降级、补偿退款与编程错误冒泡边界不回退。
- `buildings` 升级入口已不再从 view 直接调用 `refresh_manor_state(...)`；陈旧升级状态改由 `start_upgrade()` 写命令自行收口。
- `refresh_manor_state(...)` 已收紧为默认只处理建筑/资源读侧投影；`mission / scout / raid` 补偿刷新改为显式 `include_activity_refresh=True` 才会触发，避免总刷新入口继续默认扇出到阶段二写链路。
- `guests/roster`、`guests/detail` 的门客状态准备已收口到显式 read helper，不再在 `get_context_data()` 内联推进状态。
- 单会话策略已改为默认 `fail-closed`，但平台级故障语义仍需继续用真实服务门禁验证。
- integration gate 的提示信息、`pytest` 路径和模板/过滤器相关测试已补齐，但真实 MySQL / Redis / Channels / Celery gate 仍不足。

### 2.3 已启动但未封板的跨阶段主题

虽然当前主线仍是阶段 2，但以下主题已经启动，后续可以按“小主题一轮一收口”的方式继续推进：

- `阶段 3` 的异常语义收口已经开始：`trade`、`arena`、`work`、`jail`、`troop recruitment` 和部分资源链路已经退出一部分 legacy `ValueError` 兼容，但 `mission`、`guest recruitment` 等入口仍明显混用 `GameError + ValueError`。
- `mission` 已开始收口主链路异常语义：发起任务与撤退请求开始改走 `MissionError` 子类，但 view 层和部分兼容测试仍保留 `ValueError` 兜底。
- `mission` 的撤退命令契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/retreat_command.py` 当前不再把未来 `started_at` 静默纠偏成 `0` 秒已行进时间，而是统一改走显式 `AssertionError`；同时“刚出发立即撤退至少返程 1 秒”被保留为明确业务规则，不再混在坏状态兜底里。
- `mission` 的护院 loadout 归一化也已退出裸 `ValueError`：共享 `normalize_mission_loadout(...)` 现在直接抛显式 `TroopLoadoutError`，`AcceptMissionView` 也不再在 view 层重复做业务归一化，护院配置校验重新收口回服务写入口。
- `mission` 的 loadout wrapper 契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/loadout.py` 当前在 troop template 缺失时不再静默回空配置；`normalize_mission_loadout()` 与携带护院的 `travel_time_seconds()` 现在统一改走显式 `AssertionError`，避免坏环境被伪装成“未携带护院”。
- `mission` 的 squad size 配置契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/launch_command.py` 当前对坏掉的 `max_squad_size` 不再通过 `or 0` 静默兜底成“无限制/未配置”，而是统一改走显式 `AssertionError`，避免发起链路在坏庄园配置下悄悄放宽上阵人数限制。
- `mission` 的 base travel time 配置契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/launch_command.py` 当前对坏掉的 `base_travel_time` 不再依赖底层时间工具隐式纠偏，而是统一改走显式 `AssertionError`，避免发起链路在坏任务配置下悄悄改写往返耗时语义。
- `mission` 的 loadout payload 形状契约也已继续按阶段 3 收口：`gameplay/utils/resource_calculator.py` 当前对非 `dict` 的 `troop_loadout` 不再落成模糊 `AttributeError`，而是统一改走显式 `AssertionError`，避免 loadout 归一化和旅行时间计算在坏输入下暴露不稳定异常语义。
- `mission` 的 defense 发起输入契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/launch_command.py` 当前对 defense 任务误传的 `guest_ids / troop_loadout` 不再静默忽略，而是统一改走显式 `AssertionError`，避免服务层复用在坏调用下悄悄吞掉无效输入。
- `mission` 的 `accept/retreat/use_card` 视图入口以及 `scout start / retreat`、`raid start / retreat` 共享入口已不再把裸 `ValueError` 当作已知业务错误吞掉；`gameplay/views/mission_action_handlers.py` 里的 legacy `ValueError` 兼容开关也已移除，剩余 legacy `ValueError` 兼容主要还在更底层 battle/locking 输入校验等共享入口。
- `mission` 的同步战报 helper 也已开始按阶段 3 收口内部契约：`gameplay/services/missions_impl/sync_report.py` 当前不再把坏掉的 `enemy_guests / enemy_troops / guest_level / drop_table` 静默洗成空结构或默认值；这些 mission 配置错误现在统一改走显式 `AssertionError`。
- `mission` 的同步战报技术配置也已继续按阶段 3 收口：`gameplay/services/missions_impl/sync_report.py` 当前对坏掉的 `enemy_technology` 不再静默回退成空配置，而是统一改走显式 `AssertionError`，避免防守同步战报链在坏科技配置下悄悄丢掉敌方科技、加成和技能语义。
- `mission` 的同步战报门客技能配置也已继续按阶段 3 收口：`gameplay/services/missions_impl/sync_report.py` 当前对坏掉的 `enemy_technology.guest_skills` 不再静默忽略，而是统一改走显式 `AssertionError`，避免防守同步战报链在坏技能配置下悄悄丢失敌方技能语义。
- `mission` 的同步战报门客技能条目契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/sync_report.py` 当前对 `enemy_technology.guest_skills` 列表中的非字符串条目不再静默 `str(...)` 强转，而是统一改走显式 `AssertionError`，避免防守同步战报链在坏技能条目下制造伪造技能 key。
- `mission` 的同步战报 mapping key 契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/sync_report.py` 当前对 `enemy_technology` 和 offense `drop_table` 中的空 key 不再静默接受，而是统一改走显式 `AssertionError`，避免同步战报链在坏 key 配置下制造不可预测的科技或掉落语义。
- `mission` 的 launch / sync_report / drops key 类型契约也已继续按阶段 3 收口：这些链路当前对非字符串 key 不再静默 `str(...)` 强转，而是统一改走显式 `AssertionError`，避免坏配置在发起、同步战报和掉落发放链路里制造伪造 key 或悄悄改变语义。
- `mission` 的同步战报 / 掉落数值布尔值契约也已继续按阶段 3 收口：`sync_report.py` 当前对 `enemy_troops` 数量和 `guest_level` 的布尔值不再沿用 Python `bool -> int` 的隐式转换，`drops.py` 也不再把布尔值当合法掉落数量；这些情况现在统一改走显式 `AssertionError`，避免坏配置被悄悄解释成 `0/1`。
- `mission` 的 guest 配置空字符串契约也已继续按阶段 3 收口：`execution_adapters.normalize_guest_configs()`、`sync_report.py` 的 `enemy_guests` 与 `guest_skills` 当前都不再静默跳过空字符串，而是统一改走显式 `AssertionError`，避免坏配置在发起和同步战报链里悄悄少生成敌方门客或少带技能。
- `mission` 的装备掉落字段类型契约也已继续按阶段 3 收口：`drops.py` 当前对装备 `slot/category` 不再静默 `str(...)` 强转，而是统一要求显式字符串并在坏类型下改走 `AssertionError`，避免坏配置在装备掉落链里制造伪造 effect_type。
- `mission` 的结算 helper 也已开始按阶段 3 收口内部契约：`gameplay/services/missions_impl/finalization_helpers.py` 当前在读取 `report.losses.hp_updates` 与 team entry 时，不再把坏掉的 `guest_id / remaining_hp` 静默跳过；损坏的 mission 战报 payload 现在统一改走显式 `AssertionError`，避免结算链路悄悄丢失受伤/参战门客状态。
- `mission` 的结算战报容器契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/finalization_helpers.py` 当前对坏掉的 `report.losses` 与 `attacker_team / defender_team` 容器本身不再落成模糊 `AttributeError`，而是统一改走显式 `AssertionError`，避免结算链路在损坏战报形状下暴露不稳定异常语义。
- `mission` 的结算 team entry 形状契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/finalization_helpers.py` 当前对 `attacker_team / defender_team` 中的非 dict 条目不再落成模糊 `AttributeError`，而是统一改走显式 `AssertionError`，避免结算链路在坏 team entry 条目下暴露不稳定异常语义。
- `mission` 的结算载荷契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/finalization_helpers.py` 当前不再把坏掉的 `troop_loadout` 与 `report.drops` 静默当成空映射处理；这些 mission 结算 payload 现在统一改走显式 `AssertionError`，避免返还护院和战利品补发链路在坏数据下悄悄少发、漏发或跳过。
- `mission` 的防守掉落补发 payload 契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/drops.resolve_defense_drops_if_missing()` 当前对坏掉的 `report.drops` 与 `drop_table` 空 key 不再静默当空映射处理，而是统一改走显式 `AssertionError`，避免防守补发链路在坏 payload 下悄悄少发或漏发掉落。
- `mission` 的防守掉落补发 helper 也已开始按阶段 3 收口内部契约：`gameplay/services/missions_impl/drops.py` 当前在 defense 场景下不再把坏掉的 `drop_table` 静默当空表处理；损坏的 mission 掉落配置现在统一改走显式 `AssertionError`，避免补发链路悄悄丢失任务奖励。
- `mission` 的掉落发放 helper 也已开始按阶段 3 收口内部契约：`gameplay/services/missions_impl/drops.py` 当前不再把负数掉落数量静默带入奖励链，也不再在找不到物品模板时悄悄跳过该掉落；损坏的 mission 掉落 payload 现在统一改走显式 `AssertionError`，避免奖励链路少发、漏发却不暴露错误。
- `mission` 的 launch helper 也已开始按阶段 3 收口内部契约：`gameplay/services/missions_impl/launch_post_actions.py` 当前在 offense 场景下不再把坏掉的 `enemy_guests / enemy_troops / enemy_technology / drop_table` 静默洗成空结构；损坏的 mission 配置现在统一改走显式 `AssertionError`，避免发起链路悄悄改变对手配置和掉落语义。
- `mission` 的 launch guest config 适配层也已继续按阶段 3 收口：`gameplay/services/missions_impl/execution_adapters.normalize_guest_configs()` 当前不再把列表中的非法 entry 静默跳过，而是统一改走显式 `AssertionError`，避免发起链路在坏掉的 `enemy_guests` 配置下悄悄少生成对手门客。
- `mission` 的 launch mapping 适配层也已继续按阶段 3 收口：`gameplay/services/missions_impl/execution_adapters.normalize_mapping()` 当前不再把坏掉的 mapping payload 静默洗成空映射，也不再接受空 key；这些 `enemy_troops / enemy_technology / drop_table` 配置错误现在会继续通过 `launch_post_actions` 统一暴露为字段级 `AssertionError`，避免发起链路在坏配置下悄悄少带兵、少带科技或少掉落。
- `mission` 的 refresh 配置 helper 也已开始按阶段 3 收口内部契约：`gameplay/services/missions_impl/refresh_command.py` 当前对非法 `MISSION_REFRESH_SYNC_MAX_RUNS` 不再静默夹成 `0`，而是统一改走显式 `AssertionError`；仅在缺省未配置时保留默认值 `3`，避免刷新链路在坏配置下悄悄改变 sync/async 分流语义。
- `mission` 的完成任务调度契约也已继续按阶段 3 收口：`launch_post_actions.schedule_mission_completion_task()` 与 `refresh_command.schedule_mission_completion()` 当前对过去时间的 `return_at` 不再静默夹成 `0` 秒立即派发/立即兜底，而是统一改走显式 `AssertionError`；只有恰好到期的 run 才继续走同步 finalize fallback，避免 mission 调度链在坏时间状态下悄悄改写完成语义。
- `mission` 的 refresh 完成调度入口也已继续按阶段 3 收口：`refresh_command.schedule_mission_completion()` 当前对缺失的 `return_at` 不再静默跳过，而是直接抛显式 `RuntimeError("Mission run was not created correctly")`，与 launch 调度入口保持一致，避免 refresh/retreat 链在坏 run 状态下悄悄漏调度。
- `mission` 的次数 service 也已开始按阶段 3 收口内部契约：`gameplay/services/missions_impl/attempts.py` 当前对非正 `count` 不再静默创建或累加额外任务次数，而是统一改走显式 `AssertionError`，避免 `mission card` 与其它复用调用在坏输入下悄悄改写次数语义。
- `mission` 的 daily limit 计算契约也已继续按阶段 3 收口：`gameplay/services/missions_impl/attempts.py` 当前对坏掉的 `daily_limit` 与额外次数返回值不再直接带入发起前校验，而是统一改走显式 `AssertionError`，避免任务发起链在坏配置/坏数据下悄悄放宽或锁死次数限制。
- `raid/scout` 的双庄园加锁也已开始退出裸 `ValueError`：`gameplay/services/raid/scout.py` 的 `_lock_manor_pair()` 现在直接抛显式 `ScoutStartError`，把“目标庄园不存在”的业务语义留在侦察发起链路内收口。
- `raid` 的 loadout 预备层也已删掉过期兼容壳：`gameplay/services/raid/combat/raid_inputs.py` 不再把 battle 层的显式 `BattlePreparationError` 重新包成 `RaidStartError`，`start_raid_api` 继续通过统一 `GameError` 映射返回业务错误。
- `battle` 的门客技能序列化也已开始退出误吞异常：`battle/combatants_pkg/guest_builder.py` 不再把已保存门客 `skills.all()` 上的裸 `ValueError` 静默吞掉，未保存门客仍走显式空回退，程序错误改为继续冒泡。
- `battle` 的状态伤害惩罚入口也已退出裸 `ValueError`：`battle/simulation/damage_calculation.py` 的 `process_status_effects(..., phase=\"damage_penalty\")` 现在把缺少 `damage` 视为内部调用契约错误，改走显式 `AssertionError`，不再伪装成业务参数异常。
- `battle/locking.py` 的加锁输入契约也已继续退出裸 `ValueError`：`collect_guest_ids()` 与 `collect_manor_ids()` 当前不再直接泄漏 `int(...)` 的裸异常，也不再把坏掉的 `guest.manor_id` 静默跳过；非法门客/庄园 ID 现在统一改走显式 `AssertionError`，避免 `mission / raid / scout` 共用的锁顺序收集路径在坏数据下悄悄少锁行。
- `battle/setup.py` 的攻击方门客归属校验也已继续退出裸 `ValueError`：`validate_attacker_guest_ownership()` 当前不再把坏掉的 `guest.pk` / `guest.manor_id` 留给 `int(...)` 裸异常或继续走查库回退；除保留 legacy snapshot 缺失 `manor_id` 的兼容外，非法攻击方门客 ID/归属 ID 现在统一改走显式 `AssertionError`，避免 `mission / raid / scout` 共用的战斗预备层继续掩盖调用契约错误。
- `raid` 依赖的 battle 预备层异常语义也已开始收口：`battle/setup.py`、`battle/locking.py`、`battle/execution.validate_troop_capacity()` 已开始改走显式 `BattlePreparationError`，但更底层 battle 组件和其它复用路径仍未整体封板。
- `guest recruitment` 已开始收口主链路异常语义：招募发起、放大镜使用、候选保留已改走显式 `RecruitmentError` 子类，`guests/views/recruit_action_runtime.py` 不再把裸 `ValueError` 当作已知业务错误。
- `guest recruitment` 的 flow helper 也已开始退出裸 `ValueError`：`guests/services/recruitment_flow.resolve_recruitment_seed()` 对非法 seed 不再直接泄漏 `int(...)` 的裸异常，统一改走显式内部调用契约错误 `AssertionError`。
- `guest recruitment` 的 flow helper 契约也已继续收紧：`resolve_recruitment_cost()`、`create_pending_recruitment()` 对非法 cost / draw_count / duration 输入不再直接泄漏底层 `dict(...)` / `int(...)` 裸异常，统一改走显式 `AssertionError`。
- `guest recruitment` 的成本配置契约也已继续按阶段 3 收口：`resolve_recruitment_cost()` 当前不再把 `False` 这类假值坏配置静默当成空成本，而是统一改走显式 `AssertionError`；仅 `None` 继续表示“无成本”，避免招募链路在坏配置下悄悄跳过资源扣除。
- `guest recruitment` 的 candidate helper 也已开始退出裸异常：`resolve_candidate_draw_count()` 对非法抽取数量不再直接泄漏 `int(...)` 的裸异常，统一改走显式内部调用契约错误 `AssertionError`。
- `guest recruitment` 的 draw_count / duration helper 也已继续按阶段 3 收口：`resolve_candidate_draw_count()` 与 `create_pending_recruitment()` 当前对 `0`、负数这类非正输入不再静默纠偏成最小值，而是统一改走显式 `AssertionError`，避免招募 helper 在坏配置/坏调用下悄悄改变业务语义。
- `guest recruitment` 的 seed helper 也已继续按阶段 3 收口：`resolve_recruitment_seed()` 与 `create_pending_recruitment()` 当前对 `0`、负数这类非正种子不再继续接受并落库，而是统一改走显式 `AssertionError`，避免招募 helper 在坏调用下制造不合法随机种子语义。
- `guest recruitment` 的完成态 helper 也已继续按阶段 3 收口：`mark_recruitment_completed_locked()` 当前对负数 `result_count` 不再静默归零，而是统一改走显式 `AssertionError`，避免完成态 helper 在坏调用下悄悄改写候选数量语义。
- `guest recruitment` 的查询配置 helper 也已继续按阶段 3 收口：`get_pool_recruitment_duration_seconds()` 与 `_get_pool_daily_draw_limit()` 当前对非正或非法 `cooldown_seconds / DAILY_POOL_DRAW_LIMIT` 不再静默回退成 `0`、`1` 或默认值，而是统一改走显式 `AssertionError`，避免招募配置在坏值下悄悄改变倒计时和每日上限语义。
- `guest recruitment` 的 finalize helper 也已继续按阶段 3 收口：`split_candidates_by_capacity()` 当前对负数 `available_slots` 不再静默夹成 `0`，而是统一改走显式 `AssertionError`，避免完成链路在坏调用下悄悄吞掉全部候选。
- `guest recruitment` 的 finalize 容量 helper 也已继续按阶段 3 收口：`remaining_guest_capacity()` 与 `ensure_retainer_capacity_available()` 当前对坏掉的 `guest_capacity / retainer_capacity / retainer_count` 不再静默当成 `0`、满员或继续执行，而是统一改走显式 `AssertionError`，避免完成链路在脏状态下悄悄改写容量语义。
- `guest recruitment` 的门客容量占用契约也已继续按阶段 3 收口：`remaining_guest_capacity()` 当前不再把“当前门客数已超过容量”的坏状态静默夹成 `0` 剩余位，而是统一改走显式 `AssertionError`，避免 finalize 链路在庄园容量数据已损坏时继续悄悄吞掉候选。
- `guest recruitment` 的批量确认入口契约也已继续按阶段 3 收口：`bulk_finalize_candidates()` 当前不再把“未持久化候选对象”或“混入其它庄园的候选”静默当成 failed 列表处理，而是统一改走显式 `AssertionError`，避免 finalize service 在坏调用下悄悄错过真正的调用方契约问题。
- `guest recruitment` 的 finalize 主入口契约也已继续按阶段 3 收口：`finalize_guest_recruitment()` 当前对未持久化 recruitment 对象不再静默返回 `False`，而是统一改走显式 `AssertionError`，避免 worker / refresh / 其它复用方把明显的调用契约错误误判成“当前无需完成”。
- `guest recruitment` 的 refresh 入口契约也已继续按阶段 3 收口：`refresh_guest_recruitments()` 当前对非法或非正 `limit` 不再走 Python 切片的隐式回退语义，而是统一改走显式 `AssertionError`，避免 refresh service 在坏调用下悄悄少刷、反向切片或表现不确定。
- `guest recruitment` 的完成任务调度契约也已继续按阶段 3 收口：`schedule_guest_recruitment_completion()` 当前对负数或非法 `eta_seconds` 不再静默夹成 `0` 秒立即派发，而是统一改走显式 `AssertionError`，避免招募发起链在坏倒计时输入下悄悄改变任务调度语义。
- `guest recruitment` 的页面动作运行时也已继续按阶段 3 收口：`guests/views/recruit_action_runtime.py` 当前不再通过 `classify_view_error(...)` 对候选处理/放大镜动作做动态异常分类，而是直接依赖 `execute_locked_action(...)` 的显式分流，只把 `GameError` 当业务失败、只把数据库/基础设施异常映射成 500，编程错误继续冒泡，避免页面运行时继续保留模糊异常猜测层。
- `guest recruitment` 的属性点分配路径也已开始退出 legacy `ValueError`：`guests/services/recruitment_guests.allocate_attribute_points()` 与 `guests/views/training.allocate_points_view()` 已改走显式门客 / 加点异常，但训练、经验道具等其它培养入口仍未整体封板。
- `guest recruitment` 的属性点分配错误语义也已继续细化：`InvalidAllocationError("attribute_overflow")` 不再落回通用“无效的加点请求”，现在会返回明确的“属性值已达上限，无法继续加点”业务文案。
- `guest training` / `experience item` 的一部分异常语义也已开始收口：`guests/services/training.use_experience_item_for_guest()` 与 `guests/views/training.use_experience_item_view()` 已改走显式门客 / 道具异常，`TrainView` 也不再把裸 `ValueError` 当作已知业务错误。
- `guest` 的洗点卡链路也已开始退出裸 `ValueError`：`guests/growth_engine.reset_guest_allocation()` 对“没有已分配属性点”不再抛裸 `ValueError`，改走显式 `GuestAllocationResetError`，`gameplay/views/inventory.py` 能稳定按已知业务错误返回。
- `guest training` 的计算 helper 也已开始退出裸 `ValueError`：`guests/utils/training_calculator.py` 里升级成本、训练时长的参数/上限校验不再把内部调用契约失败伪装成业务错误，统一改走显式 `AssertionError`。
- `guest training` 的主写入口也已开始收口内部契约：`guests/services/training.train_guest()` 对未保存门客不再抛通用 `GuestError`，改走显式内部调用契约错误 `AssertionError`。
- `guest training` 的批量缩时入口也已开始收口业务异常：`guests/services/training.reduce_training_time()` 对“没有可缩短训练时间的门客”不再抛通用 `GuestError`，改走显式 `GuestTrainingUnavailableError`。
- `guest` 的装备 / 药品 / 技能 / 辞退入口也开始退出 legacy `ValueError`：`guests/services/health.py`、`guests/services/skills.py`、`guests/services/roster.py`、`guests/services/equipment.py` 已补显式门客 / 道具 / 技能异常，`guests/views/items.py`、`guests/views/skills.py`、`guests/views/equipment.py`、`guests/views/roster.py` 不再把裸 `ValueError` 当作已知业务错误；但 `roster`、`items`、`equipment` 之外的其它门客入口仍未整体封板。
- `guest salary` 入口也开始退出 legacy `ValueError`：`guests/views/salary.py` 已停止依赖会吞裸 `ValueError` 的通用装饰器，改单独收口 `GameError` / `DatabaseError`，工资支付链路开始具备与 `guest recruitment`、`training` 一致的异常边界。
- `inventory` 的门客定向道具链路也已开始收口：`gameplay/services/inventory/guest_reset_helpers.py`、`gameplay/services/inventory/guest_items.py` 已把重生卡 / 升阶道具 / 灵魂容器的核心校验改走显式门客 / 道具异常，`gameplay/views/inventory.py` 的目标门客物品入口不再把裸 `ValueError` 当作已知业务错误；但仓库通用 `use_item` 与其它非定向道具链路仍未整体封板。
- `gameplay/services/inventory/guest_reset_helpers.py` 的门客重置卸装恢复链也已继续按阶段 3 收口：`detach_guest_gears_for_reset()` 当前只会在显式 `GameError` 的常规卸装失败时退回强制卸装；`AssertionError("broken unequip contract")` 一类编程错误，以及强制回仓阶段的异常都会继续冒泡并回滚，避免重生/升阶/灵魂融合链路静默丢装备。
- `inventory` 的仓库通用 `use_item` 链路也已开始退出一批 legacy `ValueError`：`gameplay/services/inventory/use.py` 中免战牌、召唤卡、工具类分发、物品归属校验已改走显式 `ItemError / GuestError`，`gameplay/views/inventory.py` 的通用使用入口不再把裸 `ValueError` 当作已知业务错误；但仓库迁移和其它建筑 / 道具副作用链路仍未整体封板。
- `inventory` 的召唤卡配置契约也已继续按阶段 3 收口：`gameplay/services/inventory/use.py` 当前不再把坏掉的 `choices` / `required_items` 配置静默跳过并退化成“免费召唤”或空权重回退；权重、模板键和所需物品配置异常现在统一改走显式 `ItemNotConfiguredError`，避免仓库通用 `use_item` 链路继续掩盖道具配置错误。
- `inventory` 的宝箱概率配置契约也已继续按阶段 3 收口：`gameplay/services/inventory/use.py` 里 `gear_chance / skill_book_chance` 若为非法类型/非法数值，不再静默当成 `0` 跳过掉落分支，而是统一改走显式 `ItemNotConfiguredError`，避免坏配置把宝箱奖励悄悄降级成“永不掉落”。
- `inventory` 的宝箱 payload 类型契约也已继续按阶段 3 收口：`gameplay/services/inventory/use.py` 里 `resources / gear_keys / skill_book_keys` 若不是约定的 `dict / list`，不再等到运行时隐式报错或静默跳过，而是统一改走显式 `ItemNotConfiguredError`，避免仓库通用 `use_item` 链路继续掩盖宝箱配置错误。
- `inventory` 的免战牌配置契约也已继续按阶段 3 收口：`gameplay/services/inventory/use.py` 里 `peace_shield` 道具的 `duration` 当前必须是正整数秒数；非法类型、布尔值或非正数不再落成隐式 `TypeError`/奇怪时长，而是统一改走显式 `ItemNotConfiguredError`。
- `inventory` 的唯一门客召唤配置契约也已继续按阶段 3 收口：`gameplay/services/inventory/use.py` 里 `exclusive_template_keys` 当前若存在就必须是列表，不再在坏配置下静默忽略唯一门客保护逻辑，而是统一改走显式 `ItemNotConfiguredError`。
- `inventory` 的宝箱银两区间契约也已继续按阶段 3 收口：`gameplay/services/inventory/use.py` 里 `silver_min / silver_max` 当前不再把负数配置静默夹成 `0`、也不再把反向区间自动交换顺序，而是统一改走显式 `ItemNotConfiguredError`，避免坏配置悄悄改变奖励分布。
- `inventory` 的 payload 形状契约也已继续按阶段 3 收口：`gameplay/services/inventory/use.py` 里 `tool / resource_pack / loot_box / peace_shield / summon_guest` 相关入口现在都要求 `effect_payload` 为 `dict`；不再在坏配置下落成 `AttributeError` 或把列表/其它 JSON 形状带进运行时，而是统一改走显式 `ItemNotConfiguredError`。
- `inventory/core` 的基础库存行操作也已开始退出裸 `ValueError`：`consume_inventory_item_locked()` 与 `consume_inventory_item()` 对未持久化库存行不再抛 `ValueError("物品不存在")`，统一改走显式 `ItemNotFoundError`。
- `inventory/core` 的加库存入口也已开始退出裸 `ValueError`：`add_item_to_inventory_locked()` 对非正数量不再抛 `ValueError("quantity must be positive")`，改为显式内部调用契约错误 `AssertionError`。
- `treasury` 的物品迁移服务也已开始按阶段 3 收口内部契约：`move_item_to_treasury()` 与 `move_item_to_warehouse()` 当前对非正数量不再依赖 view 层前置校验兜底，而是直接抛显式 `AssertionError`，避免服务层被复用时静默改出负库存/反向增发。
- `raid/protection` 的免战牌服务边界也已开始收口：`gameplay/services/raid/protection.py` 已退出 legacy `ValueError`，改走显式 `PeaceShieldUnavailableError`，并成为仓库免战牌使用链路的单一校验来源。
- `raid/relocation` 的庄园迁移服务边界也已开始收口：`gameplay/services/raid/relocation.py` 已退出 legacy `ValueError`，改走显式 `RelocationError`，并补上迁移条件、金条不足、坐标耗尽等服务契约测试。
- `technology` 视图入口也已退出 legacy `ValueError`：`gameplay/views/technology.py` 现在只把显式 `TechnologyError / GameError` 当已知业务错误处理，裸 `ValueError` 改为继续冒泡。
- `building` 升级主入口也已开始收口异常语义：`gameplay/services/manor/core.start_upgrade()` 已把“正在升级 / 达到满级 / 并发上限”改走显式 `BuildingError` 子类，`gameplay/views/buildings.py` 不再把裸 `ValueError` 当已知业务错误处理。
- `production` 的马房 / 畜牧 / 冶炼主入口也已开始收口异常语义：`gameplay/services/buildings/stable.py`、`gameplay/services/buildings/ranch.py`、`gameplay/services/buildings/smithy.py` 已把参数/门槛/并发中的业务 `ValueError` 改走显式 `ProductionStartError`，`gameplay/views/production.py` 不再把裸 `ValueError` 当已知业务错误处理。
- `core` 的庄园改名入口也已开始退出 legacy `ValueError`：`gameplay/services/manor/core.rename_manor()` 已把名称校验、重名冲突、命名卡配置/扣减失败改走显式 `GameError`，`gameplay/views/core.py` 不再把裸 `ValueError` 当已知业务错误处理。
- `forge` 的锻造 / 图纸 / 分解主入口也已开始收口异常语义：`gameplay/services/buildings/forge_runtime.py`、`gameplay/services/buildings/forge_blueprints.py`、`gameplay/services/buildings/forge_decompose.py` 及相关 helper 已把业务 `ValueError` 改走显式 `ForgeOperationError`，`gameplay/views/production_forge_handlers.py` 不再把裸 `ValueError` 当已知业务错误处理。
- `阶段 5` 的测试门禁治理已经开始：hermetic / integration gate 提示、`pytest` 路径和部分边界契约测试已经补齐，但真实外部服务覆盖面仍不足。
- `阶段 5` 的超大测试文件拆分已开始：`tests/test_trade_views.py` 已拆分为 `tests/trade/test_trade_*_views.py` 并通过 `pytest tests/trade` 验证，避免单文件继续超出默认复杂度预算。

### 2.4 当前未完成的高优先级问题

- 阶段 2 已完成封板；后续只保留 `make test-critical` / `make test-real-services` / `make test-gates` 这类固定回归维护，不再把并发基线收口当作主线开发主题。
- 项目内仍有不少入口继续把 `ValueError` 作为跨层业务语义，异常层次还没有整体收口。
- 页面读路径虽然已经开始统一，但尚未完全消除局部降级分叉；活动补偿已退出页面隐式读路径，但仍需在阶段 3 持续审视显式刷新入口与错误语义的一致性。

## 3. 后续执行顺序

下一轮优化按以下顺序推进：

1. 沿高频主链路逐步退出 legacy `ValueError` 兼容，优先处理 `mission / guest recruitment` 等仍明显混用的 view/service 入口。
2. 继续统一 view / selector / service / infrastructure 的异常分层、降级口径与契约测试。
3. 在阶段 2 关键链路已有真实测试约束的前提下，继续推进模板、页面脚本和前端交互边界治理。
4. 把阶段 2 的 real-services 套件持续保留在回归节奏里，避免补偿边界与并发语义回退。

## 4. 分阶段路线

### 阶段 2：并发与测试基线

目标：

- 固化 `mission / raid / guest recruitment` 的统一写模型。
- 为请求级锁、数据库锁、任务派发和 refresh 补偿补真实环境测试。
- 禁止新增隐藏副作用 accessor 或“读取前顺手修状态”的入口。

完成标志：

- 主写入口、锁职责、补偿边界都能被清楚说明。
- 页面读请求不再承担隐式补偿职责。
- 真实环境测试开始覆盖关键并发与任务派发语义。

### 阶段 3：类型与异常边界治理

目标：

- 逐步缩小 `pyproject.toml` 中 mypy 的 `ignore_errors` 范围。
- 建立显式异常分层，逐步退出 legacy `ValueError` 兼容语义。
- 为 view / selector / service / infrastructure 建立更稳定的契约测试。

完成标志：

- 高频主链路的异常类型、降级口径和页面映射关系清晰稳定。
- 类型门禁和覆盖率门禁开始对热点路径形成真实约束。

### 阶段 4：模板与前端边界治理

目标：

- 拆分最大模板和页面脚本。
- 把内联交互、页面状态逻辑和大段样式逐步从模板中抽离。
- 降低基模板承担的全局职责密度。

完成标志：

- 高复杂页面具备稳定 partial / component 边界。
- 前端交互逻辑不再继续散落在模板内联代码中。

### 阶段 5：测试与发布质量

目标：

- 拆分超大测试文件，按业务域整理测试资产。
- 建立更清晰的 hermetic / integration 测试边界。
- 为并发、库存、撤退、报名、任务派发等关键路径增加回归测试。

完成标志：

- 测试目录、fixture、builder、integration gate 的结构更稳定。
- 默认测试和真实环境测试各自覆盖的职责清晰可说明。

### 阶段 6：运维与长期治理

目标：

- 补齐结构化日志、任务监控、失败告警和运行手册。
- 评估历史 migration、缓存策略、异步任务治理和运维流程。
- 保持文档、门禁和运行时语义一致。

完成标志：

- 开发、测试、上线、回滚和排障流程具备统一口径。
- 文档、门禁和运行时语义持续同步。
