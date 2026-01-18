"""
踢馆战斗服务（包）

保持 `gameplay.services.raid.combat` 的导入/monkeypatch 表面稳定：
- 测试会 monkeypatch `random.*` 与 LOOT_* 常量，因此它们必须是本模块属性。
- 其余实现被拆分到子模块中，并在此处 re-export。
"""

from __future__ import annotations

import random

from ....constants import PVPConstants

# ============ 踢馆掠夺性能参数 ============

# 小库存：直接拉全量并 shuffle（更贴近原始语义）
LOOT_ITEM_SMALL_INVENTORY_THRESHOLD = 200
# 大库存：每轮抽样扫描的候选条数（越大越接近原始概率分布，但单次开销也更大）
LOOT_ITEM_SAMPLE_BATCH_SIZE = 200
# 大库存：最多抽样轮数（避免极端稀有库存导致长时间扫描）
LOOT_ITEM_SAMPLE_MAX_BATCHES = 6

from .battle import (  # noqa: E402
    _apply_prestige_changes,
    _execute_raid_battle,
    _send_raid_battle_messages,
    _try_capture_guest,
    process_raid_battle,
)
from .loot import (  # noqa: E402
    _apply_loot,
    _calculate_loot,
    _format_battle_rewards_description,
    _format_capture_description,
    _format_loot_description,
    _grant_loot_items,
)
from .runs import (  # noqa: E402
    _add_troops,
    _add_troops_batch,
    _deduct_troops,
    _finalize_raid_retreat,
    _return_surviving_troops,
    can_raid_retreat,
    finalize_raid,
    get_active_raids,
    get_raid_history,
    refresh_raid_runs,
    request_raid_retreat,
    start_raid,
)
from .travel import (  # noqa: E402
    _dismiss_marching_raids_if_protected,
    calculate_raid_travel_time,
    get_active_raid_count,
    get_incoming_raids,
)

__all__ = [
    # monkeypatch surface
    "random",
    "PVPConstants",
    "LOOT_ITEM_SMALL_INVENTORY_THRESHOLD",
    "LOOT_ITEM_SAMPLE_BATCH_SIZE",
    "LOOT_ITEM_SAMPLE_MAX_BATCHES",
    # travel
    "calculate_raid_travel_time",
    "get_active_raid_count",
    "get_incoming_raids",
    "_dismiss_marching_raids_if_protected",
    # raid lifecycle
    "start_raid",
    "process_raid_battle",
    "finalize_raid",
    "request_raid_retreat",
    "can_raid_retreat",
    "refresh_raid_runs",
    "get_active_raids",
    "get_raid_history",
    # internal helpers (imported by tests)
    "_calculate_loot",
    "_apply_loot",
    "_apply_prestige_changes",
    "_execute_raid_battle",
    "_send_raid_battle_messages",
    "_try_capture_guest",
    "_format_loot_description",
    "_format_battle_rewards_description",
    "_format_capture_description",
    "_deduct_troops",
    "_return_surviving_troops",
    "_add_troops",
    "_add_troops_batch",
    "_grant_loot_items",
    "_finalize_raid_retreat",
]
