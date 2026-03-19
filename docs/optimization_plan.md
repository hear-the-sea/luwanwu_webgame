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
- 页面读路径已开始统一到请求级 helper：`trade/page_context.py`、`gameplay/views/core.py`、`gameplay/views/map.py`、`gameplay/views/inventory.py`、`gameplay/views/messages.py`、`gameplay/views/work.py`、`gameplay/views/technology.py`、`gameplay/views/recruitment.py`、`gameplay/views/arena.py`、`gameplay/views/mission_page_context.py`、`gameplay/views/production_page_context.py`、`guests/views/roster.py` 已接入 `get_prepared_manor_for_read(...)`。
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

- `HomeView`、`MapView`、`raid_status_api` 已开始向统一请求级入口收口 `raid/scout` 读侧 refresh，但其它页面和真实服务门禁仍未让这条链路整体封板。
- `gameplay/services/raid/scout_refresh.py` 已开始承接侦察 refresh 补偿命令，但 `scout.py` 的其它动作边界和真实服务测试仍需继续收口。
- `gameplay/services/raid/scout_return.py` 已开始承接撤退请求和返程完成写命令；`scout_start.py`、`scout_finalize.py` 现已承接侦察发起/结果写入主写命令，但真实服务测试仍未封板。
- `raid/scout` 已补第一批真实外部服务测试，开始覆盖 refresh dispatch dedup gate、dispatch 失败回滚和同步补偿收口；但并发冲突与 worker 实际消费语义仍未封板。
- `buildings` 升级入口已不再从 view 直接调用 `refresh_manor_state(...)`；陈旧升级状态改由 `start_upgrade()` 写命令自行收口。
- `guests/roster`、`guests/detail` 的门客状态准备已收口到显式 read helper，不再在 `get_context_data()` 内联推进状态。
- 单会话策略已改为默认 `fail-closed`，但平台级故障语义仍需继续用真实服务门禁验证。
- integration gate 的提示信息、`pytest` 路径和模板/过滤器相关测试已补齐，但真实 MySQL / Redis / Channels / Celery gate 仍不足。

### 2.3 已启动但未封板的跨阶段主题

虽然当前主线仍是阶段 2，但以下主题已经启动，后续可以按“小主题一轮一收口”的方式继续推进：

- `阶段 3` 的异常语义收口已经开始：`trade`、`arena` 和部分资源链路已经退出一部分 legacy `ValueError` 兼容，但 `mission`、`recruitment`、`jail`、`work` 等入口仍大量混用 `GameError + ValueError`。
- `guest recruitment` 已开始收口主链路异常语义：招募发起、放大镜使用、候选保留已改走显式 `RecruitmentError` 子类，`guests/views/recruit_action_runtime.py` 不再把裸 `ValueError` 当作已知业务错误。
- `阶段 5` 的测试门禁治理已经开始：hermetic / integration gate 提示、`pytest` 路径和部分边界契约测试已经补齐，但真实外部服务覆盖面仍不足。

### 2.4 当前未完成的高优先级问题

- `mission / raid / guest recruitment` 的真实并发语义测试仍然不够，尤其是 `select_for_update`、任务派发和 refresh 补偿链路。
- 项目内仍有不少入口继续把 `ValueError` 作为跨层业务语义，异常层次还没有整体收口。
- 页面读路径虽然已经开始统一，但尚未完全消除显式补偿调用、局部降级分叉，以及 `refresh_manor_state(...)` 这一类总刷新入口的扩散风险。

## 3. 后续执行顺序

下一轮优化按以下顺序推进：

1. 继续收口 `mission / raid / guest recruitment` 的主写入口、after-commit follow-up 和 refresh command 边界。
2. 为高风险写链路补真实外部服务测试，优先覆盖数据库锁、缓存/通道、任务派发与补偿刷新语义。
3. 沿高频主链路逐步退出 legacy `ValueError` 兼容，优先处理 `mission / recruitment / jail / work` 等仍明显混用的 view/service 入口。
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
