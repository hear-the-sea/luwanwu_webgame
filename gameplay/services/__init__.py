"""
游戏玩法服务模块

本模块已重构为多个子模块以提高可维护性：
- manor: 庄园和建筑管理
- resources: 资源管理
- inventory: 背包物品管理
- messages: 消息管理
- missions: 任务管理

为保持向后兼容，所有函数在此统一导出。
"""

from __future__ import annotations

# 工具函数
from common.utils.loot import resolve_drop_rewards

# 背包物品管理
from .inventory import (
    ITEM_EFFECT_HANDLERS,
    NON_WAREHOUSE_MESSAGES,
    add_item_to_inventory,
    consume_inventory_item,
    get_item_quantity,
    list_inventory_items,
    sync_manor_grain,
    use_guest_rebirth_card,
    use_inventory_item,
    use_xisuidan,
    use_xidianka,
)

# 庄园和建筑管理
from .manor import (
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

# 消息管理
from .messages import (
    MESSAGE_RETENTION_DAYS,
    claim_message_attachments,
    cleanup_old_messages,
    create_message,
    delete_all_messages,
    delete_messages,
    list_messages,
    mark_all_messages_read,
    mark_messages_read,
    unread_message_count,
)

# 任务管理
from .missions import (
    add_mission_extra_attempt,
    award_mission_drops,
    bulk_get_mission_extra_attempts,
    bulk_mission_attempts_today,
    can_retreat,
    finalize_mission_run,
    get_mission_daily_limit,
    get_mission_extra_attempts,
    launch_mission,
    mission_attempts_today,
    normalize_mission_loadout,
    refresh_mission_runs,
    request_retreat,
    schedule_mission_completion,
)

# 资源管理
from .resources import grant_resources, log_resource_gain, spend_resources, sync_resource_production

# 技术管理
from .technology import (
    finalize_technology_upgrade,
    get_building_cost_reduction,
    get_categories,
    get_march_speed_bonus,
    get_martial_technologies_grouped,
    get_player_technologies,
    get_player_technology_level,
    get_resource_production_bonus,
    get_resource_production_bonus_from_levels,
    get_tech_bonus,
    get_technologies_by_category,
    get_technology_display_data,
    get_technology_template,
    get_troop_class_for_key,
    get_troop_classes,
    get_troop_stat_bonuses,
    load_technology_templates,
    refresh_technology_upgrades,
    schedule_technology_completion,
    upgrade_technology,
)

# 打工管理
from .work import (
    assign_guest_to_work,
    claim_work_reward,
    complete_work_assignments,
    get_available_works_for_guest,
    recall_guest_from_work,
    refresh_work_assignments,
)

# 藏宝阁管理
from .treasury import (
    get_treasury_capacity,
    get_treasury_used_space,
    get_warehouse_used_space,
    move_item_to_treasury,
    move_item_to_warehouse,
)

# 监牢/结义林
from .jail import (
    add_oath_bond,
    draw_pie,
    list_held_prisoners,
    list_oath_bonds,
    recruit_prisoner,
    release_prisoner,
    remove_oath_bond,
)

# 声望系统
from .prestige import (
    PRESTIGE_SILVER_THRESHOLD,
    add_prestige_silver,
    get_prestige_progress,
)

# 排行榜服务
from .ranking import (
    get_player_rank,
    get_prestige_ranking,
    get_ranking_with_player_context,
)

# 马房服务
from .stable import (
    HORSE_CONFIG,
    finalize_horse_production,
    get_active_productions,
    get_horse_options,
    get_max_production_quantity,
    get_stable_speed_bonus,
    has_active_production,
    refresh_horse_productions,
    start_horse_production,
)

# 畜牧场服务
from .ranch import (
    LIVESTOCK_CONFIG,
    finalize_livestock_production,
    get_active_livestock_productions,
    get_livestock_options,
    get_max_livestock_quantity,
    get_ranch_speed_bonus,
    has_active_livestock_production,
    refresh_livestock_productions,
    start_livestock_production,
)

# 冶炼坊服务
from .smithy import (
    METAL_CONFIG,
    finalize_smelting_production,
    get_active_smelting_productions,
    get_metal_options,
    get_max_smelting_quantity,
    get_smithy_speed_bonus,
    has_active_smelting_production,
    refresh_smelting_productions,
    start_smelting_production,
)

# 铁匠铺锻造服务
from .forge import (
    EQUIPMENT_CONFIG,
    EQUIPMENT_CATEGORIES,
    MATERIAL_NAMES,
    finalize_equipment_forging,
    get_active_forgings,
    get_equipment_by_category,
    get_equipment_options,
    get_forge_speed_bonus,
    get_max_forging_quantity,
    has_active_forging,
    refresh_equipment_forgings,
    start_equipment_forging,
)

# 护院募兵服务
from .recruitment import (
    calculate_recruitment_duration,
    check_recruitment_requirements,
    finalize_troop_recruitment,
    get_active_recruitments,
    get_player_troops,
    get_recruit_config,
    get_recruitment_options,
    get_troop_template,
    has_active_recruitment,
    load_troop_templates,
    refresh_troop_recruitments,
    start_troop_recruitment,
)

# 踢馆/PVP服务
from .raid import (
    # 地图查询
    search_manors_by_name,
    search_manors_by_region,
    search_manors_by_coordinate,
    get_manor_public_info,
    # 距离和工具函数
    calculate_distance,
    is_same_region,
    get_prestige_color,
    can_attack_target,
    get_asset_level,
    get_troop_description,
    # 侦察系统
    get_scout_tech_level,
    calculate_scout_success_rate,
    calculate_scout_travel_time,
    check_scout_cooldown,
    get_scout_count,
    start_scout,
    finalize_scout,
    refresh_scout_records,
    get_active_scouts,
    get_scout_history,
    # 踢馆出征
    calculate_raid_travel_time,
    get_active_raid_count,
    get_incoming_raids,
    start_raid,
    process_raid_battle,
    finalize_raid,
    # 撤退机制
    request_raid_retreat,
    can_raid_retreat,
    # 保护机制
    activate_peace_shield,
    get_protection_status,
    # 庄园迁移
    get_relocation_cost,
    relocate_manor,
    # 刷新服务
    refresh_raid_runs,
    get_active_raids,
    get_raid_history,
)

__all__ = [
    # 工具函数
    "resolve_drop_rewards",
    # 庄园和建筑
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
    # 资源
    "grant_resources",
    "log_resource_gain",
    "spend_resources",
    "sync_resource_production",
    # 背包物品
    "ITEM_EFFECT_HANDLERS",
    "NON_WAREHOUSE_MESSAGES",
    "add_item_to_inventory",
    "consume_inventory_item",
    "get_item_quantity",
    "list_inventory_items",
    "sync_manor_grain",
    "use_guest_rebirth_card",
    "use_inventory_item",
    "use_xisuidan",
    "use_xidianka",
    # 消息
    "MESSAGE_RETENTION_DAYS",
    "claim_message_attachments",
    "cleanup_old_messages",
    "create_message",
    "delete_all_messages",
    "delete_messages",
    "list_messages",
    "mark_all_messages_read",
    "mark_messages_read",
    "unread_message_count",
    # 任务
    "add_mission_extra_attempt",
    "award_mission_drops",
    "bulk_get_mission_extra_attempts",
    "bulk_mission_attempts_today",
    "can_retreat",
    "finalize_mission_run",
    "get_mission_daily_limit",
    "get_mission_extra_attempts",
    "launch_mission",
    "mission_attempts_today",
    "normalize_mission_loadout",
    "refresh_mission_runs",
    "request_retreat",
    "schedule_mission_completion",
    # 技术
    "finalize_technology_upgrade",
    "get_building_cost_reduction",
    "get_categories",
    "get_march_speed_bonus",
    "get_martial_technologies_grouped",
    "get_player_technologies",
    "get_player_technology_level",
    "get_resource_production_bonus",
    "get_resource_production_bonus_from_levels",
    "get_tech_bonus",
    "get_technologies_by_category",
    "get_technology_display_data",
    "get_technology_template",
    "get_troop_class_for_key",
    "get_troop_classes",
    "get_troop_stat_bonuses",
    "load_technology_templates",
    "refresh_technology_upgrades",
    "schedule_technology_completion",
    "upgrade_technology",
    # 打工
    "assign_guest_to_work",
    "claim_work_reward",
    "complete_work_assignments",
    "get_available_works_for_guest",
    "recall_guest_from_work",
    "refresh_work_assignments",
    # 藏宝阁
    "get_treasury_capacity",
    "get_treasury_used_space",
    "get_warehouse_used_space",
    "move_item_to_treasury",
    "move_item_to_warehouse",
    # 声望系统
    "PRESTIGE_SILVER_THRESHOLD",
    "add_prestige_silver",
    "get_prestige_progress",
    # 排行榜服务
    "get_player_rank",
    "get_prestige_ranking",
    "get_ranking_with_player_context",
    # 马房服务
    "HORSE_CONFIG",
    "finalize_horse_production",
    "get_active_productions",
    "get_horse_options",
    "get_max_production_quantity",
    "get_stable_speed_bonus",
    "has_active_production",
    "refresh_horse_productions",
    "start_horse_production",
    # 畜牧场服务
    "LIVESTOCK_CONFIG",
    "finalize_livestock_production",
    "get_active_livestock_productions",
    "get_livestock_options",
    "get_max_livestock_quantity",
    "get_ranch_speed_bonus",
    "has_active_livestock_production",
    "refresh_livestock_productions",
    "start_livestock_production",
    # 冶炼坊服务
    "METAL_CONFIG",
    "finalize_smelting_production",
    "get_active_smelting_productions",
    "get_metal_options",
    "get_max_smelting_quantity",
    "get_smithy_speed_bonus",
    "has_active_smelting_production",
    "refresh_smelting_productions",
    "start_smelting_production",
    # 铁匠铺锻造服务
    "EQUIPMENT_CONFIG",
    "EQUIPMENT_CATEGORIES",
    "MATERIAL_NAMES",
    "finalize_equipment_forging",
    "get_active_forgings",
    "get_equipment_by_category",
    "get_equipment_options",
    "get_forge_speed_bonus",
    "get_max_forging_quantity",
    "has_active_forging",
    "refresh_equipment_forgings",
    "start_equipment_forging",
    # 护院募兵服务
    "calculate_recruitment_duration",
    "check_recruitment_requirements",
    "finalize_troop_recruitment",
    "get_active_recruitments",
    "get_player_troops",
    "get_recruit_config",
    "get_recruitment_options",
    "get_troop_template",
    "has_active_recruitment",
    "load_troop_templates",
    "refresh_troop_recruitments",
    "start_troop_recruitment",
    # 踢馆/PVP服务
    # 地图查询
    "search_manors_by_name",
    "search_manors_by_region",
    "search_manors_by_coordinate",
    "get_manor_public_info",
    # 距离和工具函数
    "calculate_distance",
    "is_same_region",
    "get_prestige_color",
    "can_attack_target",
    "get_asset_level",
    "get_troop_description",
    # 侦察系统
    "get_scout_tech_level",
    "calculate_scout_success_rate",
    "calculate_scout_travel_time",
    "check_scout_cooldown",
    "get_scout_count",
    "start_scout",
    "finalize_scout",
    "refresh_scout_records",
    "get_active_scouts",
    "get_scout_history",
    # 踢馆出征
    "calculate_raid_travel_time",
    "get_active_raid_count",
    "get_incoming_raids",
    "start_raid",
    "process_raid_battle",
    "finalize_raid",
    # 撤退机制
    "request_raid_retreat",
    "can_raid_retreat",
    # 保护机制
    "activate_peace_shield",
    "get_protection_status",
    # 庄园迁移
    "get_relocation_cost",
    "relocate_manor",
    # 刷新服务
    "refresh_raid_runs",
    "get_active_raids",
    "get_raid_history",
    # 监牢/结义林
    "list_held_prisoners",
    "recruit_prisoner",
    "list_oath_bonds",
    "add_oath_bond",
    "remove_oath_bond",
    "draw_pie",
    "release_prisoner",
]
