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
- `gameplay/services/raid/scout_refresh.py` 已承接侦察 refresh 补偿命令，`gameplay/services/raid/scout_followups.py` 也开始承接 after-commit 消息/任务派发；`scout.py` 已退回公共入口、状态查询和适配层，但真实服务测试仍需继续收口。
- `gameplay/services/raid/scout_return.py` 已开始承接撤退请求和返程完成写命令；`scout_start.py`、`scout_finalize.py` 现已承接侦察发起/结果写入主写命令，但真实服务测试仍未封板。
- `raid/scout` 已补第一批真实外部服务测试，开始覆盖 refresh dispatch dedup gate、dispatch 失败回滚、同步补偿收口，以及 `complete_scout_task` / `complete_scout_return_task`、`complete_raid_task`（撤退返程）、`process_raid_battle_task` 的实际消费；但并发冲突和更多 battle/refresh 竞争语义仍未封板。
- `mission` 已补第一批真实并发与任务派发语义测试，覆盖同门客并发发起只允许一个 `ACTIVE`、同一 `MissionRun` 并发撤退只允许一个状态迁移成功，以及 refresh dispatch dedup gate / dispatch 失败回滚、`complete_mission_task` 实际消费收口；`gameplay/services/missions_impl/mission_followups.py` 也开始承接 launch 后报告准备、任务导入与 completion dispatch，但更多补偿场景仍未封板。
- `guest recruitment` 已开始补真实服务语义测试，覆盖并发发起只允许一个 `PENDING`、并发完成只允许一次 `PENDING -> COMPLETED` 收口，以及候选确认只允许一次转正；`guests/services/recruitment_followups.py` 也开始承接完成任务派发与通知发送，但更多 `select_for_update` 竞争场景仍未封板。
- `map` 的 `refresh_raid_activity_api` 已退出 legacy `ValueError` 兼容：写入口默认只把显式 `GameError` 当已知业务错误，裸 `ValueError` 继续冒泡，避免 view 层把程序/契约错误伪装成 400。
- `core` 的 legacy view 装饰器也已退出 `ValueError` 业务语义：`core/decorators.handle_game_errors` 不再捕获裸 `ValueError`，避免新代码继续把 `ValueError` 当跨层业务错误。
- `core` 的错误消息清洗入口也已退出 `ValueError` 业务语义：`core/utils/validation.sanitize_error_message()` 不再直接回显裸 `ValueError` 文案，未显式归类的异常统一退回通用失败消息，避免程序错误泄漏到页面层。
- `core` 的 rate limit 工具也已开始退出裸 `ValueError`：`core/utils/rate_limit._validate_rate_limit_options()` 对非法 `limit/window_seconds` 配置不再抛 `ValueError`，改走显式内部调用契约错误 `AssertionError`。
- `resources` 服务也已开始退出裸 `ValueError`：`gameplay/services/resources._handle_unknown_resource()` 在 debug 下对未知资源类型改走显式内部调用契约错误 `AssertionError`，非 debug 环境继续记录错误并跳过非法资源，不再把该问题伪装成业务异常。
- `buildings` 升级入口已不再从 view 直接调用 `refresh_manor_state(...)`；陈旧升级状态改由 `start_upgrade()` 写命令自行收口。
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

- `mission / raid / guest recruitment` 的真实并发语义测试仍然不够；虽然 `mission` 发起/撤退、refresh dispatch / worker 消费，`scout` refresh dispatch / worker 消费，`raid` 发起/撤退、battle worker、撤退返程 worker 消费，`guest recruitment` 发起/完成/候选确认已覆盖首批关键竞争与派发语义，但更多 refresh 补偿链路和 battle/return 并发竞争仍是缺口。
- 项目内仍有不少入口继续把 `ValueError` 作为跨层业务语义，异常层次还没有整体收口。
- 页面读路径虽然已经开始统一，但尚未完全消除显式补偿调用、局部降级分叉，以及 `refresh_manor_state(...)` 这一类总刷新入口的扩散风险。

## 3. 后续执行顺序

下一轮优化按以下顺序推进：

1. 继续收口 `mission / raid / guest recruitment` 的主写入口、after-commit follow-up 和 refresh command 边界。
2. 为高风险写链路补真实外部服务测试，优先覆盖数据库锁、缓存/通道、任务派发与补偿刷新语义。
3. 沿高频主链路逐步退出 legacy `ValueError` 兼容，优先处理 `mission / guest recruitment` 等仍明显混用的 view/service 入口。
4. 在阶段 2 关键链路具备真实测试约束后，再推进模板、页面脚本和前端交互边界治理。

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
