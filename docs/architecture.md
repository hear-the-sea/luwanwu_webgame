# 春秋乱世庄园主 - 系统架构文档

> 最近校正：2026-03-18（与当前仓库结构和门禁流程对齐）

## 概述

本文档描述了"春秋乱世庄园主"游戏的系统架构设计，包括整体架构、模块划分、数据流和关键设计决策。

---

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| Web 框架 | Django 5.x | 后端核心框架 |
| REST API | Django REST Framework | API 层（预留） |
| 异步通信 | Django Channels | WebSocket 支持 |
| 任务队列 | Celery 5.x | 后台任务处理 |
| 消息代理 | Redis 7.x | Celery Broker + Channel Layer |
| 缓存 | Redis (django-redis) | 会话、缓存、在线状态 |
| 数据库 | MySQL 8.x / SQLite | 主数据存储 |
| 前端渲染 | Django Templates | 服务端渲染为主 |
| 前端样式 | Tailwind CSS + 自定义 CSS | `src/input.css` 构建到 `static/css/tailwind.css`，并配合 `static/css/style.css` |
| 前端脚本 | 原生 JavaScript | 页面脚本位于 `static/js/*.js` |

---

## 系统架构图

```
                                    ┌─────────────────────┐
                                    │     Nginx/CDN       │
                                    │  (静态资源/反向代理)  │
                                    └──────────┬──────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    │                          │                          │
                    ▼                          ▼                          ▼
           ┌───────────────┐          ┌───────────────┐          ┌───────────────┐
           │   Gunicorn    │          │    Daphne     │          │  Celery Beat  │
           │  (HTTP/WSGI)  │          │ (WebSocket)   │          │  (定时任务)    │
           └───────┬───────┘          └───────┬───────┘          └───────┬───────┘
                   │                          │                          │
                   └──────────────────────────┼──────────────────────────┘
                                              │
                                              ▼
                                    ┌─────────────────────┐
                                    │   Django App        │
                                    │   ┌─────────────┐   │
                                    │   │   Views     │   │
                                    │   └──────┬──────┘   │
                                    │          │          │
                                    │   ┌──────▼──────┐   │
                                    │   │  Services   │   │
                                    │   └──────┬──────┘   │
                                    │          │          │
                                    │   ┌──────▼──────┐   │
                                    │   │   Models    │   │
                                    │   └─────────────┘   │
                                    └──────────┬──────────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    │                          │                          │
                    ▼                          ▼                          ▼
           ┌───────────────┐          ┌───────────────┐          ┌───────────────┐
           │    MySQL      │          │     Redis     │          │ Celery Worker │
           │   (数据存储)   │          │  (缓存/消息)   │          │  (后台任务)    │
           └───────────────┘          └───────────────┘          └───────────────┘
```

---

## 应用模块

项目采用 Django App 模块化架构，每个 App 负责独立的业务领域：

```
web_game_v5/
├── config/             # 项目配置
│   ├── settings/       # 分模块 settings（base/security/database/testing/...）
│   ├── urls.py         # 主路由
│   ├── celery.py       # Celery 配置
│   ├── asgi.py         # ASGI 配置（WebSocket）
│   └── wsgi.py         # WSGI 配置
│
├── accounts/           # 账户模块
│   ├── models/         # User 模型（继承 AbstractUser）
│   ├── views/          # 登录/注册/资料
│   └── services/       # 登录运行时、单点登录
│
├── gameplay/           # 核心玩法模块
│   ├── models/         # Manor, Building, Item, Mission...
│   ├── views/          # 仪表盘、任务、仓库、消息...
│   ├── selectors/      # 读侧页面上下文装配
│   ├── services/       # 业务逻辑层
│   └── tasks/          # Celery 任务
│
├── guests/             # 门客模块
│   ├── models/         # Guest, Skill, Gear...
│   ├── views/          # 门客列表、详情、装备
│   ├── services/       # 招募、培养、装备、工资
│   └── tasks.py        # 培养完成任务
│
├── battle/             # 战斗模块
│   ├── models/         # BattleReport、TroopTemplate 等基础模型
│   ├── services/       # 战斗模拟入口
│   ├── simulation_core/  # 战斗引擎核心
│   └── tasks/          # 战报生成任务
│
├── trade/              # 交易模块
│   ├── models/         # MarketListing、ShopStock
│   ├── views/          # 商店/银庄/交易行
│   └── services/       # 商店、银庄、交易行服务
│
├── guilds/             # 帮会模块
│   ├── models/         # Guild、GuildMember、Technology...
│   ├── views/          # 帮会管理全流程
│   └── services/       # 帮会、成员、贡献、科技、仓库
│
├── websocket/          # WebSocket 模块
│   ├── consumers/      # NotificationConsumer、OnlineStatsConsumer 等
│   └── routing.py      # WebSocket 路由
│
├── battle_debugger/    # 战斗调试工具（开发用）
│
├── core/               # 共享工具
│   ├── utils/          # 通用工具函数
│   └── exceptions.py   # 自定义异常
│
├── data/               # YAML 数据配置
│   ├── item_templates.yaml
│   ├── troop_templates.yaml
│   ├── mission_templates.yaml
│   ├── guest_templates.yaml
│   └── guest_skills.yaml
│
├── src/                # 前端样式源码（Tailwind 输入）
├── templates/          # Django 模板
├── static/             # 静态资源
└── media/              # 用户上传文件
```

### 模块职责

| 模块 | 职责 | URL 前缀 |
|------|------|----------|
| accounts | 用户认证、资料管理、单点登录 | `/accounts/` |
| gameplay | 庄园资源、建筑、任务、消息、科技、打工 | `/manor/` |
| guests | 门客招募、培养、装备、技能、工资 | `/guests/` |
| battle | 战斗模拟、战报生成与查看 | `/battle/` |
| trade | 商店、银庄、交易行 | `/trade/` |
| guilds | 帮会创建/管理/科技/捐赠/仓库 | `/guilds/` |
| websocket | 实时通知、在线统计 | `ws://` |
| battle_debugger | 战斗调试器（仅开发环境） | `/debugger/` |

---

## 分层架构

项目采用三层架构模式，确保关注点分离：

```
┌─────────────────────────────────────────────────────┐
│                   View Layer                        │
│  (HTTP 请求处理、表单验证、模板渲染、权限检查)         │
└─────────────────────────────┬───────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────┐
│                  Service Layer                      │
│  (业务逻辑、事务管理、跨模块协调、验证规则)            │
└─────────────────────────────┬───────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────┐
│                   Model Layer                       │
│  (数据定义、ORM 查询、数据完整性约束)                  │
└─────────────────────────────────────────────────────┘
```

### View Layer（视图层）

- **职责**：处理 HTTP 请求，进行基础验证，调用 Service 层
- **位置**：`{app}/views/`（可包含多个子模块或 `__init__.py` 聚合）
- **原则**：
  - 不包含业务逻辑
  - 负责权限检查（`@login_required`）
  - 处理表单数据提取和响应格式化
  - 统一错误处理（Django Messages）

### Service Layer（服务层）

- **职责**：封装业务逻辑，管理事务，协调跨模块操作
- **位置**：`{app}/services/` 或 `{app}/services.py`
- **原则**：
  - 所有业务逻辑必须在此层实现
  - 优先抛出显式领域异常；`ValueError` 仅保留给历史兼容入口，不再作为默认跨层契约
  - 使用 `@transaction.atomic` 管理事务
  - 避免直接操作 HTTP 请求/响应

### Model Layer（模型层）

- **职责**：定义数据结构，提供 ORM 查询接口
- **位置**：`{app}/models/`（每个模型模块可按领域拆分）
- **原则**：
  - 包含字段定义和约束
  - 提供 `property` 计算属性
  - 使用 `Manager` 封装常用查询
  - 避免在 Model 中实现业务逻辑

---

## 异步任务架构

### Celery 配置

项目使用 Celery 处理耗时和定时任务，配置了三个专用队列：

```python
# config/settings/celery_conf.py
CELERY_TASK_QUEUES = (
    Queue("default"),   # 默认队列
    Queue("battle"),    # 战斗相关
    Queue("timer"),     # 定时器相关
)

CELERY_TASK_ROUTES = {
    "battle.generate_report": {"queue": "battle"},
    "gameplay.complete_mission": {"queue": "timer"},
    "gameplay.complete_building_upgrade": {"queue": "timer"},
    "guests.complete_training": {"queue": "timer"},
    # ...
}
```

### 队列职责

| 队列 | 用途 | Worker 配置建议 |
|------|------|-----------------|
| default | 通用任务 | 2-4 并发 |
| battle | 战报生成（CPU 密集） | 1-2 并发，独立 Worker |
| timer | 定时完成类任务 | 2-4 并发 |

### 定时任务（Celery Beat）

```python
CELERY_BEAT_SCHEDULE = {
    "scan-building-upgrades": {
        "task": "gameplay.scan_building_upgrades",
        "schedule": crontab(minute="*/10"),  # 每 10 分钟
    },
    "scan-guest-training": {
        "task": "guests.scan_training",
        "schedule": crontab(minute="*/10"),
    },
    "complete-work-assignments": {
        "task": "gameplay.complete_work_assignments",
        "schedule": crontab(minute="*/1"),   # 每分钟
    },
    "refresh-shop-stock": {
        "task": "trade.refresh_shop_stock",
        "schedule": crontab(hour=0, minute=0),  # 每天 00:00
    },
    # 帮会定时任务...
}
```

### 任务设计原则

1. **幂等性**：任务可重复执行，结果一致
2. **自动重试**：配置 `max_retries` 和 `default_retry_delay`
3. **超时控制**：设置 `soft_time_limit` 和 `time_limit`
4. **错误处理**：记录详细日志，必要时发送通知
5. **扫描兜底**：定时扫描任务防止 Worker 宕机导致任务丢失

---

## WebSocket 架构

### 连接处理

```python
# websocket/consumers/notification.py 等

class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """用户通知推送"""
    # 每个用户加入独立 group: user_{id}
    # 支持消息类型：resource_update, battle_complete, message_new

class OnlineStatsConsumer(AsyncJsonWebsocketConsumer):
    """在线统计广播"""
    # 所有用户加入同一 group: online_stats
    # 使用 Redis SET 跟踪在线用户
    # 带 TTL 自动清理（30 分钟）
```

### 消息推送流程

```
                服务端事件（如战斗完成）
                          │
                          ▼
              ┌───────────────────────┐
              │   Service Layer       │
              │   channel_layer.      │
              │   group_send(...)     │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Redis Channel Layer │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  NotificationConsumer │
              │  send_json(payload)   │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   WebSocket Client    │
              │   (浏览器 JavaScript) │
              └───────────────────────┘
```

---

## 战斗系统架构

### 核心组件

```
battle/
├── models/             # BattleReport、TroopTemplate 等基础模型
├── services/           # simulate_report() 等外部接口
├── simulation_core/    # BattleSimulator 类 - 核心引擎
├── troops/             # 兵种数据加载相关
└── tasks/              # generate_report_task
```

### 战斗模拟流程

```
                    launch_mission()
                          │
                          ▼
              ┌───────────────────────┐
              │  创建 MissionRun      │
              │  设置状态为 ACTIVE    │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  调度 Celery Task     │
              │  generate_report_task │
              │  countdown=行军时间   │
              └───────────┬───────────┘
                          │
                          ▼ (延迟执行)
              ┌───────────────────────┐
              │  BattleSimulator      │
              │  ├── 初始化双方       │
              │  ├── 回合循环         │
              │  │   ├── 技能结算     │
              │  │   ├── 伤害计算     │
              │  │   └── 状态更新     │
              │  └── 生成战报         │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │  finalize_mission_run │
              │  ├── 奖励结算         │
              │  ├── 门客状态更新     │
              │  └── 发送通知         │
              └───────────────────────┘
```

### 五行相克系统

战斗系统实现了五行相克机制：

```
        金 ──克──▶ 木
        ▲           │
        │           克
        克          │
        │           ▼
        水 ◀──克── 火
        ▲           │
        │           克
        克          │
        │           ▼
        木 ◀──克── 土 ◀──克── 金
```

- 相克关系：造成额外 20% 伤害
- 被克关系：受到额外 20% 伤害

### 并发控制

战斗系统使用数据库行级锁防止并发问题：

```python
# 使用 select_for_update 锁定门客
guests = list(
    Guest.objects.select_for_update()
    .filter(id__in=guest_ids)
)
```

---

## 数据配置系统

游戏数据通过 YAML 文件配置，便于策划调整：

```
data/
├── item_templates.yaml      # 道具定义
├── troop_templates.yaml     # 兵种定义
├── mission_templates.yaml   # 任务定义
├── guest_templates.yaml     # 门客模板
├── guest_skills.yaml        # 门客技能
├── technology_templates.yaml # 科技定义
└── work_templates.yaml      # 打工定义
```

### 加载机制

```python
# 示例：加载兵种模板
def load_troop_templates():
    path = settings.BASE_DIR / "data" / "troop_templates.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

### 数据同步

通过 Django Management Command 将 YAML 同步到数据库：

```bash
python manage.py load_item_templates
python manage.py load_mission_templates
python manage.py load_guest_templates
```

---

## 测试门禁分层（当前执行口径）

项目当前采用两条测试道并行治理：

1. `Hermetic rapid gate`：快速反馈，默认命令为 `make test` / `make test-unit`（`pytest -m "not integration"`）。
2. `Real external-service gate`：真实语义验证，命令为 `DJANGO_TEST_USE_ENV_SERVICES=1 make test-real-services`（包含 `make test-critical` + `make test-integration`）。

关键说明：

- 默认测试道使用 SQLite、LocMem cache、InMemory channel layer、memory Celery，不覆盖真实外部服务语义。
- `integration` 用例通过 `pytest.mark.integration` 区分，且依赖 `DJANGO_TEST_USE_ENV_SERVICES=1` 与可达的外部 DB/Redis/Channels/Celery。
- `make test-critical` 作为高风险快速回归，固定补跑 `raid / scout / mission / guest recruitment / work service` 的真实并发敏感套件。
- 固定串行验收可使用 `DJANGO_TEST_USE_ENV_SERVICES=1 make test-gates`（先 hermetic，再 real external services）。

---

## 前端资源边界（源码 vs 构建产物）

- 样式源码：`src/input.css`（Tailwind 输入文件）。
- 样式构建产物：`static/css/tailwind.css`（由 `npm run build:css` / `npm run build:css:prod` 生成）。
- 手写全局样式：`static/css/style.css`（非生成文件）。
- 页面脚本：`static/js/*.js`（手写脚本，不经打包器聚合）。

这条边界用于避免“把生成文件当源码改”与“把手写样式误写进构建输入”两类维护风险。

---

## 缓存策略

### Redis 用途划分

```python
REDIS_URL = "redis://127.0.0.1:6379"
REDIS_BROKER_URL = f"{REDIS_URL}/0"    # Celery Broker
REDIS_CHANNEL_URL = f"{REDIS_URL}/1"   # Django Channels
REDIS_CACHE_URL = f"{REDIS_URL}/2"     # Django Cache
```

### 缓存场景

| 场景 | 缓存键 | TTL | 说明 |
|------|--------|-----|------|
| 在线用户数 | `stats:online_users_count` | 5s | 高频读取 |
| 总用户数 | `stats:total_users_count` | 5min | 数据库 COUNT 缓存 |
| 未读消息数 | `manor:{id}:unread_count` | - | 写时失效 |
| 会话数据 | Django Session | - | 用户登录状态 |

---

## 安全架构

### 认证机制

- Session-based 认证（Django 默认）
- 单点登录：新登录自动登出其他设备
- CSRF 保护：所有 POST 请求需 Token

### 安全配置

```python
# Session 安全
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# CSRF 安全
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True

# HTTPS 强制
SECURE_SSL_REDIRECT = True  # 生产环境
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# 内容安全
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
```

### 速率限制

```python
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        "recruit": "20/hour",
        "battle": "100/hour",
        "claim": "50/hour",
    },
}
```

---

## 部署架构

### 开发环境

```bash
# 单进程模式
python manage.py runserver 0.0.0.0:8000

# Celery Worker
celery -A config worker -l INFO

# Celery Beat
celery -A config beat -l INFO
```

### 生产环境

```
                    ┌─────────────┐
                    │   Nginx     │
                    │  (SSL/静态) │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ Gunicorn │    │  Daphne  │    │ Celery   │
    │ (HTTP)   │    │ (WS)     │    │ Worker   │
    │ 4 workers│    │ 2 workers│    │ 3 queues │
    └──────────┘    └──────────┘    └──────────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │  MySQL   │    │  Redis   │    │ Celery   │
    │ (主库)   │    │ (缓存)   │    │ Beat     │
    └──────────┘    └──────────┘    └──────────┘
```

### 推荐配置

| 组件 | 配置 | 说明 |
|------|------|------|
| Gunicorn | 4 workers, gevent | HTTP 请求处理 |
| Daphne | 2 workers | WebSocket 连接 |
| Celery Worker | 3 进程，按队列分配 | 后台任务 |
| MySQL | 连接池 300 | CONN_MAX_AGE |
| Redis | maxmemory 1GB | 缓存 + 消息 |

---

## 扩展指南

### 添加新功能模块

1. 创建 Django App：`python manage.py startapp {name}`
2. 注册到 `INSTALLED_APPS`
3. 创建 `services/` 目录结构
4. 添加 URL 路由
5. 创建模板和静态资源
6. 编写测试

### 添加新的 Celery 任务

```python
# {app}/tasks.py
from celery import shared_task

@shared_task(name="{app}.{task_name}", bind=True, max_retries=2)
def my_task(self, arg1, arg2):
    try:
        # 业务逻辑
        pass
    except Exception as exc:
        raise self.retry(exc=exc)
```

### 添加新的 WebSocket Consumer

```python
# websocket/consumers/<feature>.py
class MyConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # 认证检查
        # 加入 group
        # 接受连接
        pass

# websocket/routing.py
websocket_urlpatterns = [
    path("ws/my-feature/", MyConsumer.as_asgi()),
]
```

---

## 附录：关键设计决策

### 为什么使用 Service Layer？

1. **可测试性**：业务逻辑与 HTTP 解耦，易于单元测试
2. **复用性**：同一逻辑可被 View、Task、Management Command 调用
3. **事务边界**：在 Service 层统一管理事务
4. **清晰职责**：避免"胖 View"或"胖 Model"

### 为什么使用多个 Celery 队列？

1. **优先级控制**：战斗任务优先于日常任务
2. **资源隔离**：CPU 密集任务不阻塞 I/O 密集任务
3. **弹性扩展**：可针对性扩展特定队列的 Worker

### 为什么使用 YAML 配置数据？

1. **策划友好**：非技术人员可直接修改
2. **版本控制**：数据变更可追溯
3. **热更新**：无需代码部署即可调整平衡性
