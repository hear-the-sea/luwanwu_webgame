# 第二阶段统一写模型基线

本文档用于为第二阶段的并发治理与真实语义测试提供统一基线，适用于 `mission`、`raid / scout`、`guest recruitment` 三条高频写链路。

本文件不是“未来愿景”，而是基于当前仓库实现抽出的执行约束。后续第二阶段的代码改动、测试补强和文档更新，都必须以这里的职责划分为前提。

相关代码：

- `gameplay/views/mission_action_handlers.py`
- `gameplay/services/missions_impl/*`
- `gameplay/services/raid/scout.py`
- `gameplay/services/raid/scout_start.py`
- `gameplay/services/raid/scout_finalize.py`
- `gameplay/services/raid/scout_refresh.py`
- `gameplay/services/raid/scout_return.py`
- `gameplay/services/raid/combat/*`
- `guests/views/recruit_action_runtime.py`
- `guests/views/recruit_responses.py`
- `guests/services/recruitment.py`
- `guests/services/recruitment_flow.py`
- `guests/services/recruitment_guests.py`

---

## 1. 统一规则

### 1.1 写链路必须分四层

1. **view / action handler**
   - 负责请求解析、轻量输入校验、请求级去重锁、异常到 HTTP / message / JSON 的映射
   - 不负责决定数据库锁顺序、状态推进细节或补偿策略
2. **write command**
   - 唯一允许持有事务和行锁的主入口
   - 负责二次校验、状态推进、资源扣减、创建/更新运行记录
3. **after-commit follow-up**
   - 只负责在 durable write 成功后派发任务、消息、缓存失效
   - 失败时只能记录日志，不得反向改写事务内状态
4. **refresh / finalize command**
   - 只负责对“已到期但未完成”的运行记录做补偿收口
   - 只能在显式命令、任务或调度链路中运行，不得再挂回页面读路径

### 1.2 锁的职责必须固定

- **请求级锁**：仅用于防止用户重复点击和并发提交，不承担正确性保证。
- **数据库事务 / 行锁**：唯一的业务正确性来源。
- **缓存锁 / dedup key**：只用于抑制任务重复派发或缓存击穿，不得代替数据库状态机。

### 1.3 状态推进必须由 write command 负责

- view 不能直接推进状态。
- read helper / selector / page context 不能继续承担“顺手修状态”的职责。
- after-commit follow-up 只能消费已提交状态，不能成为状态机主入口。

### 1.4 补偿的边界必须显式

- 调度失败后，允许记录“待完成”的 durable 状态，再由 refresh / finalize command 收口。
- refresh command 只允许扫“明确到期且主状态可判定”的记录。
- 补偿不能继续放在页面渲染或读路径入口里偷偷触发。

---

## 2. 任务系统（mission）

### 2.1 当前主写入口

- 发起任务：`gameplay.services.missions.launch_mission()`
- 撤退请求：`gameplay.services.missions.request_retreat()`
- 完成结算：`gameplay.services.missions.finalize_mission_run()`
- 补偿刷新：`gameplay.services.missions.refresh_mission_runs()`

### 2.2 当前职责分配

- `gameplay/views/mission_action_handlers.py`
  - 负责请求解析、请求级 action lock、错误映射
- `gameplay/services/missions_impl/launch_command.py`
  - 负责事务内二次校验、门客/护院锁定、`MissionRun` 创建、门客状态推进
- `gameplay/services/missions_impl/finalize_command.py`
  - 负责事务内结算、门客 HP / 状态恢复、护院返还、奖励发放、消息落地
- `gameplay/services/missions_impl/mission_followups.py`
  - 负责 launch 后报告准备、完成任务导入与 completion dispatch、refresh dispatch gate
- `gameplay/services/missions_impl/execution.py`
  - 负责公共入口接线与 finalize / refresh command 适配

### 2.3 第二阶段口径

- `launch_mission()` 视为唯一发起写入口。
- `request_retreat()` 视为唯一撤退写入口。
- `finalize_mission_run()` 视为唯一终态收口入口。
- `refresh_mission_runs()` 只能做“到期 run 的补偿触发”，不能继续扩散到页面读路径。

---

## 3. 踢馆 / 侦察系统（raid / scout）

### 3.1 当前主写入口

- 发起踢馆：`gameplay.services.raid.start_raid()`
- 请求撤退：`gameplay.services.raid.request_raid_retreat()`
- 踢馆结算：`gameplay.services.raid.finalize_raid()` / `process_raid_battle()`
- 侦察发起：`gameplay.services.raid.start_scout()`
- 侦察撤退：`gameplay.services.raid.request_scout_retreat()`
- 侦察收口：`gameplay.services.raid.finalize_scout()` / `finalize_scout_return()`
- 补偿刷新：`gameplay.services.raid.refresh_raid_runs()`、`gameplay.services.raid.refresh_scout_records()`

### 3.2 当前职责分配

- `gameplay/views/map.py`、`gameplay/views/mission_action_handlers.py`
  - 负责请求级锁、输入解析、异常映射
- `gameplay/services/raid/combat/start.py`
  - 负责踢馆事务内的双庄园加锁、门客/护院扣减、`RaidRun` 创建
- `gameplay/services/raid/combat/finalize.py`
  - 负责返程完成后的门客与护院恢复、战利品发放、状态落终态
- `gameplay/services/raid/scout.py`
  - 负责侦察公开入口、消息 follow-up 与共享适配
- `gameplay/services/raid/scout_start.py`
  - 负责侦察发起写命令、双庄园加锁、探子扣减、after-commit completion dispatch 注册
- `gameplay/services/raid/scout_finalize.py`
  - 负责侦察到达判定、冷却落库、返程切换、after-commit detected / return dispatch 注册
- `gameplay/services/raid/scout_refresh.py`
  - 负责到期记录扫描、refresh task 派发、同步 fallback 收口
- `gameplay/services/raid/scout_return.py`
  - 负责撤退请求、返程完成的事务与状态收口

### 3.3 第二阶段口径

- 双庄园锁顺序、门客锁、护院锁必须继续由 write command 统一持有。
- 侦察链路要继续按“发起 / 结果写入 / 撤退 / 返程完成 / refresh 补偿”拆成稳定动作边界；当前 `scout_start.py` / `scout_finalize.py` 已承接主写命令，`scout.py` 不再继续兼任总调度器。
- `refresh_raid_runs()` 与侦察 refresh 只能补偿 durable state，不得继续追加新的业务判断分支。

---

## 4. 门客招募系统（guest recruitment）

### 4.1 当前主写入口

- 发起招募：`guests.services.recruitment.start_guest_recruitment()`
- 完成招募：`guests.services.recruitment.finalize_guest_recruitment()`
- 使用放大镜：`guests.services.recruitment.use_magnifying_glass_for_candidates()`
- 确认候选：`guests.services.recruitment_guests.bulk_finalize_candidates()`
- 候选保留/辞退：`guests.services.recruitment_guests.*`
- 补偿刷新：`guests.services.recruitment.refresh_guest_recruitments()`

### 4.2 当前职责分配

- `guests/views/recruit.py`、`guests/views/recruit_action_runtime.py`
  - 负责请求解析、请求级 lock、响应映射
- `guests/services/recruitment.py`
  - 负责事务内发起招募、创建 `GuestRecruitment(PENDING)`、显现候选稀有度、完成招募
- `guests/services/recruitment_flow.py`
  - 负责主写链路共享校验、成本扣减、`PENDING/COMPLETED/FAILED` 状态落库
- `guests/services/recruitment_candidates.py`
  - 负责候选批量构造与落库；候选持久化必须直接返回本次 durable rows，不得再用“按庄园最近 N 条回查”这类启发式补丁回填主键
- `guests/services/recruitment_followups.py`
  - 负责 after-commit completion dispatch、完成通知发送
- `guests/services/recruitment_guests.py`
  - 负责候选转正式门客时的事务与行锁

### 4.3 第二阶段口径

- `start_guest_recruitment()` 是唯一允许创建 `PENDING` 招募的入口。
- `finalize_guest_recruitment()` 是唯一允许把 `PENDING -> COMPLETED / FAILED` 的入口。
- 候选批量生成的返回值必须与本次写入结果一一对应；如果数据库后端不支持 `bulk_create` 回填主键，应退回稳定的逐条插入语义，而不是依赖“最近写入记录”猜测。
- 候选确认、保留、放弃必须与 `GuestRecruitment` 状态机分离，作为独立写命令看待。
- `refresh_guest_recruitments()` 只补偿已到期仍为 `PENDING` 的招募，不再承担页面读路径修复职责。

---

## 5. 第二阶段开工清单

### 5.1 先做的代码治理

1. 为 `mission / raid / guest recruitment` 三条链路明确“主写入口 -> after-commit follow-up -> refresh command”目录边界。
2. 继续把 `raid/scout` 中混在同一文件里的动作拆成稳定 command，而不是继续增加 runtime/bundle 壳。
3. 禁止新增从 view 直接调用补偿刷新命令的路径。

### 5.2 先补的测试门禁

1. 真 MySQL 下的 `select_for_update` 并发测试：
   - `mission` 发起 / 撤退
   - `raid` 发起 / 返程
   - `guest recruitment` 完成 / 候选确认
2. 真 Redis 下的任务派发与 dedup 测试：
   - completion dispatch 失败后的 refresh 补偿
   - 请求级锁冲突与数据库事务正确性隔离
3. 契约测试：
   - view 锁只做去重，不做正确性保证
   - refresh command 只收口到期 durable state

### 5.3 开工前禁止事项

- 不得在页面读路径继续补偿 mission / raid / recruitment 状态。
- 不得把新的 cache lock 或 runtime marker 直接塞进 view 层。
- 不得在未补真实服务测试前，把局部 fail-open 改写成 production fail-closed。
