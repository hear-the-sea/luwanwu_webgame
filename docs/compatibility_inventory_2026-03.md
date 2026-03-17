# 兼容入口清单（2026-03）

只记录当前仍明确保留的兼容入口，不再记录已经删除的历史 facade。

原则：

- 已无仓内消费者、也无明确外部兼容需求的入口，直接删除
- 仍保留的入口必须写清消费者、保留原因和退场条件
- 新兼容层如果不能进入这份清单，就不应该合入

## 当前保留项

| 入口 | 当前消费者 | 保留原因 | 退场条件 |
| --- | --- | --- | --- |
| `gameplay.admin.enqueue_global_mail_backfill` 包级 re-export | `gameplay/admin/messages.py`、`tests/test_global_mail_admin.py` | admin action 与测试仍通过 `gameplay.admin` 包模块取回调 | `messages.py` 改为直接依赖真实任务模块或注入回调，测试同步改 patch 真实实现后删除 |
| `gameplay.services.raid.combat` 包根 re-export 与 `random` / `LOOT_*` monkeypatch 面 | `tests/test_raid_combat_runs.py`、`tests/test_raid_combat_battle.py`、`tests/test_raid_loot_clamping.py`、`tests/test_raid_retreat_timing.py`、`tests/test_raid_concurrency_integration.py` | raid 测试与稳定导入路径仍依赖包根入口；loot 调参与 RNG patch 也还挂在包根 | 测试和调用方迁到 `battle.py` / `runs.py` / `loot.py` 等真实子模块，并把 loot tunables 移到显式配置模块后收口 |
| `battle.combatants` 兼容 shim | 当前暂无仓内运行时调用；仅保留给外部旧导入路径与潜在第三方脚本 | 仓内调用已迁到 `battle.combatants_pkg`，但外部旧路径仍可能存在 | 确认无外部依赖或给出明确迁移公告后删除 |
| `gameplay.services.utils` 聚合导出 | `tests/test_message_attachments.py` 仍通过 `from gameplay.services.utils import messages as message_service` 取包根模块 | 历史导入路径仍在；包根当前还承担消息/缓存/通知工具聚合作用 | 仓内消费者迁到真实子模块后，收缩为纯包声明或最小稳定子模块入口 |
| `websocket.__getattr__` 懒加载入口 | `websocket/backends/chat_history.py`、`websocket/backends/rate_limiter.py`、`websocket/consumers/world_chat.py`、`websocket/services/message_builder.py`、`tests/test_asgi.py` | 多处仍通过 `from websocket import consumers` / `import websocket` 取包根懒加载属性 | 仓内调用全部迁到 `websocket.consumers` / `websocket.routing` 后，删除 `__getattr__` |
