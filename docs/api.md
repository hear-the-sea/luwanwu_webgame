# 春秋乱世庄园主 - 接口与实时入口

> 最近校正：2026-03-23

这份文档不再手写“全量接口清单”。当前仓库的入口以 Django 页面路由为主，辅以少量 `JsonResponse` 端点和 WebSocket consumer；最可维护的文档方式是记录入口分类、稳定前缀、鉴权与限流边界。

## 总体约束

- 认证方式：Django Session
- 页面动作：大部分为表单 POST，默认要求 CSRF
- 失败反馈：页面动作通常经 Django Messages + redirect 返回；JSON 端点直接返回状态码与 JSON 载荷
- API 文档页：`/api/schema/`、`/api/docs/`、`/api/redoc/`
- 说明：仓库虽然安装了 DRF 与 drf-spectacular，但业务入口并不是“完整 DRF REST 平台”

## HTTP 路由前缀

| 前缀 | 主要职责 | 入口类型 |
|------|----------|----------|
| `/accounts/` | 登录、注册、资料 | 页面 |
| `/manor/` | 仪表盘、建筑、任务、仓库、消息、地图、科技、生产、竞技场 | 页面 + 局部 JSON |
| `/guests/` | 门客列表、详情、招募、培养、装备、技能 | 页面 + 少量 JSON |
| `/battle/` | 战报查看 | 页面 |
| `/trade/` | 商铺、银庄、交易行、拍卖 | 页面 |
| `/guilds/` | 帮会大厅、成员、科技、仓库、英雄池 | 页面 |
| `/health/` | 存活与就绪探针 | JSON |
| `/debugger/` | 战斗调试器，仅开发环境可选启用 | 页面 + JSON |

## 当前稳定 JSON 入口

### 健康检查

- `GET /health/live`
- `GET /health/ready`

两条路径都同时接受带斜杠和不带斜杠形式。

### 地图与踢馆相关

位于 `gameplay/views/map.py`，当前挂载为：

- `GET /manor/api/map/search/`
- `GET /manor/api/map/manor/<int:manor_id>/`
- `POST /manor/api/map/scout/`
- `POST /manor/api/map/raid/`
- `POST /manor/api/map/raid/<int:raid_id>/retreat/`
- `GET /manor/api/map/status/`
- `POST /manor/api/map/status/refresh/`
- `GET /manor/api/map/protection/`

### 监狱 / 义园相关

位于 `gameplay/views/jail.py`，当前挂载为：

- `GET /manor/api/jail/status/`
- `POST /manor/api/jail/prisoner/<int:prisoner_id>/recruit/`
- `POST /manor/api/jail/prisoner/<int:prisoner_id>/draw-pie/`
- `POST /manor/api/jail/prisoner/<int:prisoner_id>/release/`
- `GET /manor/api/oath/status/`
- `POST /manor/api/oath/add/`
- `POST /manor/api/oath/remove/`

### 门客装备选项

位于 `guests/views/equipment.py`：

- `GET /guests/gear-options/`

### battle debugger 辅助接口

仅在 `DJANGO_DEBUG=1` 且 `DJANGO_ENABLE_DEBUGGER=1` 时挂载：

- `GET /debugger/api/guests/`
- `GET /debugger/api/skills/`
- `GET /debugger/api/troops/`

## WebSocket 入口

定义于 `websocket/routing.py`：

- `ws/notifications/`：用户通知
- `ws/online-stats/`：在线人数广播
- `ws/chat/world/`：世界聊天

Channels 通过 `config/asgi.py` 注册，真实跨进程广播依赖 Redis channel layer。

## 限流

默认限流定义于 `config/settings/base.py`：

| scope | 额度 |
|-------|------|
| `anon` | `100/hour` |
| `user` | `1000/hour` |
| `recruit` | `20/hour` |
| `battle` | `100/hour` |
| `claim` | `50/hour` |

专项 throttle 类定义于 `config/throttling.py`：

- `RecruitThrottle`
- `BattleThrottle`
- `ClaimThrottle`

## battle debugger 的访问边界

该工具不是常驻生产入口，必须同时满足：

- `DJANGO_DEBUG=1`
- `DJANGO_ENABLE_DEBUGGER=1`
- 用户已登录
- 用户为 staff

## 联调建议

- 查页面入口和动作路径时，以各 app 的 `urls.py` 为准。
- 查 JSON 端点时，优先看 `gameplay/views/map.py`、`gameplay/views/jail.py`、`guests/views/equipment.py`。
- 改动任何路由前缀、鉴权方式或限流口径后，同步更新这里，不再维护按页面逐个手写的超长接口手册。
