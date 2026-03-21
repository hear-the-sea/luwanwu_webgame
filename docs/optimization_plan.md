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

当前主线是 `阶段 2：并发与测试基线`。

本阶段已经明确的基线：

- `mission / raid / guest recruitment` 的统一写模型必须服从 [第二阶段统一写模型基线](write_model_boundaries.md)。
- 写链路要明确区分 `view / action handler`、`write command`、`after-commit follow-up`、`refresh / finalize command`。
- 补偿刷新不得重新挂回页面读路径。
- 请求级锁只做去重，数据库事务和行锁才是正确性来源。

当前已推进但尚未封板的事项：

- `HomeView`、`MapView`、`raid_status_api` 已退出 GET 读路径中的 `raid/scout` 补偿刷新；显式刷新改由 `POST /gameplay/api/map/status/refresh/` 触发，但其它页面和真实服务门禁仍未让这条链路整体封板。
- `map` 的显式活动刷新也已退出 view 内联编排：`refresh_raid_activity_api` 现在只调用 `gameplay.services.raid.refresh_raid_activity()` 这一显式服务入口，不再在 view 层直接拼接 `refresh_scout_records()` / `refresh_raid_runs()`。
- `gameplay/services/raid/scout_refresh.py` 已承接侦察 refresh 补偿命令，`gameplay/services/raid/scout_followups.py` 也开始承接 after-commit 消息/任务派发；`scout.py` 已退回公共入口、状态查询和适配层，但真实服务测试仍需继续收口。
- `gameplay/services/raid/scout_return.py` 已开始承接撤退请求和返程完成写命令；`scout_start.py`、`scout_finalize.py` 现已承接侦察发起/结果写入主写命令，但真实服务测试仍未封板。
- `raid/scout` 已补第一批真实外部服务测试，开始覆盖 refresh dispatch dedup gate、dispatch 失败回滚、同步补偿收口，以及 `complete_scout_task` / `complete_scout_return_task`、`complete_raid_task`（撤退返程）、`process_raid_battle_task` 的实际消费；但并发冲突和更多 battle/refresh 竞争语义仍未封板。
- `raid/scout` 的 refresh 契约测试已继续补强：due-id 收集现在有测试约束其只扫描“到期且仍处于 durable 进行中状态”的记录，不再把未来记录或终态记录混入补偿路径。
- `scout` 的真实并发测试也已补到仓库：并发发起只允许一次派出、并发撤退只允许一次状态迁移，以及 refresh 与 `finalize_scout()` / `finalize_scout_return()` 并发时只允许一次 durable 收口的 integration 用例，已在本机外部 MySQL gate 下完成实跑验收。
- `raid` 的真实并发测试也已继续补到仓库：并发 battle 只允许一次从 `MARCHING` 进入主流程、并发 finalize 只允许一次落成 `COMPLETED`，以及 refresh 与 `process_raid_battle()` / `finalize_raid()` 并发时只允许一次 durable 收口的 integration 用例，已在本机外部 MySQL gate 下完成实跑验收。
- `raid/scout` 的第二批真实并发测试已继续补上 refresh 竞争语义：`refresh_raid_runs()` 与显式 `process_raid_battle()` / `finalize_raid()` 并发时仍只允许一次 durable 收口，`refresh_scout_records()` 与显式 `finalize_scout()` / `finalize_scout_return()` 并发时也只允许一次状态推进或返还探子。
- `mission` 已补真实并发与任务派发语义测试，覆盖同门客并发发起只允许一个 `ACTIVE`、同一 `MissionRun` 并发撤退只允许一个状态迁移成功，以及 refresh dispatch dedup gate / dispatch 失败回滚、`complete_mission_task` 实际消费收口；`refresh_mission_runs()` 与显式 `finalize_mission_run()` 的真实并发竞争用例也已补齐，并在 real-services gate 下完成验收。
- `mission` 发起写入口已退出预刷新耦合：`launch_mission()` 不再在主写命令前隐式调用 `refresh_mission_runs()`；到期 run 的补偿继续留在显式 refresh / worker 链路，并已补回归测试约束该边界。
- `guest recruitment` 已补真实服务语义测试，覆盖并发发起只允许一个 `PENDING`、并发完成只允许一次 `PENDING -> COMPLETED` 收口，以及候选确认只允许一次转正；`refresh_guest_recruitments()` 与显式 `finalize_guest_recruitment()` 的真实并发竞争用例也已补齐，并在 real-services gate 下完成验收。
- `guest recruitment` 的 refresh 契约测试也已补到 service 层：`refresh_guest_recruitments()` 现在有测试约束其只扫描“到期且仍为 PENDING”的 durable rows，不再把未来记录或已结束记录混入补偿路径。
- `2026-03-22` 已完成一轮阶段 2 real-services 验收：`tests/test_raid_concurrency_integration.py`、`tests/test_raid_scout_concurrency_integration.py` 共 `8 passed, 2 skipped`，`tests/test_mission_concurrency_integration.py`、`tests/test_guest_recruitment_concurrency_integration.py` 共 `6 passed, 1 skipped`。
- 阶段 2 的关键 real-services 套件现已纳入 `make test-critical` 固定回归：`raid / scout / mission / guest recruitment` 会与既有 `work service` 并发用例一起在 `DJANGO_TEST_USE_ENV_SERVICES=1 make test-real-services` / `make test-gates` 中执行，避免封板后只停留在一次性人工验收。
- 阶段 3 的异常边界治理已开始落到 `guest recruitment` 与 `mission` follow-up 链路：`finalize_guest_recruitment()` 不再把 `AssertionError` 等内部契约/程序错误伪装成 `FAILED` 招募结果，当前只会把显式 `RecruitmentError` 落成 durable 失败态；`recruitment_followups` 也已退出“导入失败/消息发送失败一律吞掉”的 broad catch，任务模块导入的编程错误会继续冒泡，招募完成通知只对显式消息/基础设施异常降级。与此同时，`mission` 的 `import_launch_post_action_tasks()`、`refresh_command` 与相关 task follow-up 导入逻辑也开始区分“目标模块缺失”与“模块内部嵌套依赖损坏”两类 ImportError，只对前者降级；`launch_resilience` 也开始只对基础设施类 launch/report/dispatch 故障降级，编程错误不再统一吃掉；`send_mission_report_message()` 也已改为只对显式消息/通知基础设施异常降级，战报消息创建与通知中的编程错误会继续冒泡；`build_mission_drops_with_salvage()` 这类纯业务奖励计算也已退出 broad catch，salvage 计算契约错误不再被静默降级为“少发奖励”，并已补服务契约测试约束这些边界。
- `troop recruitment` 生命周期也已开始按阶段 3 收口异常语义：`gameplay/services/recruitment/lifecycle.py` 的 `complete_troop_recruitment` 导入 fallback 现在只在 `gameplay.tasks` 目标模块缺失时降级，嵌套依赖损坏和其它导入故障会继续冒泡；募兵完成通知已拆分为站内信创建与 WebSocket 推送两段，只有显式消息/通知基础设施故障继续 fail-open，编程错误会继续暴露。`guests/services/recruitment_shared.py` 的聚贤庄缓存失效 helper 也已去掉多余 broad catch，不再把参数/程序错误吞成静默 debug。
- `2026-03-22` 已补一轮阶段 3 聚焦验证：`tests/test_troop_recruitment_service.py`、`tests/test_recruitment_hall_cache.py` 共 `16 passed`，用于约束护院募兵生命周期与聚贤庄缓存失效 helper 的异常边界不回退。
- `raid/scout` 的 follow-up 与 refresh 任务导入边界也已开始按阶段 3 收口：`gameplay/services/raid/scout_followups.py` 不再把侦察结果消息链中的编程错误统一吞成 best-effort 成功，当前只对显式站内信/数据库基础设施故障做降级；`dispatch_scout_task()` 与 `scout_refresh.resolve_scout_refresh_tasks()` 也开始区分“`gameplay.tasks.pvp` 目标模块缺失”和“模块内部嵌套依赖损坏/其它导入故障”，只对前者回退，后者继续冒泡。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_raid_scout_refresh.py` 共 `18 passed`，用于约束 `raid/scout` follow-up 与 refresh 任务导入的异常边界不回退。
- `raid` 主写链路的任务导入边界也已继续按阶段 3 收口：`gameplay/services/raid/combat/refresh_flow.py`、`gameplay/services/raid/combat/run_side_effects.py` 与 `gameplay/services/raid/combat/battle.py` 现在开始区分“`gameplay.tasks` 目标模块缺失”和“模块内部嵌套依赖损坏/其它导入故障”，只对前者做同步回退或 best-effort 降级；`process_raid_battle_task`、`complete_raid_task` 相关导入中的编程错误不再被统一伪装成刷新/返程成功。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_raid_combat_runs.py`、`tests/test_raid_combat_battle.py` 共 `46 passed`，用于约束 `raid` refresh / dispatch / finalize 的任务导入异常边界不回退。
- `raid` 的消息与缓存降级口径也已继续按阶段 3 收口：`gameplay/services/raid/combat/start.py` 发送来袭警报时不再把 `AssertionError` 等编程错误统一吞成出征成功，当前只对显式消息/数据库基础设施故障做 fail-open；`gameplay/services/raid/utils.py` 的近期攻击缓存 helper 也已改为只对显式缓存基础设施故障降级，缓存调用契约错误会继续冒泡。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_raid_combat_runs.py`、`tests/test_raid_utils_cache.py` 共 `36 passed`，用于约束 `raid` 来袭消息与近期攻击缓存 helper 的异常边界不回退。
- `arena` 的消息降级口径也已开始按阶段 3 收口：`gameplay/services/arena/exchange_helpers.py`、`gameplay/services/arena/lifecycle_helpers.py` 与 `gameplay/services/arena/match_helpers.py` 不再把竞技场兑换提示、结算奖励消息和战报消息里的编程错误统一吞成 best-effort 成功，当前只对显式消息/数据库基础设施故障做 fail-open；相关 helper 的异常边界开始与 `mission / raid / recruitment` 保持一致。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_arena_exchange_helpers.py`、`tests/test_arena_services.py`、`tests/test_arena_message_boundaries.py` 共 `33 passed`，用于约束 `arena` 兑换、结算与战报消息的异常边界不回退。
- `arena` 的批处理主入口也已开始按阶段 3 收口：`gameplay/services/arena/core.py` 的 `start_ready_tournaments()` 与 `run_due_arena_rounds()` 已去掉 broad catch，不再把批处理编排里的 `AssertionError` 等编程错误吞成“记录日志后继续处理”，当前会让异常继续冒泡，避免后台任务静默掩盖竞技场轮次编排问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_arena_services.py`、`tests/test_arena_exchange_helpers.py`、`tests/test_arena_message_boundaries.py` 共 `35 passed`，用于约束 `arena` 批处理主入口与消息边界不回退。
- `arena` 的比赛解析边界也已继续按阶段 3 收口：`gameplay/services/arena/match_helpers.py` 的 `resolve_match_locked()` 不再把 `simulate_report()` 的所有异常统一改写成“待系统重试”；当前只会把显式 `BattlePreparationError` 转成可重试的 `ArenaMatchResolutionError` 语义，`AssertionError` 等编程错误会继续冒泡，避免竞技场对战编排静默掩盖 battle 契约错误。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_arena_services.py`、`tests/test_arena_exchange_helpers.py`、`tests/test_arena_message_boundaries.py`、`tests/test_arena_round_helpers.py` 共 `40 passed`，用于约束 `arena` 批处理主入口、消息边界与比赛解析异常边界不回退。
- `arena` 的消息降级口径也已继续退出 runtime marker 猜测：`gameplay/services/arena/exchange_helpers.py`、`gameplay/services/arena/lifecycle_helpers.py` 与 `gameplay/services/arena/match_helpers.py` 当前只对显式 `MessageError` 与数据库基础设施故障做 best-effort 降级，不再把 `RuntimeError("message backend down")` 一类 runtime marker 继续当作消息基础设施错误，避免竞技场消息链静默掩盖契约问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_arena_exchange_helpers.py`、`tests/test_arena_message_boundaries.py`、`tests/test_arena_services.py`、`tests/test_arena_round_helpers.py` 共 `44 passed`，用于约束 `arena` 消息降级口径退出 runtime marker 猜测后不回退。
- `raid` 的战斗后置副作用边界也已继续按阶段 3 收口：`gameplay/services/raid/combat/battle.py` 不再把 `_send_raid_battle_messages()` 与 `_dismiss_marching_raids_if_protected()` 的编程错误统一吞成“记录日志后继续”；当前只对显式消息/基础设施故障做降级，但仍会在返程完成任务派发后把编程错误继续冒泡，避免战斗结果已落库时静默掩盖消息与保护清理契约错误。
- `raid` 的目标失效遣返边界也已继续收紧：`gameplay/services/raid/combat/travel.py` 的 `_retreat_raid_run_due_to_blocked_target()` 不再吞掉消息发送里的编程错误，`resolve_complete_raid_task()` 也只对显式缺少 `gameplay.tasks` 模块做降级，嵌套依赖导入失败与其它契约错误会继续冒泡。
- `raid` 的俘获奖励边界也已继续收紧：`gameplay/services/raid/combat/capture.py` 的 `_delete_captured_guest_gear()` 不再把删装备阶段的编程错误统一吞掉，当前只对显式数据库/基础设施故障做降级；`gameplay/services/raid/combat/battle.py` 的 `_apply_capture_reward()` 也已统一为仅对显式基础设施故障 fail-open，`AssertionError` 等契约错误会继续冒泡，避免俘获奖励链路静默掩盖 gear / capture 契约问题。
- `raid` 的刷新与派发边界也已继续按阶段 3 收口：`gameplay/services/raid/combat/refresh_flow.py` 与 `gameplay/services/raid/combat/run_side_effects.py` 已去掉 import 路径上的 broad catch，当前只对显式缺少 `gameplay.tasks` 模块做同步回退/降级，`AssertionError` 等编程错误会直接冒泡，避免后台刷新与任务派发静默掩盖导入契约错误。
- `raid` 与 `scout` 的消息/派发入口也已继续收紧 runtime marker 兼容：`gameplay/services/raid/combat/start.py` 与 `gameplay/services/raid/scout_followups.py` 的消息发送当前只对显式 `MessageError` 与数据库基础设施故障做降级，不再把 `RuntimeError(\"message backend down\")` 一类 runtime marker 猜测继续当作消息基础设施错误；同时 `dispatch_scout_task()` 已去掉导入路径上的 broad catch，仅对显式缺少 `gameplay.tasks.pvp` 模块做降级，嵌套依赖导入失败与编程错误会继续冒泡。
- `raid/scout` 的刷新 helper 与近期攻击缓存配置边界也已继续按阶段 3 收口：`gameplay/services/raid/scout_refresh.py` 的 `resolve_scout_refresh_tasks()` 已去掉导入路径上的 broad catch，仅对显式缺少 `gameplay.tasks.pvp` 模块做同步回退；`gameplay/services/raid/utils.py` 的 `_recent_attacks_cache_ttl_seconds()` 也不再吞掉任意配置读取异常，当前只对非法 TTL 值做默认值兜底，设置访问契约错误会继续冒泡，避免缓存策略配置问题被静默掩盖。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_raid_scout_refresh.py`、`tests/test_raid_utils_cache.py`、`tests/test_raid_combat_runs.py` 共 `68 passed`，用于约束 `raid/scout` refresh 任务导入与近期攻击缓存配置边界不回退。
- `troop recruitment` 与 `mission` 的完成通知口径也已继续退出 runtime marker 猜测：`gameplay/services/recruitment/lifecycle.py` 的募兵完成站内信和 WebSocket 通知当前只对显式 `MessageError` 与已知通知基础设施故障做降级，不再把 `RuntimeError("message backend down")`、`RuntimeError("ws backend down")` 一类 runtime marker 继续当作可吞错误；同文件的 `schedule_recruitment_completion()` 也已去掉导入路径上的 broad catch，仅对显式缺少 `gameplay.tasks` 模块做跳过调度。`gameplay/services/missions_impl/finalization_helpers.py` 的任务战报消息与通知也同步退出 runtime marker 兼容，继续把模糊 runtime 包装和编程错误暴露出来。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_troop_recruitment_service.py`、`tests/test_mission_refresh_async.py` 共 `32 passed`，用于约束 `troop recruitment` 与 `mission` 完成通知边界退出 runtime marker 猜测后不回退。
- `gameplay/services/utils/notifications.py` 这个 WebSocket 通知总入口也已继续退出 runtime marker 兼容：`notify_user()` 当前只对显式通知基础设施异常做返回 `False` 的降级，不再把 `RuntimeError("notification backend down")` 一类模糊 runtime 包装继续当作 channels 基础设施错误吞掉，避免调用侧被总入口静默掩盖契约问题。
- `mission` 启动韧性边界也已继续退出 runtime marker 猜测：`gameplay/services/missions_impl/launch_resilience.py` 的战报准备与完成任务派发当前只对显式数据库/基础设施故障做降级，不再把 `RuntimeError("report backend unavailable")`、`RuntimeError("dispatch backend unavailable")` 一类 runtime marker 继续当作可吞错误，避免启动主链静默掩盖调度契约问题。
- `raid` 主战斗链上的 runtime marker 兼容也已继续收口：`gameplay/services/raid/combat/battle.py`、`gameplay/services/raid/combat/capture.py`、`gameplay/services/raid/combat/travel.py` 当前只对显式 `MessageError` 与已知数据库/基础设施故障做降级，不再把 `RuntimeError("redis down")`、`RuntimeError("redis timed out")`、`RuntimeError("message backend down")` 一类 runtime marker 继续当作可吞错误，避免来袭消息、俘获奖励和战后清理静默掩盖契约问题。
- `trade / guests / 页面错误映射` 的剩余 runtime marker 兼容也已继续收口：`trade/tasks.py`、`trade/selector_builders.py`、`guests/tasks.py` 与 `guests/services/recruitment_followups.py` 当前都只对显式数据库/基础设施异常或 `MessageError` 做降级，不再把 `RuntimeError("... backend unavailable")`、`RuntimeError("message backend down")` 一类模糊 runtime 包装继续当作可吞错误；`core/utils/view_error_mapping.py` 也同步移除了页面错误分类里的 runtime marker 开关，避免页面层继续把模糊运行时包装误判成基础设施故障。
- `trade/services/market_notification_helpers.py` 与 `core/utils/infrastructure.py` 也已同步完成语义下沉：通用 `is_expected_infrastructure_error()` 不再接受 runtime marker 猜测，cache 兼容被收口到 `is_expected_cache_infrastructure_error()` 这类 cache 专用 helper；交易消息 helper 当前只对显式 `MessageError` 与数据库基础设施故障做 fail-open，不再把 `RuntimeError("message backend down")` 一类模糊 runtime 包装吞成交易成功后的静默降级。
- `trade` 的拍卖通知链也已继续按阶段 3 收口：`trade/services/auction/bidding.py` 的出局提醒，以及 `trade/services/auction/rounds.py` 的中标消息/推送，当前只对显式 `MessageError`、数据库基础设施异常与通知基础设施异常做降级；中标消息的“直接发货” fallback 也不再把 `RuntimeError("message backend down")` 一类模糊 runtime 包装当成可吞错误，避免拍卖消息与发货补偿静默掩盖契约问题。
- `2026-03-22` 已继续补一轮阶段 3 聚焦验证：`tests/test_trade_auction_bidding.py`、`tests/test_trade_auction_rounds.py` 共 `36 passed`，用于约束拍卖出局提醒、中标消息与 direct grant fallback 的异常边界不回退。
- `map` 的 `refresh_raid_activity_api` 已退出 legacy `ValueError` 兼容：写入口默认只把显式 `GameError` 当已知业务错误，裸 `ValueError` 继续冒泡，避免 view 层把程序/契约错误伪装成 400。
- `map` 的目标庄园解析 helper 也已继续收紧：`gameplay/views/map._target_manor_or_error()` 在参数已通过 `safe_positive_int()` 归一化后，不再额外吞掉 `ValueError/TypeError`，查库阶段的异常改为继续冒泡。
- `core` 的 legacy view 装饰器也已退出 `ValueError` 业务语义：`core/decorators.handle_game_errors` 不再捕获裸 `ValueError`，避免新代码继续把 `ValueError` 当跨层业务错误。
- `core` 的错误消息清洗入口也已退出 `ValueError` 业务语义：`core/utils/validation.sanitize_error_message()` 不再直接回显裸 `ValueError` 文案，未显式归类的异常统一退回通用失败消息，避免程序错误泄漏到页面层。
- `core` 的 rate limit 工具也已开始退出裸 `ValueError`：`core/utils/rate_limit._validate_rate_limit_options()` 对非法 `limit/window_seconds` 配置不再抛 `ValueError`，改走显式内部调用契约错误 `AssertionError`。
- `resources` 服务也已开始退出裸 `ValueError`：`gameplay/services/resources._handle_unknown_resource()` 在 debug 下对未知资源类型改走显式内部调用契约错误 `AssertionError`，非 debug 环境继续记录错误并跳过非法资源，不再把该问题伪装成业务异常。
- `chat` 服务入口也已退出 legacy `ValueError` 兼容：`gameplay/services/chat.consume_trumpet()` 不再把裸 `ValueError` 当作特殊输入错误分支处理，库存不足继续走显式 `InsufficientStockError`，其余异常统一按未知失败降级。
- `buildings` 升级入口已不再从 view 直接调用 `refresh_manor_state(...)`；陈旧升级状态改由 `start_upgrade()` 写命令自行收口。
- `refresh_manor_state(...)` 已收紧为默认只处理建筑/资源读侧投影；`mission / scout / raid` 补偿刷新改为显式 `include_activity_refresh=True` 才会触发，避免总刷新入口继续默认扇出到阶段二写链路。
- `guests/roster`、`guests/detail` 的门客状态准备已收口到显式 read helper，不再在 `get_context_data()` 内联推进状态。
- 单会话策略已改为默认 `fail-closed`，但平台级故障语义仍需继续用真实服务门禁验证。
- integration gate 的提示信息、`pytest` 路径和模板/过滤器相关测试已补齐，但真实 MySQL / Redis / Channels / Celery gate 仍不足。

### 2.3 已启动但未封板的跨阶段主题

虽然当前主线仍是阶段 2，但以下主题已经启动，后续可以按“小主题一轮一收口”的方式继续推进：

- `阶段 3` 的异常语义收口已经开始：`trade`、`arena`、`work`、`jail`、`troop recruitment` 和部分资源链路已经退出一部分 legacy `ValueError` 兼容，但 `mission`、`guest recruitment` 等入口仍明显混用 `GameError + ValueError`。
- `mission` 已开始收口主链路异常语义：发起任务与撤退请求开始改走 `MissionError` 子类，但 view 层和部分兼容测试仍保留 `ValueError` 兜底。
- `mission` 的护院 loadout 归一化也已退出裸 `ValueError`：共享 `normalize_mission_loadout(...)` 现在直接抛显式 `TroopLoadoutError`，`AcceptMissionView` 也不再在 view 层重复做业务归一化，护院配置校验重新收口回服务写入口。
- `mission` 的 `accept/retreat/use_card` 视图入口以及 `scout start / retreat`、`raid start / retreat` 共享入口已不再把裸 `ValueError` 当作已知业务错误吞掉；`gameplay/views/mission_action_handlers.py` 里的 legacy `ValueError` 兼容开关也已移除，剩余 legacy `ValueError` 兼容主要还在更底层 battle/locking 输入校验等共享入口。
- `raid/scout` 的双庄园加锁也已开始退出裸 `ValueError`：`gameplay/services/raid/scout.py` 的 `_lock_manor_pair()` 现在直接抛显式 `ScoutStartError`，把“目标庄园不存在”的业务语义留在侦察发起链路内收口。
- `raid` 的 loadout 预备层也已删掉过期兼容壳：`gameplay/services/raid/combat/raid_inputs.py` 不再把 battle 层的显式 `BattlePreparationError` 重新包成 `RaidStartError`，`start_raid_api` 继续通过统一 `GameError` 映射返回业务错误。
- `battle` 的门客技能序列化也已开始退出误吞异常：`battle/combatants_pkg/guest_builder.py` 不再把已保存门客 `skills.all()` 上的裸 `ValueError` 静默吞掉，未保存门客仍走显式空回退，程序错误改为继续冒泡。
- `battle` 的状态伤害惩罚入口也已退出裸 `ValueError`：`battle/simulation/damage_calculation.py` 的 `process_status_effects(..., phase=\"damage_penalty\")` 现在把缺少 `damage` 视为内部调用契约错误，改走显式 `AssertionError`，不再伪装成业务参数异常。
- `raid` 依赖的 battle 预备层异常语义也已开始收口：`battle/setup.py`、`battle/locking.py`、`battle/execution.validate_troop_capacity()` 已开始改走显式 `BattlePreparationError`，但更底层 battle 组件和其它复用路径仍未整体封板。
- `guest recruitment` 已开始收口主链路异常语义：招募发起、放大镜使用、候选保留已改走显式 `RecruitmentError` 子类，`guests/views/recruit_action_runtime.py` 不再把裸 `ValueError` 当作已知业务错误。
- `guest recruitment` 的 flow helper 也已开始退出裸 `ValueError`：`guests/services/recruitment_flow.resolve_recruitment_seed()` 对非法 seed 不再直接泄漏 `int(...)` 的裸异常，统一改走显式内部调用契约错误 `AssertionError`。
- `guest recruitment` 的 flow helper 契约也已继续收紧：`resolve_recruitment_cost()`、`create_pending_recruitment()` 对非法 cost / draw_count / duration 输入不再直接泄漏底层 `dict(...)` / `int(...)` 裸异常，统一改走显式 `AssertionError`。
- `guest recruitment` 的 candidate helper 也已开始退出裸异常：`resolve_candidate_draw_count()` 对非法抽取数量不再直接泄漏 `int(...)` 的裸异常，统一改走显式内部调用契约错误 `AssertionError`。
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
- `inventory` 的仓库通用 `use_item` 链路也已开始退出一批 legacy `ValueError`：`gameplay/services/inventory/use.py` 中免战牌、召唤卡、工具类分发、物品归属校验已改走显式 `ItemError / GuestError`，`gameplay/views/inventory.py` 的通用使用入口不再把裸 `ValueError` 当作已知业务错误；但仓库迁移和其它建筑 / 道具副作用链路仍未整体封板。
- `inventory/core` 的基础库存行操作也已开始退出裸 `ValueError`：`consume_inventory_item_locked()` 与 `consume_inventory_item()` 对未持久化库存行不再抛 `ValueError("物品不存在")`，统一改走显式 `ItemNotFoundError`。
- `inventory/core` 的加库存入口也已开始退出裸 `ValueError`：`add_item_to_inventory_locked()` 对非正数量不再抛 `ValueError("quantity must be positive")`，改为显式内部调用契约错误 `AssertionError`。
- `raid/protection` 的免战牌服务边界也已开始收口：`gameplay/services/raid/protection.py` 已退出 legacy `ValueError`，改走显式 `PeaceShieldUnavailableError`，并成为仓库免战牌使用链路的单一校验来源。
- `raid/relocation` 的庄园迁移服务边界也已开始收口：`gameplay/services/raid/relocation.py` 已退出 legacy `ValueError`，改走显式 `RelocationError`，并补上迁移条件、金条不足、坐标耗尽等服务契约测试。
- `technology` 视图入口也已退出 legacy `ValueError`：`gameplay/views/technology.py` 现在只把显式 `TechnologyError / GameError` 当已知业务错误处理，裸 `ValueError` 改为继续冒泡。
- `building` 升级主入口也已开始收口异常语义：`gameplay/services/manor/core.start_upgrade()` 已把“正在升级 / 达到满级 / 并发上限”改走显式 `BuildingError` 子类，`gameplay/views/buildings.py` 不再把裸 `ValueError` 当已知业务错误处理。
- `production` 的马房 / 畜牧 / 冶炼主入口也已开始收口异常语义：`gameplay/services/buildings/stable.py`、`gameplay/services/buildings/ranch.py`、`gameplay/services/buildings/smithy.py` 已把参数/门槛/并发中的业务 `ValueError` 改走显式 `ProductionStartError`，`gameplay/views/production.py` 不再把裸 `ValueError` 当已知业务错误处理。
- `core` 的庄园改名入口也已开始退出 legacy `ValueError`：`gameplay/services/manor/core.rename_manor()` 已把名称校验、重名冲突、命名卡配置/扣减失败改走显式 `GameError`，`gameplay/views/core.py` 不再把裸 `ValueError` 当已知业务错误处理。
- `forge` 的锻造 / 图纸 / 分解主入口也已开始收口异常语义：`gameplay/services/buildings/forge_runtime.py`、`gameplay/services/buildings/forge_blueprints.py`、`gameplay/services/buildings/forge_decompose.py` 及相关 helper 已把业务 `ValueError` 改走显式 `ForgeOperationError`，`gameplay/views/production_forge_handlers.py` 不再把裸 `ValueError` 当已知业务错误处理。
- `阶段 5` 的测试门禁治理已经开始：hermetic / integration gate 提示、`pytest` 路径和部分边界契约测试已经补齐，但真实外部服务覆盖面仍不足。

### 2.4 当前未完成的高优先级问题

- 阶段 2 的核心验收项已基本具备：`mission / raid / guest recruitment` 的主写入口、refresh 补偿边界、真实并发与 refresh/finalize 竞争语义都已有 real-services 约束；后续剩余工作以封板整理和回归维护为主。
- 项目内仍有不少入口继续把 `ValueError` 作为跨层业务语义，异常层次还没有整体收口。
- 页面读路径虽然已经开始统一，但尚未完全消除局部降级分叉；活动补偿已退出页面隐式读路径，但仍需在阶段 3 持续审视显式刷新入口与错误语义的一致性。

## 3. 后续执行顺序

下一轮优化按以下顺序推进：

1. 完成阶段 2 封板整理，保持 `mission / raid / guest recruitment` 的主写入口、after-commit follow-up 和 refresh command 边界不回退。
2. 沿高频主链路逐步退出 legacy `ValueError` 兼容，优先处理 `mission / guest recruitment` 等仍明显混用的 view/service 入口。
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
