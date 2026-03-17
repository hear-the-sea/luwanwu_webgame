# 春秋乱世庄园主 - 开发环境搭建指南

本文档详细介绍如何在本地搭建开发环境，以及开发过程中的常用命令和最佳实践。

---

## 环境要求

| 软件 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.12+ | 推荐 3.12（与 CI/Docker 保持一致） |
| MySQL | 8.0+ | 或 SQLite（开发） |
| Redis | 7.0+ | Celery + Channels 必需 |
| Node.js | 18+ | 前端资源编译（可选） |

---

## 快速开始

### 0. （推荐）Docker Compose 一键启动

```bash
cp .env.docker.example .env.docker
docker compose up --build
```

### 0.1 生产部署（Docker Compose）

```bash
cp .env.docker.prod.example .env.docker
docker compose -f docker-compose.prod.yml up -d --build
```

生产部署前请至少确认：

- 设置强随机 `DJANGO_SECRET_KEY`
- 设置 `MYSQL_PASSWORD` 与 `MYSQL_ROOT_PASSWORD`
- 正确配置 `DJANGO_ALLOWED_HOSTS` 与 `DJANGO_CSRF_TRUSTED_ORIGINS`；默认示例域名为 `luanwu.top`
- 若通过反向代理/负载均衡终止 TLS，设置 `DJANGO_USE_PROXY=1`、`DJANGO_TRUSTED_PROXY_IPS`、`DJANGO_ACCESS_LOG_TRUST_PROXY=1`
- 若没有前置 HTTPS 终止层，不要直接对外暴露当前 `docker-compose.prod.yml` 并保留 `DJANGO_SECURE_SSL_REDIRECT=1`；请先补齐 `443` 入口或在前面接入 HTTPS 代理
- `health/ready` 默认会检查 DB、cache、channel layer、Celery broker；如果你的编排不希望 `web` readiness 依赖后两项，可配置 `DJANGO_HEALTH_CHECK_CHANNEL_LAYER=0` 或 `DJANGO_HEALTH_CHECK_CELERY_BROKER=0`

常用容器内命令：

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py bootstrap_game_data --skip-images
docker compose exec web python manage.py load_item_templates
docker compose exec web python manage.py load_mission_templates
docker compose exec web python manage.py load_guest_templates
```

### 1. 克隆项目

```bash
git clone <repository-url>
cd web_game_v5
```

### 2. 创建虚拟环境

```bash
# 创建虚拟环境
python3 -m venv .venv

# 激活虚拟环境
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt

# 或使用 Makefile
make install
```

为了保证环境可复现（尤其是线上/CI），建议使用锁定依赖安装：

```bash
make install-lock

# 如果已生成开发锁文件，也可安装完整开发环境
make install-dev-lock
```

更新锁文件：

```bash
make lock

# 生成包含开发依赖的锁文件
make lock-dev
```

建议安装 `pre-commit` 钩子，避免提交前才发现格式/静态检查问题：

```bash
make precommit
```

---

## 质量门禁（推荐）

本项目默认启用 CI 质量门禁（GitHub Actions）：

- `flake8`：基础代码风格检查（仓库内固定 `jobs=1`，保证在受限环境也可运行）
- `pytest + coverage`：默认单元测试道与覆盖率报告（不包含 `integration` marker）
- `python manage.py check --deploy`：部署安全检查

本地建议按以下顺序执行：

```bash
make format
make lint
make cov
```

覆盖率阈值会在 CI 中强制执行（见 `.github/workflows/ci.yml`）。

---

## 开发调试工具

### 战斗调试器（battle_debugger）

`battle_debugger` 仅在开发环境可用，并且需要显式启用：

```bash
export DJANGO_ENABLE_DEBUGGER=1
```

默认关闭可以避免在开发/测试环境中意外加载额外路由与调试页面。

### 4. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件，至少修改以下配置：
# - DJANGO_SECRET_KEY（生成新的密钥）
# - DJANGO_DEBUG=1（开发模式）
# - 数据库配置（如使用 MySQL）
```

生成 SECRET_KEY：

```bash
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

### 5. 初始化数据库

```bash
# 运行迁移
python manage.py migrate

# 或使用 Makefile
make migrate
```

### 6. 加载初始数据

```bash
# 加载道具模板
python manage.py load_item_templates

# 加载任务模板
python manage.py load_mission_templates

# 加载门客模板
python manage.py load_guest_templates
```

### 7. 创建管理员账号

```bash
python manage.py createsuperuser
```

### 8. 启动服务

需要同时启动多个服务（建议使用多个终端窗口）：

**终端 1 - Django 开发服务器：**
```bash
python manage.py runserver 0.0.0.0:8000

# 或使用 Makefile
make dev
```

**终端 2 - Celery Worker：**
```bash
celery -A config worker -l INFO

# 或使用 Makefile
make worker
```

**终端 3 - Celery Beat（可选，定时任务）：**
```bash
celery -A config beat -l INFO

# 或使用 Makefile
make beat
```

### 9. 访问应用

- **主页**：http://localhost:8000/
- **管理后台**：http://localhost:8000/admin/

---

## 环境配置详解

### .env 文件配置

#### 核心配置

```ini
# Django 密钥（必须修改）
DJANGO_SECRET_KEY=your-secret-key-here

# 调试模式（开发环境设为 1）
DJANGO_DEBUG=1

# 允许的主机
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
```

#### 数据库配置

**开发环境（SQLite）：**
```ini
# 使用默认 SQLite，无需额外配置
# 数据库文件：db.sqlite3
```

**开发环境（MySQL）：**
```ini
DJANGO_DB_ENGINE=django.db.backends.mysql
DJANGO_DB_NAME=webgame_dev
DJANGO_DB_USER=root
DJANGO_DB_PASSWORD=your-password
DJANGO_DB_HOST=127.0.0.1
DJANGO_DB_PORT=3306
```

#### Redis 配置

```ini
REDIS_URL=redis://127.0.0.1:6379
REDIS_BROKER_URL=redis://127.0.0.1:6379/0
REDIS_CHANNEL_URL=redis://127.0.0.1:6379/1
REDIS_CACHE_URL=redis://127.0.0.1:6379/2
```

---

## 开发命令

### Makefile 命令

| 命令 | 说明 |
|------|------|
| `make install` | 安装 Python 依赖 |
| `make install-dev-lock` | 安装锁定的开发依赖 |
| `make migrate` | 运行数据库迁移 |
| `make dev` | 启动开发服务器 |
| `make worker` | 启动 Celery Worker |
| `make beat` | 启动 Celery Beat |
| `make test` | 运行默认单元测试道（排除 `integration`） |
| `make test-unit` | 同 `make test`，显式运行单元测试道 |
| `make test-integration` | 运行依赖外部 MySQL/Redis/Celery/Channels 的集成测试 |
| `make format` | 格式化代码（black + isort） |
| `make lock` | 生成运行时锁文件 |
| `make lock-dev` | 生成开发依赖锁文件 |
| `make lint` | 代码检查（flake8 + mypy） |
| `make check` | 格式化 + 检查 |

### Django 管理命令

```bash
# 创建新迁移
python manage.py makemigrations

# 运行迁移
python manage.py migrate

# 创建超级用户
python manage.py createsuperuser

# 启动 Django Shell
python manage.py shell

# 收集静态文件（生产部署）
python manage.py collectstatic

# 查看所有可用命令
python manage.py help
```

### 数据加载命令

```bash
# 加载道具模板
python manage.py load_item_templates

# 加载任务模板
python manage.py load_mission_templates

# 加载门客模板
python manage.py load_guest_templates
```

---

## IDE 配置

### VSCode 推荐配置

**.vscode/settings.json：**
```json
{
    "python.defaultInterpreterPath": "./venv/bin/python",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.flake8Enabled": true,
    "editor.formatOnSave": true,
    "[python]": {
        "editor.defaultFormatter": "ms-python.black-formatter"
    }
}
```

**推荐扩展：**
- Python (ms-python.python)
- Pylance (ms-python.vscode-pylance)
- Black Formatter (ms-python.black-formatter)
- Django (batisteo.vscode-django)

### PyCharm 配置

1. 设置 Python 解释器为虚拟环境
2. 启用 Django 支持：Settings → Languages & Frameworks → Django
3. 配置 Black 作为代码格式化工具
4. 启用 flake8 作为代码检查工具

---

## 测试

### 运行测试

```bash
# 默认单元测试道（排除 integration）
python -m pytest -m "not integration"

# 或使用 Makefile 封装
make test
make test-unit

# 运行依赖外部 MySQL/Redis/Celery/Channels 的集成测试
DJANGO_TEST_USE_ENV_SERVICES=1 python -m pytest -m integration
make test-integration

# 运行特定模块测试
python -m pytest tests/test_gameplay.py

# 显示详细输出
python -m pytest -v

# 显示测试覆盖率
python -m pytest --cov=.
```

### 测试文件位置

```
tests/
├── __init__.py
├── test_accounts.py    # 账户模块测试
├── test_core_views.py  # 拆分后的核心视图测试
├── test_message_views.py  # 拆分后的消息视图测试
├── test_integration_external_services.py  # 外部服务集成测试
└── ...
```

### 测试层级说明

> **重要**：本仓库正式区分两套测试道。`make test` 通过，只能说明业务逻辑在 hermetic 替身环境上基本正确；**不能**据此推断真实 MySQL / Redis / broker / Channels 语义已经验证。

| 层级 | 命令 | 依赖 | 能证明什么 | 不能证明什么 |
|------|------|------|------------|--------------|
| Hermetic 套件 | `make test` / `make test-unit` | SQLite + `LocMem` cache + in-memory broker/channel layer | 业务逻辑、状态机、计算规则、同步降级分支在本地替身环境下基本正确 | 真实数据库锁与事务语义、Redis 共享锁/去重语义、真实 Celery broker dispatch/retry/fallback、Channels 经 Redis 的跨进程广播/聊天链路 |
| Infra-backed 集成测试 | `DJANGO_TEST_USE_ENV_SERVICES=1 make test-integration` | MySQL + Redis + 真实 Celery broker / Channels transport | 真实依赖交互、一致性边界、跨进程并发、外部基础设施降级与恢复路径 | 性能/容量上限仍需额外压测或 profile 测试 |

`make test-critical` 是一个便捷目标，不是单独的验收层级；它只是在启用外部服务时补跑若干并发敏感用例，不能替代完整的 `make test-integration` 门禁。

**Hermetic 套件主要回答的问题：**

- 业务逻辑是否基本正确，核心服务/模型/视图在 SQLite + 本地内存替身下是否按预期运行
- 基本状态机、数值计算、权限/校验、同步 fallback 分支是否按预期执行

**Hermetic 套件不能回答的问题：**

- `select_for_update()`、事务等待、死锁/锁顺序等真实数据库语义是否成立
- Redis 共享缓存锁、去重键、原子 `add` / `delete` / `incr` 是否符合跨进程预期
- Celery dispatch、retry、broker 不可用时的 scanner fallback / 降级路径是否在真实 broker 下成立
- Django Channels 是否能通过 Redis channel layer 把聊天/广播消息正确送到真实消费者

**Infra-backed 集成测试重点覆盖的真实风险：**

- MySQL 行锁、唯一约束、事务隔离级别、`select_for_update()` 冲突与等待
- Redis 共享锁、dedup、计数器和 TTL 在多进程下的真实行为
- Celery 在真实 broker 上的投递、重试、去重回滚、scanner fallback 和 dispatch 降级
- Django Channels / WebSocket 通过 Redis 的聊天链路、group fan-out 和多消费者广播

### 高风险改动的强制 infra-backed 验证

以下任一条件命中时，提交前**必须**运行 `DJANGO_TEST_USE_ENV_SERVICES=1 make test-integration`，并确保对应集成测试通过。仅 `make test` 绿灯不构成合并依据：

- 改动涉及 `select_for_update()`、显式数据库锁或任何依赖真实锁等待/事务语义的路径
- 改动涉及共享缓存锁、`cache_lock`、dedup key、`cache.add()` / `cache.delete()` / `cache.incr()` 等 Redis 语义
- 改动涉及 Celery dispatch、retry、任务扫描器（scanner）fallback、broker 不可用降级或 `safe_apply_async(_with_dedup)` 相关行为
- 改动涉及 Django Channels、channel layer、Redis 聊天链路、WebSocket 广播或多消费者 fan-out

**典型高风险路径示例：**

| 模块 / 路径 | 风险类型 | 为什么必须跑 infra-backed |
|-------------|----------|---------------------------|
| `core/utils/cache_lock.py` | Redis 共享锁 | `locmem` 只提供单进程锁，无法证明跨进程互斥 |
| `gameplay/services/arena/` | 数据库锁 / 并发状态机 | arena 推进依赖 `select_for_update()` 行锁，SQLite 下该语义是 no-op |
| `gameplay/models/arena.py` | MySQL 约束 | MySQL 约束与事务细节在 SQLite 下不能等价验证 |
| `common/utils/celery.py` | Celery dispatch / retry / fallback | 真实 broker 的投递、失败、重试与回滚语义无法由 in-memory broker 代表 |
| `websocket/consumers/world_chat.py` | Channels / Redis 聊天链路 | 单进程 channel layer 无法证明真实 Redis fan-out 与消费者广播路径 |
| `websocket/backends/` | Redis 聊天后端 | 聊天历史、限流、ID 分配等 Redis 语义必须在真实 Redis 下验证 |

**本地运行 infra-backed 集成测试：**

```bash
# 需要先启动 MySQL 和 Redis（推荐 Docker Compose）
DJANGO_TEST_USE_ENV_SERVICES=1 make test-integration
```

### 测试数据库

- 默认测试道会自动使用内存 SQLite、`locmem` cache、in-memory channel layer 和 memory Celery backend，无需额外配置。
- `integration` 测试要求设置 `DJANGO_TEST_USE_ENV_SERVICES=1`，并连接外部 MySQL/Redis/Celery/Channels。
- 当前仓库没有独立的 profile/performance 测试道；性能/容量回归仍需额外补充。

---

## 代码规范

### 格式化工具

项目使用以下工具保持代码一致性：

| 工具 | 用途 | 配置文件 |
|------|------|----------|
| black | Python 代码格式化 | pyproject.toml |
| isort | import 排序 | pyproject.toml |
| flake8 | 代码风格检查 | .flake8 |
| mypy | 类型检查 | pyproject.toml |

### 运行检查

```bash
# 一键格式化和检查
make check

# 分步执行
make format  # 格式化代码
make lint    # 代码检查
```

### 代码风格要求

1. **行长度**：最大 100 字符
2. **缩进**：4 空格
3. **命名**：
   - 类名：PascalCase
   - 函数/变量：snake_case
   - 常量：UPPER_CASE
4. **文档字符串**：Google 风格
5. **类型注解**：推荐使用

---

## 调试技巧

### Django Debug Toolbar

开发环境已集成 Django Debug Toolbar，显示 SQL 查询、请求信息等。

### 日志配置

```python
# 在代码中使用
import logging
logger = logging.getLogger(__name__)

logger.debug("调试信息")
logger.info("一般信息")
logger.warning("警告信息")
logger.error("错误信息")
```

### Celery 调试

```bash
# 以调试模式启动 Worker
celery -A config worker -l DEBUG

# 查看任务状态
celery -A config inspect active
celery -A config inspect reserved
celery -A config inspect scheduled
```

### Redis 调试

```bash
# 连接 Redis CLI
redis-cli

# 查看所有键
KEYS *

# 查看 Celery 队列长度
LLEN celery

# 清空所有数据（谨慎！）
FLUSHALL
```

---

## 常见问题

### 1. MySQL 连接错误

**错误：** `django.db.utils.OperationalError: (2002, ...)`

**解决：**
- 确认 MySQL 服务已启动
- 检查 `.env` 中的数据库配置
- 确认数据库用户权限

### 2. Redis 连接错误

**错误：** `redis.exceptions.ConnectionError`

**解决：**
- 确认 Redis 服务已启动：`redis-cli ping`
- 检查 Redis URL 配置

### 3. Celery Worker 不执行任务

**可能原因：**
- Worker 未启动或连接错误
- 任务队列配置不匹配

**解决：**
```bash
# 检查 Worker 状态
celery -A config inspect active

# 确认 Broker 连接
celery -A config inspect ping
```

### 4. 静态文件 404

**解决：**
```bash
# 开发环境：确保 DEBUG=1
# 生产环境：
python manage.py collectstatic
```

### 5. 迁移冲突

**错误：** `django.db.migrations.exceptions.InconsistentMigrationHistory`

**解决：**
```bash
# 查看迁移状态
python manage.py showmigrations

# 伪执行迁移（谨慎）
python manage.py migrate --fake <app> <migration>
```

---

## 多服务启动脚本

为方便同时启动多个服务，可创建启动脚本：

**start_dev.sh（Linux/macOS）：**
```bash
#!/bin/bash

# 启动 Redis（如未运行）
redis-server &

# 启动 Django
python manage.py runserver 0.0.0.0:8000 &

# 启动 Celery Worker
celery -A config worker -l INFO &

# 启动 Celery Beat
celery -A config beat -l INFO &

echo "All services started!"
wait
```

**使用 tmux 管理多窗口：**
```bash
# 创建会话
tmux new-session -d -s webgame

# 窗口 0: Django
tmux send-keys -t webgame:0 'make dev' C-m

# 窗口 1: Celery Worker
tmux new-window -t webgame
tmux send-keys -t webgame:1 'make worker' C-m

# 窗口 2: Celery Beat
tmux new-window -t webgame
tmux send-keys -t webgame:2 'make beat' C-m

# 连接会话
tmux attach -t webgame
```

---

---

## 异步任务调度约束

### safe_apply_async 语义

`safe_apply_async` 和 `safe_apply_async_with_dedup`（位于 `common/utils/celery.py`）采用 **best-effort** 语义：

- **dispatch 成功**：返回 `True`，任务已进入 broker 队列
- **dispatch 失败**（broker 不可用等基础设施问题）：返回 `False`，同时记录 `celery_dispatch_failed` 降级计数，**不抛异常**
- **`raise_on_failure=True`**：仅在调用方明确要求强制保证时使用，此时 dispatch 失败会重新抛出原始异常

**调用方职责**：检查返回值，根据业务场景决定失败时的处理方式。

### 两类使用场景

| 场景 | dispatch 失败时 | 补偿机制 |
|------|-----------------|----------|
| 允许降级（如通知、消息推送、刷新缓存） | 静默跳过，仅记录降级计数 | 无需补偿，下次请求自然触发 |
| 必须执行（如状态机推进、资源扣减） | **必须同步降级执行** | 调用方负责提供降级路径 |

对于"必须执行"场景，推荐模式：

```python
dispatched = safe_apply_async(my_task, args=[...], logger=logger)
if not dispatched:
    # broker 不可用，同步降级执行
    my_task_logic(...)
```

### safe_apply_async_with_dedup 的去重语义

`safe_apply_async_with_dedup` 在 dispatch 前通过 `cache.add(dedup_key, ...)` 设置去重锁：

- 去重锁获取成功且 dispatch 成功：返回 `True`，锁保留到 `dedup_timeout` 超时
- 去重锁获取失败（key 已存在）：表示窗口内已有相同任务 dispatch，**直接返回 `True`**（幂等跳过）
- 去重锁获取成功但 dispatch 失败：**自动回滚去重锁**（`cache.delete`），避免窗口内后续重试被误判为重复

### 降级计数观测

当 `dispatch 失败` 时，`celery_dispatch_failed` 降级计数器会自动递增（通过 `core.utils.task_monitoring.increment_degraded_counter`）。

```bash
# 查询今日 Celery dispatch 失败次数（需要 Redis 可用）
python manage.py shell -c "
from core.utils.task_monitoring import get_degraded_counter
print(get_degraded_counter('celery_dispatch_failed'))
"
```

> **注意**：该计数器存储在 Redis cache 中。若 Redis 本身不可用，计数器读取也会失败——这种情况下应直接检查 broker 连通性（`celery -A config inspect ping`）。

---

## 下一步

- 阅读 [API 文档](api.md) 了解接口详情
- 阅读 [架构文档](architecture.md) 了解系统设计
- 阅读 [数据库文档](database.md) 了解数据模型
