# 健康检查运维手册

本文档描述健康检查端点的行为、各检查项的排障方法，以及与部署流水线的集成方式。

相关代码：`core/views/health.py`、`core/tasks.py`、`core/utils/degradation.py`

---

## 端点概览

| 端点 | 方法 | 用途 | 访问限制 |
|------|------|------|----------|
| `/health/live/` | GET | 存活探针，进程正常即返回 200 | 无 |
| `/health/ready/` | GET | 就绪探针，依赖全部正常才返回 200 | 可限制为内网 |

### `/health/live/`

返回 `{"status": "ok"}`，仅验证 Django 进程能响应 HTTP 请求，不检查任何外部依赖。适合作为 Kubernetes `livenessProbe` 或负载均衡器的 TCP 级探活。

### `/health/ready/`

逐项检查外部依赖是否可用，全部通过返回 200，任一失败返回 503。响应体结构：

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
  "degradation_counts": {}
}
```

`errors` 字段仅在 `DEBUG=True` 时包含异常详情；生产环境不暴露内部错误信息。

---

## 访问控制

当 `HEALTH_CHECK_REQUIRE_INTERNAL=True`（生产默认开启）时，`/health/ready/` 仅允许来自回环地址或 RFC 1918 内网 IP 的请求，外部请求返回 404。

如需从外部监控系统访问，有以下方案：
- 通过反向代理将健康检查请求转发到内网地址
- 设置环境变量 `DJANGO_HEALTH_CHECK_REQUIRE_INTERNAL=0` 关闭限制（不推荐直接暴露）

---

## 各检查项详解

### db（数据库）

**检查内容**：向默认数据库连接执行 `SELECT 1` 并读取结果。

**常见失败原因**：
- MySQL 服务宕机
- 数据库连接池耗尽（`CONN_MAX_AGE` 设置不合理）
- 网络分区导致数据库不可达
- 数据库磁盘空间不足导致只读模式

**排障步骤**：
1. 检查数据库进程状态：`systemctl status mysql` 或 `docker ps`
2. 尝试手动连接：`mysql -u <user> -p -h <host> -e "SELECT 1"`
3. 检查连接数：`SHOW PROCESSLIST;` 或 `SHOW STATUS LIKE 'Threads_connected';`
4. 检查 Django 日志中的 `DatabaseError` 异常

**恢复操作**：
- 重启数据库服务
- 如连接池耗尽，重启 Web / Worker 进程并检查连接回收策略
- 检查 `DATABASES["default"]["CONN_MAX_AGE"]` 和 `CONN_HEALTH_CHECKS` 配置

---

### cache（缓存）

**检查内容**：向 Django Cache 写入临时键 `health:ready:cache`，随即读取验证值一致，最后删除。

**常见失败原因**：
- Redis 服务宕机或不可达
- Redis 内存达到 `maxmemory` 上限且驱逐策略拒绝写入
- Redis 连接超时

**排障步骤**：
1. 检查 Redis 进程：`redis-cli ping`
2. 检查内存使用：`redis-cli info memory | grep used_memory_human`
3. 检查连接数：`redis-cli info clients | grep connected_clients`
4. 确认 `REDIS_CACHE_URL` 配置正确（默认使用 Redis DB 2）

**恢复操作**：
- 重启 Redis 服务
- 如内存不足，清理过期键或调整 `maxmemory`
- 检查网络连通性

---

### channel_layer（Channels 通道层）

**检查内容**：通过 Django Channels 的 Channel Layer 执行一次完整的发送-接收往返。创建临时通道，发送标记消息，在超时时间内等待接收。

**启用条件**：`HEALTH_CHECK_CHANNEL_LAYER=True`（生产默认开启）

**超时配置**：`HEALTH_CHECK_CHANNEL_LAYER_TIMEOUT_SECONDS`（默认 1.0 秒）

**常见失败原因**：
- Redis Channel Layer 后端（DB 1）不可用
- Channel Layer 配置错误（`CHANNEL_LAYERS` 未正确设置）
- Redis 延迟过高导致超时

**排障步骤**：
1. 检查 Redis DB 1 的连通性：`redis-cli -n 1 ping`
2. 检查 `CHANNEL_LAYERS` 配置中的 `hosts` 设置
3. 如超时频繁，考虑增大 `DJANGO_HEALTH_CHECK_CHANNEL_LAYER_TIMEOUT_SECONDS`

**恢复操作**：
- 重启 Redis 或检查 Redis DB 1 的可用性
- 如 WebSocket 功能已禁用，可设置 `DJANGO_HEALTH_CHECK_CHANNEL_LAYER=0` 跳过此检查

---

### celery_broker（Celery 消息代理）

**检查内容**：尝试打开一个到 Celery Broker（Redis DB 0）的只读连接。

**启用条件**：`HEALTH_CHECK_CELERY_BROKER=True`（生产默认开启）

**常见失败原因**：
- Redis DB 0 不可用
- Broker URL 配置错误
- 网络不通

**排障步骤**：
1. 检查 Redis DB 0：`redis-cli -n 0 ping`
2. 确认 `CELERY_BROKER_URL` 配置正确
3. 检查 Django 日志中的 Celery 连接异常

**恢复操作**：
- 重启 Redis
- 修正 Broker URL 配置

---

### celery_workers（Celery Worker 存活）

**检查内容**：通过 `celery_app.control.inspect().ping()` 向所有 Worker 发送 ping，要求至少一个 Worker 响应。超时为 1.0 秒。

**启用条件**：`HEALTH_CHECK_CELERY_WORKERS=True`（环境变量 `DJANGO_HEALTH_CHECK_CELERY_WORKERS=1`）

**常见失败原因**：
- 没有运行中的 Celery Worker
- Worker 卡死（死循环、死锁）
- Worker 正在重启中，尚未注册到 Broker

**排障步骤**：
1. 检查 Worker 进程：`celery -A config inspect ping`
2. 查看 Worker 日志中的异常
3. 检查 Worker 是否消费了正确的队列（`default`, `battle`, `timer`）

**恢复操作**：
- 重启 Celery Worker：`celery -A config worker -l INFO`
- 如 Worker 卡死，先 `kill -9` 再重启

---

### celery_beat（Celery Beat 心跳）

**检查内容**：从缓存读取键 `health:celery:beat:last_seen` 中的时间戳，验证距上次心跳不超过 `HEALTH_CHECK_CELERY_BEAT_MAX_AGE_SECONDS`（默认 180 秒）。

心跳由 Celery Beat 定期执行 `core.record_celery_beat_heartbeat` 任务写入。

**启用条件**：`HEALTH_CHECK_CELERY_BEAT=True`（环境变量 `DJANGO_HEALTH_CHECK_CELERY_BEAT=1`）

**常见失败原因**：
- Celery Beat 进程未运行
- Beat 进程运行但心跳任务未配置到 `CELERY_BEAT_SCHEDULE`
- 缓存不可用导致心跳无法写入/读取
- 首次部署后 Beat 尚未执行过心跳任务

**排障步骤**：
1. 检查 Beat 进程：`ps aux | grep celery.*beat`
2. 手动查看心跳缓存：`redis-cli -n 2 get "health:celery:beat:last_seen"`
3. 确认 Beat 配置中包含 `core.record_celery_beat_heartbeat` 任务
4. 如心跳过期但 Beat 在运行，检查 Worker 是否正常消费 `default` 队列

**恢复操作**：
- 重启 Celery Beat：`celery -A config beat -l INFO`
- 首次部署时可暂时增大 `DJANGO_HEALTH_CHECK_CELERY_BEAT_MAX_AGE_SECONDS` 等待首次心跳

---

### celery_roundtrip（Celery 端到端往返）

**检查内容**：发送一个 `celery_health_ping` 任务到 Celery，等待 Worker 返回 `"pong"` 结果。验证从 Broker 投递到 Worker 执行再到 Result Backend 回写的完整链路。

**启用条件**：`HEALTH_CHECK_CELERY_ROUNDTRIP=True`（环境变量 `DJANGO_HEALTH_CHECK_CELERY_ROUNDTRIP=1`）

**超时配置**：`HEALTH_CHECK_CELERY_ROUNDTRIP_TIMEOUT_SECONDS`（默认 3.0 秒）

**常见失败原因**：
- Worker 不可用（同 celery_workers）
- Result Backend 不可用或配置错误
- 任务队列积压严重，ping 任务排队超时
- Worker 未消费 `default` 队列

**排障步骤**：
1. 先确认 `celery_broker` 和 `celery_workers` 检查通过
2. 检查队列积压：`celery -A config inspect active_queues`
3. 检查 Result Backend 配置（通常也是 Redis）
4. 如超时频繁但 Worker 正常，考虑增大 `DJANGO_HEALTH_CHECK_CELERY_ROUNDTRIP_TIMEOUT_SECONDS`

**恢复操作**：
- 清理积压任务（谨慎操作）
- 增加 Worker 并发数
- 重启 Worker 进程

---

## 降级计数（degradation_counts）

`/health/ready/` 响应中的 `degradation_counts` 字段反映了进程内各模块的优雅降级次数（自进程启动以来的累计值）。

已定义的降级类别：

| 类别 | 含义 | 常见触发场景 |
|------|------|-------------|
| `cache_fallback` | 缓存读写失败，回退到本地缓存或数据库查询 | Redis 连接抖动 |
| `redis_failure` | Redis 操作失败 | Redis 宕机、网络超时 |
| `chat_history_degraded` | 世界聊天历史加载降级 | Redis 不可用时回退 |
| `world_chat_refund` | 世界聊天发送失败后退还消耗 | Channel Layer 异常 |
| `session_sync_failure` | 会话同步失败 | 会话后端不可用 |
| `celery_task_retry` | Celery 任务重试 | 任务执行异常触发自动重试 |

**解读方式**：
- 计数器为 0 表示该类别无降级发生，系统正常
- 小幅增长（如 1-5 次）通常是瞬态网络抖动，可观察
- 持续快速增长表示底层依赖存在系统性问题，需立即排查
- 计数器在进程重启后归零；如需持久化监控，应接入 Prometheus/StatsD 采集

---

## 配置标志汇总

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DJANGO_HEALTH_CHECK_REQUIRE_INTERNAL` | 生产 `1` / 开发 `0` | 限制 `/health/ready/` 仅允许内网访问 |
| `DJANGO_HEALTH_CHECK_CHANNEL_LAYER` | 生产 `1` / 开发 `0` | 启用 Channel Layer 检查 |
| `DJANGO_HEALTH_CHECK_CHANNEL_LAYER_TIMEOUT_SECONDS` | `1.0` | Channel Layer 往返超时 |
| `DJANGO_HEALTH_CHECK_CELERY_BROKER` | 生产 `1` / 开发 `0` | 启用 Celery Broker 连接检查 |
| `DJANGO_HEALTH_CHECK_CELERY_WORKERS` | `0` | 启用 Celery Worker ping 检查 |
| `DJANGO_HEALTH_CHECK_CELERY_BEAT` | `0` | 启用 Celery Beat 心跳检查 |
| `DJANGO_HEALTH_CHECK_CELERY_BEAT_MAX_AGE_SECONDS` | `180` | Beat 心跳最大允许年龄（秒） |
| `DJANGO_HEALTH_CHECK_CELERY_ROUNDTRIP` | `0` | 启用 Celery 端到端往返检查 |
| `DJANGO_HEALTH_CHECK_CELERY_ROUNDTRIP_TIMEOUT_SECONDS` | `3.0` | Celery 往返超时（秒） |

---

## 部署集成

### Kubernetes 探针配置

```yaml
livenessProbe:
  httpGet:
    path: /health/live/
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health/ready/
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 15
  failureThreshold: 2
  timeoutSeconds: 5
```

**注意事项**：
- `readinessProbe` 的 `timeoutSeconds` 应大于各检查项的超时之和（尤其是启用 `celery_roundtrip` 时）
- `HEALTH_CHECK_REQUIRE_INTERNAL` 在 K8s Pod 内网环境下通常满足条件，无需额外设置
- 如果 Celery Worker 和 Web 进程分属不同 Pod，Web Pod 的就绪探针检测 `celery_workers` 可能不合适；建议仅在包含 Worker 的 Pod 中启用

### 负载均衡器配置

- 使用 `/health/live/` 作为 TCP 级别的后端健康检查
- 使用 `/health/ready/` 作为 HTTP 级别的后端健康检查（确保来源 IP 为内网或关闭 `REQUIRE_INTERNAL`）
- 建议检查间隔：10-15 秒；不健康阈值：2-3 次

### 滚动部署

- 新版本启动后 `/health/ready/` 返回 200 才加入流量池
- 首次部署如启用了 `celery_beat` 检查，需等待 Beat 写入首次心跳（最长约 `CELERY_BEAT_MAX_AGE_SECONDS` 秒）
- 如果 `/health/ready/` 持续返回 503 导致 Pod 无法就绪，优先排查数据库和缓存连通性
