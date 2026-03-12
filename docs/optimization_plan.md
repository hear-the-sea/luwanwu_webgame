# 项目全方位优化计划

本文档给出 `web_game_v5` 的分阶段优化路线，并标记首批已落地项。

## 2026-03-09 当前执行面

### 本轮目标

- 先做低风险、可回归、能持续削减复杂度的收敛工作。
- 每轮只推进一个可验证的小主题，避免“大爆炸式重构”。
- 每完成一个主题，都要求补文档、补测试、补最小验证命令。

### 执行顺序

1. 模板加载工具收敛：合并重复 helper，减少查询工具分叉。
2. `battle/views.py` / `gameplay/views/production.py` 上下文拼装下沉到 selector/helper。
3. 拆分 `guests/services/recruitment.py` 为缓存、抽取、落库、通知四层。
4. 拆分 `gameplay/services/buildings/forge.py` 为配置、蓝图、分解、排程四层。
5. 收缩 `gameplay/services/__init__.py` 兼容出口，限制新增代码继续从聚合层导入。

### 本轮已完成的收敛项

- `gameplay/utils/template_loader.py` 已向 `core/utils/template_loader.py` 收敛，保留兼容 API，减少重复查询实现。
- `battle/view_helpers.py` 已抽离战报视图中的展示辅助逻辑，并合并掉落/损失标签查询。
- `gameplay/views/production_helpers.py` 已抽离锻造页分类、排序、图纸标注等纯逻辑。
- `guests/services/recruitment_templates.py` 已抽离招募模板缓存、稀有度搜索与模板选择逻辑。
- `gameplay/services/buildings/forge_config_helpers.py` 已抽离铁匠铺配置归一化逻辑。
- `gameplay/services/arena/helpers.py` 已抽离竞技场纯计算与轮次辅助逻辑。
- `gameplay/services/arena/snapshots.py` 已抽离竞技场报名快照构建与快照代理逻辑。

## 目标

- 降低核心模块复杂度，减少大文件和兼容层长期膨胀。
- 提升可观测性，让线上问题能快速定位到请求、任务、模块。
- 继续强化类型、测试、配置校验，降低回归成本。
- 在不打断现有业务迭代的前提下，逐步推进重构。

## 阶段 1：低风险高收益（本轮优先）

- 日志链路补全：为应用日志统一接入 `request_id`，访问日志独立配置。
- 视图解耦：将任务视图中的纯辅助逻辑拆出，降低单文件职责密度。
- 回归测试：为日志配置、任务辅助函数补充轻量测试。
- 文档沉淀：把优化目标和顺序固化为可执行清单。
- 工具收敛：减少同类 helper 的重复实现，优先统一模板加载、缓存 key、轻量通用查询工具。

### 本轮已完成

- `config/settings/logging_conf.py`：接入 `RequestIDFilter`，并为 `access` logger 配置独立 handler。
- `gameplay/views/mission_helpers.py`：抽离任务视图辅助逻辑。
- `gameplay/views/missions.py`：改为消费 helper，降低文件复杂度。
- `tests/test_logging_configuration.py`：新增日志配置回归测试。
- `tests/test_mission_helper_functions.py`：新增任务辅助函数回归测试。

### 本轮新增启动项

- `gameplay/utils/template_loader.py`：开始收敛到 `core/utils/template_loader.py` 的统一实现。
- `battle/views.py`：开始向 `battle/view_helpers.py` 下沉展示辅助逻辑。
- `gameplay/views/production.py`：开始向 `gameplay/views/production_helpers.py` 下沉纯上下文拼装逻辑。
- `guests/services/recruitment.py`：开始拆分模板缓存与模板选择逻辑。
- `gameplay/services/buildings/forge.py`：开始拆分配置归一化逻辑。
- `gameplay/services/arena/core.py`：开始拆分纯 helper 与报名快照逻辑。

## 阶段 2：热点模块重构

- 拆分 `guests/services/recruitment.py`：缓存、抽卡、候选人构建、落库、通知分层。
- 拆分 `gameplay/services/buildings/forge.py`：配方加载、分解、锻造、蓝图、排程分层。
- 拆分 `gameplay/services/arena/core.py`：报名、快照、匹配、结算、奖励分层。
- 收缩 `gameplay/services/__init__.py` 聚合出口，新增代码只允许从子模块导入。

## 阶段 3：类型与边界治理

- 逐步缩小 `pyproject.toml` 中 mypy 的 `ignore_errors` 范围。
- 优先覆盖 selector、service、utility 层，再逐步推进到 views。
- 约束新模块必须带类型标注，避免继续产生新的类型盲区。

## 阶段 4：性能与数据一致性

- 为关键页面增加查询次数基线测试，重点覆盖任务、仓库、交易、竞技场。
- 统一高频缓存 key、TTL 和失效策略，减少隐式缓存分叉。
- 继续梳理 Celery 任务的“吞异常但兜底扫描”模式，补 metrics/告警。

## 阶段 5：测试与发布质量

- 将超大测试文件按业务域拆分，例如 `tests/test_views.py`。
- 增加并发行为回归用例，覆盖锁、库存、撤退、报名等关键路径。
- 为 YAML 配置加载继续补 schema 化校验与负例测试。

## 阶段 6：迁移与运维治理

- 评估 `gameplay`、`guests` 的历史 migration，择机进行 squash。
- 增加结构化日志、关键任务监控和失败告警。
- 完善运行手册，形成开发 / 测试 / 上线统一流程。
