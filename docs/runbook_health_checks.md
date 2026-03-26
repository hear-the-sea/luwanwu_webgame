# 健康检查运行手册

> 最近校正：2026-03-26

相关代码：

- [`core/views/health.py`](/home/daniel/code/web_game_v5/core/views/health.py)
- [`core/views/health_support.py`](/home/daniel/code/web_game_v5/core/views/health_support.py)
- [`core/tasks.py`](/home/daniel/code/web_game_v5/core/tasks.py)
- [`websocket/routing_status.py`](/home/daniel/code/web_game_v5/websocket/routing_status.py)

## 端点概览

| 端点 | 方法 | 用途 | 访问限制 |
|------|------|------|----------|
| `/health/live` | GET | 存活探针 | 无 |
| `/health/live/` | GET | 与上面等价 | 无 |
| `/health/ready` | GET | 就绪探针 | 可限制为内网 |
| `/health/ready/` | GET | 与上面等价 | 可限制为内网 |

### `/health/live`

只验证 Django 进程是否能返回 HTTP 响应，返回：

```json
{"status": "ok"}
```

### `/health/ready`

按配置执行依赖检查，全部成功返回 `200`，任一失败返回 `503`。

典型响应：

```json
{
  "status": "ok | error",
  "checks": {
    "db": true,
    "cache": true,
    "channel_layer": true,
    "celery_broker": true,
    "celery_workers": true,
    "celery_beat": true,
    "celery_roundtrip": true
  },
  "errors": {},
  "degradation_counts": {},
  "task_metrics": {},
  "degraded_counters": {}
}
```

说明：

- `errors` 只在对应检查返回调试错误文本时出现，生产默认不暴露异常详情。
- `degradation_counts`、`task_metrics`、`degraded_counters` 只在 `DJANGO_HEALTH_CHECK_INCLUDE_DETAILS=1` 且对应数据非空时出现。
- `websocket_routing` 不是固定字段；只有 ASGI 路由导入失败时，才会以失败项出现在 `checks` 中。

## 响应缓存

`/health/ready` 支持短 TTL 缓存，配置项是：

- `DJANGO_HEALTH_CHECK_CACHE_TTL_SECONDS`

当前默认值：

- 开发环境：`0`
- 生产环境：`3`
- 测试环境：`0`

影响：

- 当 TTL 大于 `0` 时，短时间内会复用上一次 ready 结果。
- 排障时如果你刚恢复依赖但结果仍未刷新，先看是否命中了这层短缓存。

## 访问控制

当 `DJANGO_HEALTH_CHECK_REQUIRE_INTERNAL=1` 时，`/health/ready` 只接受：

- 回环地址
- RFC 1918 私网地址
- 受信任代理转发后的内部来源

不满足条件时直接返回 `404`，不是 `403`。

## 检查项说明

### db

检查内容：

- 对默认数据库执行 `SELECT 1`

常见失败原因：

- MySQL 宕机
- 网络不通
- 连接池耗尽
- 只读或异常恢复状态

### cache

检查内容：

- 向 Django cache 写入临时键后再读回并删除

常见失败原因：

- Redis cache 不可用
- 写入失败
- cache backend 配置错误

### channel_layer

启用开关：

- `DJANGO_HEALTH_CHECK_CHANNEL_LAYER`

检查内容：

- 创建临时 channel
- 发送一条标记消息
- 在超时内接收回环消息

超时配置：

- `DJANGO_HEALTH_CHECK_CHANNEL_LAYER_TIMEOUT_SECONDS`

常见失败原因：

- Redis channel layer 不可用
- `CHANNEL_LAYERS` 配置错误
- 延迟过高导致超时

### celery_broker

启用开关：

- `DJANGO_HEALTH_CHECK_CELERY_BROKER`

检查内容：

- 打开 Celery broker 的只读连接

常见失败原因：

- broker URL 配置错误
- Redis broker 不可用

### celery_workers

启用开关：

- `DJANGO_HEALTH_CHECK_CELERY_WORKERS`

检查内容：

- `celery_app.control.inspect().ping()`
- 至少一个 worker 响应才算成功

常见失败原因：

- 没有 worker 在运行
- worker 卡死或未注册到 broker

### celery_beat

启用开关：

- `DJANGO_HEALTH_CHECK_CELERY_BEAT`

检查内容：

- 读取 `health:celery:beat:last_seen`
- 验证时间戳没有超过允许年龄

相关任务：

- `core.record_celery_beat_heartbeat`

最大年龄配置：

- `DJANGO_HEALTH_CHECK_CELERY_BEAT_MAX_AGE_SECONDS`

### celery_roundtrip

启用开关：

- `DJANGO_HEALTH_CHECK_CELERY_ROUNDTRIP`

检查内容：

- 发送 `celery_health_ping`
- 等待 worker 返回 `"pong"`
- 验证 broker -> worker -> result backend 整条链路

超时配置：

- `DJANGO_HEALTH_CHECK_CELERY_ROUNDTRIP_TIMEOUT_SECONDS`

### websocket_routing

这不是独立探针开关，而是 ASGI 路由装配状态：

- 如果 `config.asgi` 在导入 `websocket.routing` 时失败
- ready 响应会附加 `checks.websocket_routing = false`
- 在 `DEBUG=True` 时还会附带错误文本

这项用于暴露“HTTP 能启动，但 WebSocket 路由其实坏了”的情况。

## 详情字段解读

当 `DJANGO_HEALTH_CHECK_INCLUDE_DETAILS=1` 时，响应可能追加以下字段：

| 字段 | 来源 | 作用 |
|------|------|------|
| `degradation_counts` | 进程内降级计数 | 观察缓存 / Redis / 聊天 / 任务重试等退化次数 |
| `task_metrics` | 任务监控统计 | 查看采样到的任务运行指标 |
| `degraded_counters` | 指定降级组件计数 | 观测关键 fail-open / fallback 组件 |

这些字段为空时会被省略，不要把“字段不存在”误判成接口异常。

## 排障顺序建议

1. 先看 `status` 和 `checks`
2. 如果 `cache` / `channel_layer` / `celery_*` 同时失败，优先检查 Redis
3. 如果只有 `db` 失败，优先检查 MySQL 连通性和连接数
4. 如果只有 `celery_workers` 或 `celery_roundtrip` 失败，检查 worker 是否还在消费正确队列
5. 如果只有 `websocket_routing` 失败，检查 `config.asgi` 和 `websocket.routing` 的导入错误
6. 如果启用了详情字段，再结合 `degradation_counts` 和 `degraded_counters` 判断是瞬态抖动还是持续退化

## 配置项汇总

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DJANGO_HEALTH_CHECK_REQUIRE_INTERNAL` | 开发 / 测试 `0`，生产 `1` | 限制 `/health/ready` 的来源 |
| `DJANGO_HEALTH_CHECK_CHANNEL_LAYER` | 开发 / 测试 `0`，生产 `1` | 启用 channel layer 检查 |
| `DJANGO_HEALTH_CHECK_CHANNEL_LAYER_TIMEOUT_SECONDS` | `1.0` | channel layer 往返超时 |
| `DJANGO_HEALTH_CHECK_CACHE_TTL_SECONDS` | 开发 / 测试 `0`，生产 `3` | ready 响应缓存 TTL |
| `DJANGO_HEALTH_CHECK_INCLUDE_DETAILS` | 开发 `1`，测试 / 生产 `0` | 是否附加详情字段 |
| `DJANGO_HEALTH_CHECK_CELERY_BROKER` | 开发 / 测试 `0`，生产 `1` | 启用 broker 检查 |
| `DJANGO_HEALTH_CHECK_CELERY_WORKERS` | `0` | 启用 worker ping 检查 |
| `DJANGO_HEALTH_CHECK_CELERY_BEAT` | `0` | 启用 beat 心跳检查 |
| `DJANGO_HEALTH_CHECK_CELERY_BEAT_MAX_AGE_SECONDS` | `180` | beat 心跳最大年龄 |
| `DJANGO_HEALTH_CHECK_CELERY_ROUNDTRIP` | `0` | 启用 Celery 端到端往返检查 |
| `DJANGO_HEALTH_CHECK_CELERY_ROUNDTRIP_TIMEOUT_SECONDS` | `3.0` | Celery 往返超时 |
