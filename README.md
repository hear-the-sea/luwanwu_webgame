# 春秋乱世庄园主

> 最近校正：2026-03-20
>
> 本 README 只保留当前仓库能验证的工程事实。更细的架构、接口和数据设计请看 [`docs/`](docs/index.md)。

## 项目简介

这是一个以春秋战国为题材的 Django 游戏项目。当前仓库已经包含账号、庄园建设、门客、战斗、交易、帮会、地图、通知等核心模块，并采用数据驱动配置管理大部分玩法模板。

当前前端形态不是 SPA，也不是 Bootstrap 站点，而是：

- Django Templates
- Tailwind CSS 构建产物
- 手写 CSS / JavaScript

## 当前实现范围

- 账号体系：注册、登录、Session 鉴权
- 庄园系统：建筑升级、资源产出、仓储、科技、生产加工
- 门客系统：招募、培养、技能、装备、薪资
- 战斗系统：回合制推演、战报生成与展示
- 交易系统：商铺、银行兑换、交易行、拍卖相关逻辑
- 帮会系统：成员管理、科技、仓库、公告
- 地图玩法：搜索、侦察、踢馆
- 异步与实时：Celery + Redis、Channels + WebSocket
- 数据驱动配置：`data/*.yaml`

## 技术栈

- Python / Django 5
- Django REST framework
- Channels / Daphne
- Celery
- Redis
- MySQL（真实服务环境）
- Tailwind CSS

默认开发与 hermetic 测试场景可以退回 SQLite / LocMem / InMemory channel layer；真实并发与 Redis 语义验证仍以外部服务环境为准。

## 快速开始

### 1. 安装依赖

```bash
make install
npm install
```

### 2. 准备环境变量

```bash
cp .env.example .env
```

按需补充数据库、Redis、密钥等配置。相关示例文件：

- `.env.example`
- `.env.docker.example`
- `.env.docker.prod.example`

### 3. 初始化数据

```bash
python manage.py migrate
python manage.py bootstrap_game_data --skip-images
npm run build:css
```

### 4. 启动服务

只需要 HTTP 页面时：

```bash
make dev
```

需要 WebSocket 时：

```bash
make dev-ws
make worker
make beat
```

## 测试与质量门禁

默认快速门禁：

```bash
make test
```

等价于：

```bash
python -m pytest -m "not integration"
```

真实服务门禁：

```bash
DJANGO_TEST_USE_ENV_SERVICES=1 make test-real-services
```

固定串行验收：

```bash
DJANGO_TEST_USE_ENV_SERVICES=1 make test-gates
```

静态检查：

```bash
make lint
```

## 前端资源边界

- 样式源码：`src/input.css`
- 样式产物：`static/css/tailwind.css`
- 手写样式：`static/css/*.css`
- 手写脚本：`static/js/*.js`

仓库当前没有前端 bundler 聚合业务脚本；Tailwind 仅用于样式构建。

## 目录概览

```text
accounts/    账号体系
battle/      战斗推演与战报
config/      Django / Celery / settings
core/        通用中间件与基础工具
data/        YAML 配置与部分静态资源
docs/        技术文档
gameplay/    庄园、建筑、任务、地图、仓库等主玩法
guests/      门客相关逻辑
guilds/      帮会相关逻辑
trade/       商铺、银行、交易行、拍卖
websocket/   Channels consumers 与 routing
tests/       pytest 测试
```

## 文档入口

- [文档索引](docs/index.md)
- [架构设计](docs/architecture.md)
- [开发指南](docs/development.md)
- [API 接口](docs/api.md)
- [数据库设计](docs/database.md)
- [编码规范](docs/coding_standards.md)
- [技术审计（2026-03）](docs/technical_audit_2026-03.md)

## 相关文件

- `Makefile`
- `pyproject.toml`
- `requirements.txt`
- `package.json`
- `docker-compose.yml`
- `docker-compose.prod.yml`
