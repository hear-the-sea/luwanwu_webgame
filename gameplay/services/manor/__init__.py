"""
庄园系统服务模块

本模块包含庄园核心功能：
- core: 庄园管理和建筑系统
- treasury: 藏宝阁管理
- prestige: 声望系统
"""

from __future__ import annotations

# 庄园核心（core.py）
from .core import (
    bootstrap_buildings,
    ensure_buildings_exist,
    ensure_manor,
    finalize_building_upgrade,
    finalize_upgrades,
    get_rename_card_count,
    is_manor_name_available,
    refresh_manor_state,
    rename_manor,
    schedule_building_completion,
    start_upgrade,
    validate_manor_name,
)

# 声望系统（prestige.py）
from .prestige import PRESTIGE_SILVER_THRESHOLD, add_prestige_silver, get_prestige_progress

# 藏宝阁（treasury.py）
from .treasury import (
    get_treasury_capacity,
    get_treasury_used_space,
    get_warehouse_used_space,
    move_item_to_treasury,
    move_item_to_warehouse,
)

__all__ = [
    # core
    "bootstrap_buildings",
    "ensure_buildings_exist",
    "ensure_manor",
    "finalize_building_upgrade",
    "finalize_upgrades",
    "get_rename_card_count",
    "is_manor_name_available",
    "refresh_manor_state",
    "rename_manor",
    "schedule_building_completion",
    "start_upgrade",
    "validate_manor_name",
    # treasury
    "get_treasury_capacity",
    "get_treasury_used_space",
    "get_warehouse_used_space",
    "move_item_to_treasury",
    "move_item_to_warehouse",
    # prestige
    "PRESTIGE_SILVER_THRESHOLD",
    "add_prestige_silver",
    "get_prestige_progress",
]
