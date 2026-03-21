"""
踢馆系统服务包

拆分为以下模块：
- utils: 工具函数（距离计算、声望颜色等）
- map_search: 地图查询服务
- scout: 侦察系统服务
- combat: 踢馆战斗服务
- protection: 保护机制服务
- relocation: 庄园迁移服务
"""

from __future__ import annotations

# 踢馆战斗
from .activity_refresh import refresh_raid_activity
from .combat import (
    calculate_raid_travel_time,
    can_raid_retreat,
    finalize_raid,
    get_active_raid_count,
    get_active_raids,
    get_incoming_raids,
    get_raid_history,
    process_raid_battle,
    refresh_raid_runs,
    request_raid_retreat,
    start_raid,
)

# 地图查询
from .map_search import (
    get_manor_public_info,
    search_manors_by_coordinate,
    search_manors_by_name,
    search_manors_by_region,
)

# 保护机制
from .protection import activate_peace_shield, get_protection_status

# 庄园迁移
from .relocation import get_relocation_cost, relocate_manor

# 侦察系统
from .scout import (
    calculate_scout_success_rate,
    calculate_scout_travel_time,
    can_scout_retreat,
    check_scout_cooldown,
    finalize_scout,
    finalize_scout_return,
    get_active_scouts,
    get_scout_count,
    get_scout_history,
    get_scout_tech_level,
    refresh_scout_records,
    request_scout_retreat,
    start_scout,
)

# 工具函数
from .utils import (
    calculate_distance,
    can_attack_target,
    get_asset_level,
    get_prestige_color,
    get_recent_attacks_24h,
    get_troop_description,
    invalidate_recent_attacks_cache,
    is_same_region,
)

__all__ = [
    # 工具函数
    "calculate_distance",
    "is_same_region",
    "get_prestige_color",
    "can_attack_target",
    "get_recent_attacks_24h",
    "invalidate_recent_attacks_cache",
    "get_asset_level",
    "get_troop_description",
    # 地图查询
    "search_manors_by_name",
    "search_manors_by_region",
    "search_manors_by_coordinate",
    "get_manor_public_info",
    # 侦察系统
    "get_scout_tech_level",
    "calculate_scout_success_rate",
    "calculate_scout_travel_time",
    "check_scout_cooldown",
    "get_scout_count",
    "start_scout",
    "finalize_scout",
    "finalize_scout_return",
    "refresh_scout_records",
    "get_active_scouts",
    "get_scout_history",
    "can_scout_retreat",
    "request_scout_retreat",
    # 踢馆战斗
    "calculate_raid_travel_time",
    "get_active_raid_count",
    "get_incoming_raids",
    "start_raid",
    "process_raid_battle",
    "finalize_raid",
    "refresh_raid_activity",
    "request_raid_retreat",
    "can_raid_retreat",
    "refresh_raid_runs",
    "get_active_raids",
    "get_raid_history",
    # 保护机制
    "activate_peace_shield",
    "get_protection_status",
    # 庄园迁移
    "get_relocation_cost",
    "relocate_manor",
]
