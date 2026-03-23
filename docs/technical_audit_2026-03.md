# 项目重构优化规则与阶段目标（2026-03）

最近更新：2026-03-23

本文档不记录详细审计过程、历史数据或阶段性结果，只保留后续重构必须遵守的规则，以及各阶段的优化目标。

相关文档：

- [架构设计](architecture.md)
- [开发指南](development.md)
- [优化计划](optimization_plan.md)
- [数据流边界](domain_boundaries.md)
- [第二阶段统一写模型基线](write_model_boundaries.md)

## 0. 当前基线（2026-03-23）

本文档原则上不展开完整审计过程，但为避免规则与仓库现实脱节，仍保留当前治理基线与未收口项摘要。

- 2026-03-21 本地验证：`make lint` 通过。
- 2026-03-21 本地验证：默认 `make test` 通过，结果为 `1852 passed, 28 deselected`。
- 2026-03-23 本轮验证：`make lint` 通过。
- 2026-03-23 本轮验证：默认 `make test` 通过，结果为 `2248 passed, 38 deselected`。
- 2026-03-23 本轮验证：阶段 3 收口后再次执行 `make lint` 通过。
- 2026-03-23 本轮验证：阶段 3 收口后再次执行默认 `make test` 通过，结果为 `2350 passed, 38 deselected`。
- 2026-03-23 本轮验证：`DJANGO_TEST_USE_ENV_SERVICES=1 REDIS_URL=redis://127.0.0.1:6379 REDIS_BROKER_URL=redis://127.0.0.1:6379/0 REDIS_RESULT_URL=redis://127.0.0.1:6379/0 REDIS_CHANNEL_URL=redis://127.0.0.1:6379/1 REDIS_CACHE_URL=redis://127.0.0.1:6379/2 python -m pytest tests/test_mission_concurrency_integration.py tests/test_guest_recruitment_concurrency_integration.py -q` 通过，结果为 `6 passed, 1 skipped`。
- 2026-03-22 本轮验证：`pytest tests/test_trade_auction_rounds.py -q` 通过，结果为 `30 passed`。
- 2026-03-22 本轮验证：`pytest tests/test_inventory_guest_items.py -q` 通过，结果为 `16 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_summon_card.py -q` 通过，结果为 `29 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_inventory_views.py -k "use_item_ajax" -q` 通过，结果为 `4 passed, 25 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_equipment_service_contracts.py tests/test_guest_item_view_validation.py -k "gear_options or equip_view or equipment_service_contracts" -q` 通过，结果为 `12 passed, 24 deselected`。
- 2026-03-23 本轮验证：`pytest tests/inventory_guest_items/soul_container.py tests/test_guest_roster_service.py -q` 通过，结果为 `8 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_gameplay_services.py -k "grant_resources or spend_resources or sync_resource_production" -q` 通过，结果为 `16 passed, 13 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_item_view_validation.py tests/test_guest_view_error_boundaries.py -k "use_medicine_item_view or learn_skill_view or forget_skill_view" -q` 通过，结果为 `19 passed, 55 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_runtime_refresh_views.py -q` 通过，结果为 `5 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_item_view_validation.py tests/test_guest_view_error_boundaries.py -k "use_experience_item_view or allocate_points_view or train" -q` 通过，结果为 `15 passed, 60 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_inventory_views.py -k "use_rebirth_card or use_xisuidan or use_xidianka or use_guest_rarity_upgrade or use_soul_container" -q` 通过，结果为 `10 passed, 20 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_treasury_move_service_contracts.py -q` 通过，结果为 `2 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guilds.py tests/test_guild_view_helpers.py -q` 通过，结果为 `39 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guilds.py -k "create_guild or upgrade_guild or update_guild_info or disband_guild" -q` 通过，结果为 `10 passed, 16 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_guild_hero_pool.py tests/test_guild_hero_pool_views.py -q` 通过，结果为 `13 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guild_view_helpers.py tests/test_guilds_technology_service.py -q` 通过，结果为 `17 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guilds_tasks.py -k "process_single_guild_production_missing_guild_id_bubbles_up" -q` 通过，结果为 `1 passed, 21 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_bootstrap_game_data_command.py tests/test_load_item_templates_command.py tests/test_check_guild_schema_command.py -q` 通过，结果为 `10 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_trade_cache_resilience.py -q` 通过，结果为 `12 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_accounts_utils.py -q` 通过，结果为 `20 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_raid_combat_battle.py -q` 通过，结果为 `37 passed`。
- 2026-03-23 本轮验证：`python -m mypy accounts/admin.py gameplay/admin/__init__.py gameplay/admin/arena.py gameplay/admin/buildings.py gameplay/admin/core.py gameplay/admin/inventory.py gameplay/admin/messages.py gameplay/admin/missions.py gameplay/admin/raids.py guests/admin.py guilds/admin.py trade/admin.py core/views/health_support.py gameplay/management/commands/arena_quick_test.py gameplay/management/commands/cleanup_data_report.py gameplay/management/commands/cleanup_old_data.py gameplay/management/commands/bootstrap_game_data.py gameplay/management/commands/load_building_templates.py gameplay/management/commands/load_item_templates.py gameplay/management/commands/load_mission_templates.py gameplay/management/commands/load_technology_templates.py gameplay/management/commands/reload_runtime_configs.py gameplay/management/commands/seed_work_templates.py gameplay/management/commands/validate_yaml_configs.py guilds/management/commands/check_guild_schema.py gameplay/views/arena.py gameplay/views/buildings.py gameplay/views/mission_action_handlers.py gameplay/views/mission_helpers.py gameplay/views/mission_page_context.py gameplay/views/production_forge_handlers.py gameplay/views/read_helpers.py guilds/views/announcement.py guilds/views/contribution.py guilds/views/core.py guilds/views/hero_pool.py guilds/views/helpers.py guilds/views/membership.py guilds/views/technology.py guilds/views/warehouse.py` 通过。
- 2026-03-23 本轮验证：`python -m mypy accounts/views.py battle/management/commands/load_troop_templates.py guests/views/common.py guests/views/read_helpers.py guests/views/recruit_action_runtime.py guests/views/recruit_handlers.py guests/views/salary.py` 通过。
- 2026-03-23 本轮验证：`python -m mypy battle/admin.py battle/views.py battle/management/commands/__init__.py battle/management/commands/load_troop_templates.py core/views/__init__.py gameplay/management/commands/__init__.py gameplay/views/__init__.py guests/management/commands/__init__.py guests/views/__init__.py accounts/views.py guests/views/common.py guests/views/read_helpers.py guests/views/recruit_action_runtime.py guests/views/recruit_handlers.py guests/views/salary.py` 通过。
- 2026-03-23 本轮验证：`python -m mypy battle_debugger/__init__.py battle_debugger/config.py battle_debugger/simulator.py battle_debugger/urls.py battle_debugger/views.py battle_debugger/management/commands/__init__.py battle_debugger/management/commands/battle_debug.py gameplay/admin/__init__.py guests/management/commands/test_recruitment.py guests/templatetags/__init__.py guests/templatetags/guest_extras.py guilds/management/commands/__init__.py guilds/views/__init__.py` 通过。
- 2026-03-23 本轮验证：`python -m mypy gameplay/models/__init__.py gameplay/models/arena.py gameplay/models/items.py gameplay/models/manor.py gameplay/models/missions.py gameplay/models/progression.py gameplay/models/pvp.py` 通过。
- 2026-03-23 本轮验证：宽泛 `ignore_errors = true` 规则已删除，按脚本扫描当前生产代码命中的剩余模块数为 `0`。
- 2026-03-23 本轮验证：`guilds.views.helpers`、`guilds.views.hero_pool` 与 `guilds.views.technology` 已升入 `disallow_untyped_defs = true` 严格名单，并完成对应签名补齐。
- 2026-03-23 本轮验证：`guilds.views.announcement`、`guilds.views.contribution` 与 `guilds.views.core` 已升入 `disallow_untyped_defs = true` 严格名单，并完成对应签名补齐。
- 2026-03-23 本轮验证：生产代码 `except Exception` 扫描结果为 `0`。
- 2026-03-23 本轮验证：生产代码 `raise ValueError(...)` 扫描结果为 `0`。
- 2026-03-23 本轮验证：`python -m mypy websocket/consumers/world_chat.py config/asgi.py config/settings/testing.py battle/management/commands/load_troop_templates.py` 通过。
- 2026-03-23 本轮验证：`pytest tests/test_world_chat_consumer.py tests/test_asgi.py tests/test_management_command_validation.py -q` 通过，结果为 `26 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_accounts_utils.py tests/test_coverage_misc_imports.py -q` 通过，结果为 `23 passed`。
- 2026-03-23 本轮验证：`python -m mypy common/utils/random_utils.py tests/test_random_utils.py` 通过。
- 2026-03-23 本轮验证：`pytest tests/test_random_utils.py -q` 通过，结果为 `2 passed`。
- 2026-03-23 本轮验证：阶段 4 首轮治理中，`guests/templates/guests/detail.html` 的页面专属脚本已迁移到 `static/js/guest-detail.js`；`pytest tests/test_guest_runtime_refresh_views.py tests/test_guest_allocate_points_view.py tests/test_guest_view_error_boundaries.py -q` 通过，结果为 `51 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_item_view_validation.py -k "gear_options" -q` 通过，结果为 `4 passed, 30 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_runtime_refresh_views.py tests/test_salary_views.py tests/test_guest_item_view_validation.py -k "use_exp_item or use_medicine_item or roster or detail or salary" -q` 通过，结果为 `23 passed, 29 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_inventory_views.py -k "warehouse or move_item_to_warehouse or move_item_to_treasury or use_rebirth_card or use_xisuidan or use_xidianka or use_guest_rarity_upgrade or use_soul_container or use_item_ajax" -q` 通过，结果为 `26 passed, 5 deselected`。
- 2026-03-23 本轮验证：修正历史迁移中招募卡池 `cooldown_seconds` 默认基线后，`pytest tests/test_inventory_views.py -q` 通过，结果为 `31 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_inventory_views.py tests/test_guest_item_view_validation.py -k "recruitment_hall or recruit_view_ajax or candidate_accept_view or use_magnifying_glass_view" -q` 通过，结果为 `17 passed, 49 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_message_views.py -q` 通过，结果为 `14 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_mission_views.py -q` 通过，结果为 `28 passed`。
- 2026-03-23 本轮验证：`python -m mypy` 覆盖当前工作区修改的 `accounts / battle_debugger / core / gameplay / guests / guilds / trade` 相关文件通过；阶段 3 关键回归测试组合为 `204 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_recruitment_flow_helpers.py -q` 通过，结果为 `25 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_recruitment_service.py -k "bulk_finalize_candidates" -q` 通过，结果为 `4 passed, 30 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_recruitment_service.py -k "bulk_finalize_candidates or finalize_guest_recruitment_rejects_unpersisted_recruitment or refresh_guest_recruitments" -q` 通过，结果为 `7 passed, 29 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_guests.py -k "schedule_guest_recruitment_completion or finalize_guest_recruitment" -q` 通过，结果为 `11 passed, 14 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_mission_sync_report.py -q` 通过，结果为 `16 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_mission_finalization_helpers.py -q` 通过，结果为 `11 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_battle_salvage.py -q` 通过，结果为 `10 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_mission_salvage_side_filter.py -q` 通过，结果为 `5 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_mission_drops_service.py -q` 通过，结果为 `12 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_mission_refresh_async.py -q` 通过，结果为 `32 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_recruitment_finalize_helpers.py -q` 通过，结果为 `8 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_mission_attempts_service.py -q` 通过，结果为 `4 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_gameplay.py -k "normalize_mission_loadout or mission_loadout_service or mission_travel_time or resolve_max_squad_size or resolve_base_travel_time or calculate_travel_time or prepare_launch_inputs" -q` 通过，结果为 `15 passed, 20 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_gameplay.py -k "request_retreat" -q` 通过，结果为 `3 passed, 19 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_guest_view_error_boundaries.py -k "candidate_accept or magnifying_glass" -q` 通过，结果为 `3 passed, 38 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_battle_ai_generator_contracts.py tests/test_battle_tasks_generate_report_task.py -q` 通过，结果为 `20 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_battle.py -k "snapshot" -q` 通过，结果为 `19 passed, 24 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_core_views.py -k "home_page_raid_scout_countdowns_use_explicit_refresh_api or home_page_uses_external_landing_script_for_retreat_and_collapse_actions" -q` 通过，结果为 `2 passed, 19 deselected`。
- 2026-03-23 本轮验证：`pytest tests/test_map_views.py tests/test_message_views.py -q` 通过，结果为 `57 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_production_views.py -q` 通过，结果为 `23 passed`。
- 2026-03-23 本轮验证：`pytest tests/test_work_views.py tests/test_forge_views.py tests/test_map_views.py tests/test_arena_views.py -q` 通过，结果为 `108 passed`。
- 2026-03-23 本轮验证：`rg -n "<script>(?!.*application/ld\\+json)|onclick=|onchange=|onsubmit=|oninput=|onblur=|onfocus=" templates gameplay/templates guests/templates -g '*.html' -P` 无输出，阶段 4 范围内模板内联脚本与内联事件扫描结果为 `0`。
- 2026-03-23 本轮验证：`pytest tests/test_core_views.py -k "home_page_uses_external_landing_script_for_retreat_and_collapse_actions" -q` 与 `pytest tests/test_message_views.py -k "message_detail_page_loads_external_page_script_without_inline_logic" -q` 均通过，结果分别为 `1 passed, 20 deselected` 与 `1 passed, 14 deselected`；`rg -n "<style>|style=\"" templates/landing.html gameplay/templates/gameplay/message_detail.html` 无输出，首页与消息详情页的页面级内联样式也已完成外迁。
- 2026-03-21 依赖图/导入链复核：`config/urls.py`、`gameplay/context_processors.py`、`gameplay/views/arena.py`、`guests/urls.py`、`guilds/urls.py` 已改为显式子模块导入，不再依赖 `gameplay.views`、`gameplay.selectors`、`guests.views`、`guilds.views` 包根聚合入口。
- 2026-03-21 包边界复核：`gameplay/views/__init__.py`、`gameplay/selectors/__init__.py`、`guests/views/__init__.py`、`guilds/views/__init__.py` 已收口为无副作用最小包标记文件，不再承担跨模块 re-export 责任。
- 阶段 4 的模板/前端边界主线已完成当前封板：`guests/templates/guests/detail.html`、`guests/templates/guests/roster.html`、`templates/landing.html`、`gameplay/templates/gameplay/warehouse.html`、`gameplay/templates/gameplay/recruitment_hall.html`、`gameplay/templates/gameplay/messages.html`、`gameplay/templates/gameplay/message_detail.html`、`gameplay/templates/gameplay/tasks.html`、`gameplay/templates/gameplay/map.html`、`gameplay/templates/gameplay/smithy.html`、`gameplay/templates/gameplay/stable.html`、`gameplay/templates/gameplay/ranch.html`、`gameplay/templates/gameplay/work.html`、`gameplay/templates/gameplay/forge.html`、`gameplay/templates/gameplay/raid_config.html` 与 `gameplay/templates/gameplay/arena/registration.html` 的页面专属脚本均已迁移到 `static/js/*.js` 外链模块，阶段 4 范围内模板内联脚本与内联事件扫描结果已清零；其中 `landing.html` 与 `message_detail.html` 的页面级样式也已进一步迁移到 `static/css/*.css`，用于收掉本轮最后两处明显的页面样式热点。超大测试文件已开始收缩，`tests/test_trade_auction_rounds.py`、`tests/test_inventory_guest_items.py` 均已收口为薄入口并拆到各自 `tests/*/` 子模块，但仍有多份 `>800` 行测试文件待治理。

## 1. 重构优化规则

### R1. 先定边界，再做拆分

- 不以“抽 helper / 拆文件数量增加”作为完成标准。
- 拆分前必须先明确 view、selector、service、infrastructure 的职责边界。
- 优先按业务动作、状态流转和补偿职责组织模块，不按工具函数类型切碎文件。
- 如果复杂度只是从一个大文件搬到多个 orchestrator / runtime / handler 中，不算优化完成。

### R2. 先定错误语义，再谈统一异常处理

- 禁止继续把 `ValueError`、`RuntimeError`、裸 `Exception` 混合作为默认跨层语义。
- 必须显式区分业务错误、基础设施错误、程序错误。
- view 层只负责异常映射，不负责猜测异常类别。
- 基础设施异常翻译应收口到适配层，不继续在业务层和页面层扩散。

### R3. 读写职责必须分离

- selector 必须保持只读，不承担状态推进、副作用和补偿扫描。
- 页面读请求如需读侧投影、缓存补偿或状态刷新，必须走统一入口。
- 禁止把“读取前顺手修状态”继续藏在 accessor、context builder 或 selector 内部。
- 写操作必须由明确 service / command 入口承接。

### R4. 基础设施故障策略必须平台统一

- 单会话、缓存、通知、在线状态、任务分发等故障语义，必须统一定义 `fail-open` 或 `fail-closed`。
- 禁止单个业务模块私自决定全局故障口径。
- 没有真实环境验证前，不得把局部收紧直接视为平台封板结论。

### R5. 测试必须约束边界

- 重构不能只补“这次改动能过”的回归测试，必须补边界契约测试。
- 统一异常映射、统一读路径入口、统一降级策略、公开 service 入口都必须有测试约束。
- 默认 `make test`、`make lint` 任一不绿时，优先恢复绿灯，不继续扩散改动范围。
- 默认门禁不绿时，禁止继续功能开发和结构性重构；确需临时绕过时，必须在优化计划中明确风险、范围和回收时间。
- 真实外部服务 gate 需要逐步覆盖并发、缓存、任务派发和通道语义。

### R6. 文档必须先于第二轮大拆分

- 在继续推进热点重构前，必须先固化模块边界、错误策略和基础设施规则。
- 没有文档约束的大拆分，默认视为高风险操作。
- 优化计划必须服从本文档；若冲突，以本文档为准。

### R7. 依赖方向必须显式受控

- 不能只声明职责边界，必须同时约束依赖方向。
- `selector / query / page_context` 禁止依赖 `view`、模板 helper、HTTP 适配层。
- `service` 禁止依赖 `HttpRequest`、`messages`、模板渲染或页面跳转逻辑。
- `context_processor`、middleware、consumer 等系统级入口禁止 import 热点业务包的聚合导出，只能依赖明确子模块。

### R8. 禁止包级聚合导入扩大耦合面

- 热点业务包的 `__init__.py` 不得继续承担全量 re-export 和跨模块聚合导入职责。
- 禁止为了“导入方便”把整个 `views/`、`selectors/`、`services/` 包在 import 时一次性拉起。
- 新增模块若需要对外暴露入口，应通过显式子模块路径导入，不得依赖隐式包初始化副作用。
- 已存在的聚合导入必须逐步拆除；修复循环依赖时优先删除聚合依赖，而不是继续增加延迟导入补丁。

### R9. 模板与前端边界不得继续恶化

- 在后端边界尚未完全稳定前，也禁止继续把新增页面状态机、AJAX 流程和复杂交互堆入模板内联脚本。
- 新增前端交互默认进入 `static/js` 或明确页面脚本模块，不再接受大段 `onclick`、内联事件处理和模板内业务流程编排。
- 基模板只能承载全局必需能力，不得继续吸纳页面专属逻辑。
- 模板拆分必须与页面脚本边界同步推进，避免只拆 HTML 不收口交互状态。

### R10. 必须控制复杂度预算，而不是转移复杂度

- 单文件、单模板、单测试文件体量超过团队可维护阈值时，必须拆分并说明新的边界和调用链。
- 拆分验收标准不是文件数量变多，而是入口更清晰、依赖更少、认知负担下降。
- 新增 `helper / runtime / handler / orchestrator` 前，必须先说明其职责边界以及为什么现有入口无法承接。
- 禁止用“兼容层”“转发层”“薄封装”无限叠加目录层级来掩盖热点复杂度。

### R11. 临时兼容方案必须带退出条件

- 临时兼容、降级开关、桥接适配层、回退逻辑必须在文档或计划中写明退出条件。
- 每个临时方案至少要包含：负责人、适用范围、目标收口阶段或版本、删除条件。
- 没有退出条件的“临时方案”，视同新增长期技术债，必须单独登记和追踪。
- 若兼容逻辑已经阻碍依赖收口、异常收口或测试门禁，应优先清理，不得继续叠加外围补丁。

### R12. 审计文档必须维护当前治理基线

- 审计文档可以省略详细过程，但不能省略当前治理基线、主要未收口项和最近一次门禁验证结论。
- 若仓库现实已与文档假设不一致，应优先更新基线，再继续推进下一轮重构。
- 阶段完成声明必须基于已记录的验证结果，不得仅凭主观判断宣布“已收口”或“已稳定”。
- 默认门禁、聚合导入、热点复杂度等高风险主题，必须在文档或配套计划中保留最新状态摘要。

## 2. 阶段目标

### 阶段 1：先稳边界

目标：

- 收口热点页面入口，降低 view 主文件的职责密度。
- 把读侧 page context 与写动作入口分开。
- 清理热路径中的动态 import、callback 空转层和无意义兼容壳。
- 拆除热点包的聚合导入与循环依赖入口。
- 为后续第二阶段固化更清晰的 view / selector / service 边界。

完成标志：

- 热点 view 不再同时承担页面装配、写动作 orchestration、异常包装和跨域协调。
- 读侧上下文构建与写动作处理各有明确入口。
- 默认 `make test` 与 `make lint` 在边界调整后仍持续为绿。
- 热点模块不再从 `gameplay.selectors`、`gameplay.views` 等包根聚合入口导入核心符号。
- 热点业务包的 `__init__.py` 不再承担跨模块 re-export 责任，或已被明确限制为无副作用的最小导出。
- 已记录一次带日期的依赖图/导入链复核结果，确认主要循环依赖入口已收口。

### 阶段 2：再稳并发与测试

目标：

- 为 `mission / raid / guest recruitment` 固化统一写模型。
- 明确主写入口、after-commit follow-up、refresh command、补偿边界。
- 继续把读路径中的补偿职责外迁，禁止新增隐藏副作用 accessor。
- 为高风险写路径补真实外部服务测试，而不只依赖 hermetic 套件。

完成标志：

- 关键链路的锁职责、状态推进、补偿入口都能被清楚说明。
- 页面读请求不再承担隐式补偿职责。
- 真实环境测试开始覆盖关键并发与任务派发语义。

### 阶段 3：收紧门禁

目标：

- 建立显式异常层次，逐步退出 legacy `ValueError` 兼容语义。
- 收缩 broad `except Exception` 与 runtime marker 猜测。
- 继续缩小 mypy 的 `ignore_errors` 范围。
- 重新评估 coverage 盲区，让门禁覆盖高变更入口。
- 为默认测试、覆盖率或热点路径覆盖建立更明确的失败阈值。

完成标志：

- 高风险主链路的异常类型、降级口径和页面映射关系清晰稳定。
- 类型门禁和覆盖率门禁开始对热点路径形成真实约束。
- 默认门禁失败能够阻断问题继续扩散，而不是只在文档中提示。

### 阶段 4：治理模板与前端边界

目标：

- 在后端边界稳定后，集中拆分最大模板和页面脚本。
- 把内联交互、页面状态逻辑和大段样式逐步从模板中抽离。
- 降低基模板承担的全局大杂烩职责。
- 清理历史内联事件和页面级脚本散落问题，建立稳定的脚本归属规则。

完成标志：

- 高复杂页面具备稳定 partial / component 边界。
- 前端交互逻辑不再继续散落在模板内联代码中。
- 新增页面默认不再引入大段模板内联 JS。

### 阶段 5：测试与发布质量

目标：

- 拆分超大测试文件，按业务域整理测试资产。
- 建立更清晰的 hermetic / integration 测试边界。
- 为并发、库存、撤退、报名、任务派发等关键路径增加回归测试。
- 保持默认门禁与真实外部服务门禁都可持续运行。

完成标志：

- 测试目录、fixture、builder、integration gate 的结构更稳定。
- 默认测试和真实环境测试各自覆盖的职责清晰可说明。
- 超大测试文件和“只涨不拆”的测试资产开始收缩。

## 2.1 默认复杂度预算

以下阈值作为默认治理基线；若因明确业务原因暂时超出，必须在 ADR、优化计划或对应模块文档中写明豁免原因与回收时间。

- Python 业务代码文件：默认不超过 400 行；超过 600 行视为热点治理对象。
- 模板文件：默认不超过 300 行；超过 500 行视为热点治理对象。
- 测试文件：默认不超过 500 行；超过 800 行视为热点治理对象。
- 单次新增内联脚本：默认不超过 30 行；超过该阈值应迁移到独立脚本模块。
- 新增 `helper / runtime / handler / orchestrator` 文件时，若只是转发现有调用链且未降低依赖复杂度，默认不予接受。

### 阶段 6：运维与长期治理

目标：

- 补齐结构化日志、任务监控、失败告警和运行手册。
- 评估历史 migration、缓存策略、异步任务治理和运维流程。
- 让文档持续跟随真实目录结构与运行语义，而不是滞后于代码。

完成标志：

- 开发、测试、上线、回滚和排障流程具备统一口径。
- 文档、门禁和运行时语义保持一致。

## 3. 当前执行原则

后续每一轮优化都应满足以下要求：

1. 一轮只推进一个可验证主题，不做大爆炸式重构。
2. 每轮改动都要同步补测试和文档。
3. 每轮结束都要说明这轮改动对应了哪些规则、推进了哪个阶段目标。
4. 如果某项改动仍是临时兼容方案，必须写明下一步收口点，以及负责人、目标阶段/版本和删除条件。
5. 每轮结束都要检查是否新增了违反依赖方向的 import、包级聚合导入或模板内联交互。
6. 涉及热点边界的重构验收，除测试外还必须复核依赖图、导入链和关键调用链是否变短、变清晰。
7. 每轮结束都要记录最近一次默认门禁验证日期、执行命令、结果摘要；没有记录则不得声称门禁已恢复稳定。
