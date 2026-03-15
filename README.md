# 春秋乱世庄园主 · 概要设计

## 技术文档

详细技术文档请查阅 [`docs/`](docs/index.md) 目录：

| 文档 | 说明 |
|------|------|
| [文档索引](docs/index.md) | 技术文档总览与快速导航 |
| [架构设计](docs/architecture.md) | 系统架构、模块划分、数据流 |
| [开发指南](docs/development.md) | 环境搭建、命令行工具、调试 |
| [API 接口](docs/api.md) | HTTP/WebSocket 接口规范 |
| [数据库设计](docs/database.md) | 数据模型、表结构、索引 |

---

## 一、游戏定位与基础设定
- **题材**：穿越春秋战国，玩家化身庄园主，联合横跨古今的门客在乱世建立霸业。
- **核心循环**：建设庄园 → 招募/培养门客 → 获得士兵与资源 → 进攻或任务 → 获得战报与奖励 → 再投资庄园建设。
- **坐标体系**：每位玩家创建时分配 `region + (X, Y)` 庄园坐标，用于地图检索与侦察/踢馆定位（当前为二维坐标，无 `Z`）。
- **门客分类**：稀有度黑→灰→绿→红→蓝→紫→橙；分文、武两系，影响成长权重与战斗表现。

## 二、核心系统概览
### 1. 小喇叭（规划）
- 消耗“喇叭道具”在全服顶部滚动消息，带冷却与日志，便于玩家之间发布消息。

### 当前已落地的主要功能（2025-12）
- **账号体系**：注册/登录/资料（`/accounts/`），基于 Session。
- **庄园与资源**：`/` 指挥中心概览；`/manor/` 建筑升级、资源产出与仓储（粮仓/银库/藏宝阁）、科技、护院招募与生产加工（畜牧场/冶炼坊/马房/铁匠铺）。
- **任务与战斗**：`MissionTemplate` / `MissionRun`（`data/mission_templates.yaml`，`load_mission_templates` 导入），战斗推演生成战报（`/battle/report/<id>/`）。
- **门客系统**：招募/培养/技能/装备/发薪（`/guests/`，模板 `data/guest_templates.yaml`，技能 `data/guest_skills.yaml`，`load_guest_templates` 导入）。
- **社交与经济**：帮会（`/guilds/`）、交易（`/trade/`）、打工（`/manor/work/`）、地图侦察/踢馆（`/manor/map/`）。
- **异步与实时**：Celery + Redis 处理倒计时/结算，Channels + Redis 推送通知；订阅 `/ws/notifications/` 与 `/ws/online-stats/`。
- **数据驱动配置**：YAML 模板 `data/*.yaml`（物品/任务/兵种/商铺/建筑/科技等）；其中门客/物品/任务/兵种支持 `load_*_templates` 导入。
- **页面入口**：主页 `/` 概览与导航；庄园 `/manor/`、门客 `/guests/`、帮会 `/guilds/`、交易 `/trade/` 等。

### 2. 战斗系统
- 出征时根据双方坐标距离、军情与门客速度生成倒计时；完成后发送图文战报。
- 战斗采用回合制：展示我方门客头像/兵力在左、敌方在右，底部逐回合汇总伤害/伤亡。
- 每回合出手顺序会根据参战单位敏捷动态排序（门客敏捷会叠加智力折算速度；护院敏捷来自兵种 `speed_bonus`），战报中展示完整的行动序列，便于复盘。
- 出征前可自定义携带的兵种与数量（由 `data/troop_templates.yaml` 配置模板与 `priority`）；`priority < 0` 的单位会在“先攻阶段”提前出手（如弓系默认 `-1`，科技「凤舞九天」可使弓系额外提前到 `-2`），其余单位首轮显示“冲锋中”。
- 战报结构可套用模板，支持存档与分享。

### 3. 门客招募
- 多档招募（童试/乡试/会试/殿试），每档消耗不同资源并对应概率表。
- 高级招募拥有更高稀有度概率；卡池与模板定义集中在 `data/guest_templates.yaml`。

### 4. 门客培养
- 通过训练（计时）、装备、技能书等提升门客能力。
- 文/武门客在战斗中采用不同的攻击力公式（见 `guests/models.py` 的 `stat_block()`），成长时的随机加点权重也不同（见 `guests/utils/attribute_growth.py`）。

#### 门客属性与成长（当前实现）
- **属性字段**：武力/智力/防御/敏捷/运势/忠诚度等，模板与初始值由 `data/guest_templates.yaml` 定义。
- **升级（训练）**：等级上限 100；训练消耗与耗时由 `guests/utils/training_calculator.py` 计算并写入 `training_complete_at`，完成后自动结算（Celery `timer` 队列 + beat 扫描兜底）。
- **成长机制**：
  - 每级会获得一定的“随机属性成长点”（按稀有度区间随机，并按文/武权重分配，见 `guests/utils/attribute_growth.py`）。
  - 每级额外获得 `attribute_points`（当前所有稀有度为每级 +1），可由玩家手动分配。
- **血量计算**：`max_hp = template.base_hp + hp_bonus + defense_stat * 50`（设置了最小血量下限），结算时可恢复满血（见 `guests/models.py`）。

### 5. 建筑升级
- 建筑影响士兵上限、门客容量、资源产出速率、科技解锁等。
- 需考虑排队/加速、互斥升级、每日限制等机制。

### 6. 任务系统
- 包含日常、主线、出征任务；任务完成触发资源、装备或门客碎片奖励。
- 出征任务复用战斗流程，以时间驱动完成。

### 7. 斗技场（规划）
- 定时开启匹配，通过多轮对决决出排名，生成战报并根据名次发奖。
- 支持观战/复盘接口，为后续赛事化扩展预留。

### 8. 帮会
- 帮会科技提供全体被动加成；帮贡可兑换帮会独有装备。
- 支持帮会建设与任务，后续可扩展帮会战、跨服联赛。

### 9. 交易与商铺（已落地）
- `/trade/` 提供商铺买卖、银行兑换与交易行挂单/购买/撤单等功能。
- 商铺商品由 `data/shop_items.yaml` 配置，配套 Celery 定时刷新库存并处理过期挂单。

### 10. 打工与地图（已落地）
- `/manor/work/` 门客打工：派遣/撤回/领奖，结算由 Celery 定时扫描兜底。
- `/manor/map/` 地图：周边庄园搜索、侦察与踢馆（Raid）流程，提供对应 API 与倒计时结算。

## 三、经济与资源设计
- **核心资源**：粮食（`grain`）与银两（`silver`），对应 `Manor.grain` / `Manor.silver`，并受 `grain_capacity` / `silver_capacity` 限制。
- **道具/材料**：装备材料、技能书、产出物等以道具（`InventoryItem`）形式存于仓库/藏宝阁，可用于锻造、培养、交易与帮会兑换等。
- 资源来源：建筑产出、任务、战斗掠夺、斗技场、活动礼包。
- 资源消耗：建筑升级、招募、培养、科技、装备打造。
- 需设上线与回收点控制通胀，如限时活动、维护性费用。

## 四、后端架构建议
| 模块 | 说明 |
| --- | --- |
| API Gateway / Django + DRF/Channels | 统一入口，负责认证、速率限制与路由；DRF 提供 RESTful 接口，Channels 支撑 WebSocket。 |
| Gameplay Service | 庄园、建筑、门客、任务等主逻辑。 |
| Battle Service | 战斗推演、战报生成，可按需独立以便水平扩展。 |
| Scheduler & Worker | 处理出征/任务/斗技场/帮会研究倒计时，发放奖励。 |
| Notification Service | 推送小喇叭、系统邮件、战报通知。 |

- **数据存储**：MySQL 持久化核心数据（玩家、门客、战斗记录、建筑）；Redis 用于缓存热数据、计时器、排行榜、门客唯一性锁。
- **异步/队列**：Celery 驱动定时任务与战斗结算；Redis 充当 Broker。
- **战报渲染**：模板引擎（如 Jinja2）生成 JSON/HTML，再由前端绘制或直接导出图片。
- **实时性**：WebSocket/Socket.IO 用于战斗倒计时、喇叭广播、斗技场进度推送。

## 五、推荐技术栈（尽量简化）
- **语言**：Python 3.12+
- **Web 框架**：Django 5 + Django REST Framework（接口）+ Django Channels（WebSocket/实时推送）
- **ORM/数据层**：Django ORM + 内置迁移（可结合 Django Admin 维护配置）
- **任务队列**：Celery + Redis（Broker/Cache）
- **数据库**：MySQL 8.x（主存储）、Redis 7.x（缓存/排行榜/分布式锁）
- **鉴权**：Django Auth + Session（当前实现：DRF `SessionAuthentication`）
- **测试**：Pytest + pytest-django
- **监控**：Prometheus + Grafana（或轻量日志 + APM 方案）
- **部署**：Docker Compose（API、Worker、DB、Cache 容器化）

> 选择 Django + DRF 的原因：框架成熟度高，有完善的权限系统与后台管理便于配置门客/建筑/概率表；依托 Channels 可以在同一技术栈下提供 WebSocket/长连接能力；生态中有丰富的插件（国际化、表单、后台工具）可支撑持续运营。

### 进程/队列拆分预留
- 进程角色：`Web`（Django/DRF + Channels，HTTP + WebSocket）、`Worker`（Celery，战斗/计时任务可按队列拆分）、`Beat`（Celery 定时调度）。保持同仓但独立进程/容器即可平滑放大。
- 队列隔离：已在 settings 预设 Celery 队列 `default` / `battle` / `timer`，对应 `.env` 中的 `CELERY_DEFAULT_QUEUE`、`CELERY_BATTLE_QUEUE`、`CELERY_TIMER_QUEUE`，可用 `-Q` 独立起不同 worker。
- Redis 分层：预留 `REDIS_CHANNEL_URL`（Channels）、`REDIS_BROKER_URL`/`REDIS_RESULT_URL`（Celery）、`REDIS_CACHE_URL`（缓存/锁），默认同实例不同 DB，压测后可直接改指向独立实例。

## 六、数据模型要点（示例）
- `accounts.User`：用户账号。
- `gameplay.Manor`：庄园基础信息、坐标（region/x/y）、资源（grain/silver）、保护状态与声望。
- `gameplay.BuildingType` / `gameplay.Building`：建筑模板与实例（产出/升级）。
- `guests.GuestTemplate` / `guests.Guest`：门客模板与实例（属性、训练、状态、技能/装备）。
- `gameplay.MissionTemplate` / `gameplay.MissionRun`、`battle.BattleReport`：任务出征与战报。
- `gameplay.RaidRun` / `gameplay.ScoutRecord`：踢馆与侦察记录；其余交易/帮会分别在 `trade/*`、`guilds/*`。

## 七、开发阶段规划
1. **阶段0：立项与预研（~2周）**
   - 输出：数值原型、低保真交互、服务划分与数据流设计、技术栈 PoC（Django + Channels + Celery 可跑通）。
   - 验收：核心玩法文档冻结、接口规范与数据模型初稿、CI/CD 雏形可跑基础测试。
2. **阶段1：基础架构 & 账号体系（~3周）**
   - 任务：完成 Django/DRF 项目骨架、配置管理、日志/监控埋点；实现注册登录、Session/权限、后台配置；打通数据库迁移、缓存、队列部署。
   - 验收：可创建账号、登录后台、调用基础健康检查与示例 API，CI 自动跑单元测试。
3. **阶段2：庄园循环最小可玩（~4周）**
   - 任务：实现建筑/资源产出、升级排队、加速与上限控制；补齐任务系统（日常/主线）；提供图形化监测资源流。
   - 验收：玩家可完成“建造→产出→任务领奖→再投资”闭环，覆盖 70% 核心 KPI（留存/资源平衡）所需埋点。
4. **阶段3：门客与战斗基线（~4周）**
   - 任务：实现门客招募概率表、培养/装备；完成战斗推演引擎、战报模板、倒计时调度与内测 AI，对接 Channels 推送。
   - 验收：可执行 PVE 战斗并收到完整战报；战斗数据可追踪（计算时间、胜率、损耗）。
5. **阶段4：实时社交 & 竞技（~3周）**
   - 任务：上线小喇叭、站内信、通知中心；实现斗技场匹配、排名、奖励发放；提供排行榜/回放接口。
   - 验收：服务器可承载并发推送（目标 5k socket），竞技赛季奖励自动结算且可灰度。
6. **阶段5：帮会与高级运营（~3周+）**
   - 任务：帮会创建/审核、帮贡与科技、帮会仓库/兑换；交易行/商铺与经济系统；运营后台可配置活动与稀有门客。
   - 验收：帮会功能覆盖基础治理、全服公告、活动投放；具备热修/灰度机制。
7. **阶段6：长线拓展 &优化（持续迭代）**
   - 任务：跨服/赛季、剧情副本、门客缘分、用户增长活动；性能调优（缓存分片、异步批处理），A/B Testing。
   - 验收：每次迭代都有明确 KPI（留存、付费、LTV），并通过监控仪表盘验证。

## 阶段2落地 · 庄园循环
- **资源产出**：`Manor` + `Building` + `ResourceEvent` 驱动粮食（`grain`）/银两（`silver`）的自动产出与流水记录，按建筑等级计算每小时速率并受 `grain_capacity` / `silver_capacity` 约束（茅厕额外等量产银）。
- **建筑升级**：建筑模板由迁移 seed 到 `BuildingType`（当前按资源生产/仓储设施/生产加工/人员管理/特殊建筑分类，如农田/税务司/澡堂/茅厕、粮仓/银库/藏宝阁、畜牧场/冶炼坊/马房/铁匠铺、聚贤庄/家丁房/练功场/酒馆、祠堂/悠嘻宝塔）；支持排队升级、按成长系数扣资源并记录升级倒计时；升级完成由 Celery `timer` 队列延时任务结算，beat 每 10 分钟兜底扫描，完成后会写系统消息并推送 WebSocket 通知。
- **聚贤庄**：新增 `聚贤庄` 建筑负责门客招募容量管理，可在建筑面板跳转至招募大厅并通过升级提升可招募上限。
- **任务系统**：已切换为 `MissionTemplate` / `MissionRun` 出征任务，支持自定义敌人、掉落、耗时与每日次数（用 `load_mission_templates` 从 `data/mission_templates.yaml` 导入）。
- **可视化面板**：登录后访问 `/` 可查看资源/事件与收支概览；访问 `/manor/` 可按分类查看建筑并升级，部分建筑提供快捷入口（招募/生产/冶炼/锻造/护院招募等）。
- **数据初始化**：迁移会 seed 建筑模版并为已有账号生成庄园 + 建筑实例；门客/物品/任务/兵种等数据建议通过 `load_*_templates`/`seed_*` 命令导入；新增账号通过 `post_save` 信号自动完成庄园初始化。

> 体验流程：`python manage.py migrate` →（可选）按“快速开始”导入模板数据 → 注册/登录 → 访问 `/` 查看资源/事件 → 访问 `/manor/` 升级建筑 → 访问 `/manor/tasks/` 接取任务并领奖。

## 阶段3落地 · 门客与战斗
- **门客招募与培养**：`guests` 模块负责门客模板/实例、招募候选、训练/属性点、技能与装备等；招募大厅位于 `/manor/recruitment/`（聚贤庄），门客列表与培养入口在 `/guests/`。
- **门客培养规则更新**：门客等级上限 100，培养需等待修行时间（黑色门客 1→2 需约 120 秒，随等级与稀有度略增），修行完成后自动加点与满血，Celery `timer` 队列/beat 兜底。
- **装备系统**：提供武器/饰品模板与实例，支持在 UI 中给门客穿戴，自动结算属性加成并记录到战斗力。
- **战斗推演**：`battle` 模块提供回合制推演，默认自动选择最多 `MAX_SQUAD=5` 名空闲门客参战；任务/踢馆等玩法可按 `Manor.max_squad_size` 扩展上阵人数；主推演最多 `MAX_ROUNDS=32` 回合（另含 `priority < 0` 的先攻阶段），生成结构化战报（`BattleReport`）与战斗日志。
- **战报查看**：战报可在 `/battle/report/<id>/` 页面查看阵容、回合事件与胜负。
- **招募规则升级**：银两成为招募主货币，通过任务奖励与“税务司”建筑产出；童试/乡试/会试/殿试四档卡池一次生成 1/5/8/10 名候选，玩家仅能看到姓名与文/武倾向，稀有度需在候选招募后揭晓。黑色门客会随机生成姓名并套用文/武模板，黑色以上稀有度绑定历史/小说人物；所有模板与卡池定义集中在 `data/guest_templates.yaml`，可通过 `python manage.py load_guest_templates` 热更新。
- **技能系统**：门客模型内置技能表（`Skill/SkillBook`），模板可指定默认技能；运势属性会影响技能触发概率，详情页可查看已学技能并通过技能书扩充。
- **门客属性面板**：门客详情展示武力/智力/防御/敏捷、性别、品性（1-100）、运势、忠诚度等核心属性，可在详情页培养、换装或辞退；`guest_templates.yaml` 同步提供默认性别与品性初值，命令导入时自动写入。
- **测试与校验**：新增 `tests/test_guests.py`、`tests/test_battle.py`，覆盖招募/培养与战报生成流程，`pytest` 可全量校验阶段2/阶段3基线。

## 阶段4落地 · 社交与经济
- **打工系统**：`WorkTemplate` / `WorkAssignment` 驱动门客派遣、撤回与领奖，`gameplay.complete_work_assignments` 定时结算兜底。
- **交易系统**：`trade` 模块提供商铺买卖、银行兑换、交易行挂单/购买/撤单；任务 `trade.refresh_shop_stock` / `trade.process_expired_listings` 负责定时刷新与过期处理。
- **帮会系统**：`guilds` 模块支持创建/申请/成员管理、贡献排行、科技升级、仓库兑换与公告；提供每日产出/周统计/日志清理等定时任务。
- **地图玩法**：`/manor/map/` 支持周边搜索、侦察与踢馆（Raid）流程，提供对应 API 与倒计时结算任务。
- **在线与通知**：WebSocket 新增 `/ws/online-stats/`，配合 `/ws/notifications/` 提供实时数据与消息推送。

## 八、扩展与维护建议
- 保持模块化：战斗公式、门客表、概率配置均使用数据驱动（JSON/YAML + 管理后台），方便数值运营调优。
- 预留监控指标：资源流入流出、战斗失败率、喇叭使用量、队列耗时等。
- 版本迭代策略：先在小规模测试环境验证数值与并发，再灰度上线。
- 数据安全：Redis 定期持久化；MySQL 做主从或备份；敏感字段加密。

## 九、后续可拓展玩法
- **跨服战/赛季制**：分赛季重置部分进度，增加长线目标。
- **门客缘分系统**：组合出战触发特效，增加收集深度。
- **剧情副本 & 探险**：结合春秋名场景，丰富PVE内容。
- **自定义战报分享**：导出图像或动态，增强社交传播。

> 本 README 旨在作为首版设计蓝本，后续可根据测试反馈细化数值、接口与UML文档。

## 十、项目结构（基础框架）
```
web_game_v5/
├── accounts/                 # 账号体系（注册/登录/资料）
├── battle/                   # 战斗推演、战报渲染、兵种模板
├── battle_debugger/          # 开发调试工具（仅 DEBUG 下启用路由）
├── config/                   # Django 项目配置（settings/urls/asgi/wsgi/celery）
├── core/                     # 通用中间件/工具（request_id、health、rate_limit 等）
├── data/                     # YAML 数据模板（任务/门客/物品/兵种/商铺/建筑/科技）
├── docker/                   # 容器脚本与 Nginx 配置
├── docs/                     # 当前技术文档与少量保留的专题说明
├── gameplay/                 # 庄园/建筑/任务/仓库/地图/打工等
├── guests/                   # 门客（招募/培养/技能/装备/薪资）
├── guilds/                   # 帮会（成员/科技/仓库/公告）
├── media/                    # 上传/生成的媒体文件（本地/容器卷）
├── scripts/                  # 辅助脚本（分析/图片等）
├── static/                   # Web 端静态资源
├── tasks/                    # Celery 任务聚合（部分 app 内也有 tasks.py）
├── templates/                # Django Templates（页面/战报等）
├── tests/                    # pytest-django 与集成测试
├── trade/                    # 商铺/银行/交易行
├── websocket/                # Channels consumers/routing（通知、在线状态等）
├── manage.py
├── docker-compose.yml        # API、Worker、MySQL、Redis、Channels 等编排
├── docker-compose.prod.yml   # 生产编排（Daphne + Nginx）
├── Dockerfile
├── Makefile                  # 常用命令封装
├── pyproject.toml
├── requirements.txt
├── pytest.ini
├── .env.example              # 环境变量模板
├── .env.docker.example       # Docker Compose 环境变量模板
└── .env.docker.prod.example  # 生产 Docker Compose 环境变量模板
```

## 十一、快速开始（本地）
1. `cp .env.example .env` 并根据实际数据库/Redis 凭据调整。
   - Redis 拆分已预留：`REDIS_URL`（默认基址）、`REDIS_CHANNEL_URL`（Channels）、`REDIS_BROKER_URL`/`REDIS_RESULT_URL`（Celery）、`REDIS_CACHE_URL`（缓存/锁），默认指向同一实例不同 DB，后续按需改为独立实例即可。
   - （可选）`GAME_TIME_MULTIPLIER` 可用于加速/减速所有计时类行为（升级/出征/生产/训练等），开发调试默认建议为 `1`。
2. （可选）创建虚拟环境并执行 `make install`（开发依赖；存在 `requirements-dev.lock.txt` 时优先使用开发锁文件）或 `pip install -r requirements.txt`（运行时依赖）。
3. 初始化数据库：`python manage.py migrate`（可选 `python manage.py createsuperuser` 便于调试后台）。
4. 同步模板数据：
   - 门客/卡池/技能：`python manage.py load_guest_templates --file data/guest_templates.yaml`（默认加载 `data/guest_skills.yaml`）
   - 任务：`python manage.py load_mission_templates --file data/mission_templates.yaml`
   - 物品：`python manage.py load_item_templates --file data/item_templates.yaml`
   - 兵种：`python manage.py load_troop_templates --file data/troop_templates.yaml`
   - 打工模板：`python manage.py seed_work_templates`
5. 启动服务（需先启动 Redis）：
   - Web（开发）：`make dev`（或 ASGI：`python -m daphne config.asgi:application --port 8000`）
   - Celery Worker（默认队列）：`celery -A config worker -l info -Q ${CELERY_DEFAULT_QUEUE:-default}`
   - Celery Worker（战斗队列）：`celery -A config worker -l info -Q ${CELERY_BATTLE_QUEUE:-battle}`
   - Celery Worker（计时/任务队列）：`celery -A config worker -l info -Q ${CELERY_TIMER_QUEUE:-timer}`（建筑升级、门客自动升级、返程等依赖）
   - Celery Beat（兜底/调度）：`make beat`（或 `celery -A config beat -l info`）
6. 运行测试：
   - 单元/默认测试道：`pytest -m "not integration"`（或 `make test` / `make test-unit`）
   - 外部服务集成测试道：`DJANGO_TEST_USE_ENV_SERVICES=1 pytest -m integration`（或 `make test-integration`）
   - 默认测试道会自动切到内存 SQLite/locmem/in-memory channel layer；`integration` 测试才会验证外部 MySQL/Redis/Celery/Channels 依赖。
   - 当前仓库还没有独立的 profile/performance 测试道。
7. Docker 一键拉起全栈依赖（API/Worker/MySQL/Redis/Channels）：
   - `cp .env.docker.example .env.docker`
   - `docker compose up --build`

### 生产部署（Docker Compose）

1. 准备生产环境变量：
   - `cp .env.docker.prod.example .env.docker`
   - 默认示例域名已设置为 `luanwu.top`；如果还要支持 `www.luanwu.top`，请同步补到 `DJANGO_ALLOWED_HOSTS` 和 `DJANGO_CSRF_TRUSTED_ORIGINS`
   - 必改项：`DJANGO_SECRET_KEY`、`MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD`、`REDIS_PASSWORD`（建议）等
   - 若由 CDN / 反向代理 / 负载均衡终止 TLS，请配置：`DJANGO_USE_PROXY=1`、`DJANGO_TRUSTED_PROXY_IPS`、`DJANGO_ACCESS_LOG_TRUST_PROXY=1`
   - 若没有前置 HTTPS 终止层，不要直接使用 `DJANGO_SECURE_SSL_REDIRECT=1` 对外暴露当前 compose；请先补齐 `443` 入口或在前面接入 HTTPS 反向代理
2. 启动（含 Nginx 反代、静态文件、WebSocket）：
   - `docker compose -f docker-compose.prod.yml up -d --build`
3. 首次上线常用操作：
   - 迁移：`docker compose -f docker-compose.prod.yml exec web python manage.py migrate --noinput`
   - 管理员：`docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser`
   - 若本次发布包含 `data/*.yaml` 中的导入型模板改动，请执行：`docker compose -f docker-compose.prod.yml exec web python manage.py bootstrap_game_data --skip-images`
   - 若只需同步物品模板，可执行：`docker compose -f docker-compose.prod.yml exec web python manage.py load_item_templates --file data/item_templates.yaml`
   - 健康检查：`/health/live`、`/health/ready`
   - `/health/ready` 默认会检查 DB、cache、channel layer、Celery broker；如果你的编排不希望 `web` readiness 绑定后两项，可在环境变量里调整 `DJANGO_HEALTH_CHECK_CHANNEL_LAYER=0` 或 `DJANGO_HEALTH_CHECK_CELERY_BROKER=0`

## 十二、后续迭代提示
- 结合游戏玩法补充更多 Django App/DRF Router（庄园、建筑、门客等），在 `config/urls.py` 中按领域挂载。
- 异步任务建议按领域放在各 App 的 `tasks.py` 中，并在 `config/settings/celery_conf.py` 的 `CELERY_TASK_ROUTES` / `CELERY_BEAT_SCHEDULE` 配置队列与调度。
- 数值/概率优先走 `data/*.yaml`，导入型数据用 `python manage.py load_*_templates` 同步（门客/物品/任务/兵种等）。
- 日志与健康检查：访问 `/health/live`、`/health/ready`；日志格式在 `config/settings/logging_conf.py` 的 `LOGGING` 配置。
