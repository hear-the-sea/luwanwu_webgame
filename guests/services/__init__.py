"""
门客系统服务模块

本模块已重构为多个子模块以提高可维护性：
- health: 生命值管理
- equipment: 装备管理
- recruitment: 招募系统
- training: 训练系统

为保持向后兼容，所有函数在此统一导出。
"""

from __future__ import annotations

# 装备管理
from .equipment import apply_set_bonuses, ensure_inventory_gears, equip_guest, give_gear, unequip_guest_item

# 生命值管理
from .health import INJURY_RECOVERY_THRESHOLD, heal_guest, recover_guest_hp, use_medicine_item_for_guest

# 忠诚度
from .loyalty import grant_battle_victory_loyalty

# 招募系统
from .recruitment import (
    CORE_POOL_TIERS,
    allocate_attribute_points,
    available_guests,
    bulk_finalize_candidates,
    choose_template_from_entries,
    convert_candidate_to_retainer,
    finalize_candidate,
    finalize_guest_recruitment,
    get_active_guest_recruitment,
    get_pool_recruitment_duration_seconds,
    grant_template_skills,
    has_active_guest_recruitment,
    list_candidates,
    list_pools,
    recruit_guest,
    refresh_guest_recruitments,
    reveal_candidate_rarity,
    start_guest_recruitment,
    use_magnifying_glass_for_candidates,
)

# 训练系统
from .training import (
    ensure_auto_training,
    finalize_guest_training,
    reduce_training_time,
    reduce_training_time_for_guest,
    train_guest,
    use_experience_item_for_guest,
)

__all__ = [
    # 生命值
    "heal_guest",
    "recover_guest_hp",
    "use_medicine_item_for_guest",
    "INJURY_RECOVERY_THRESHOLD",
    "grant_battle_victory_loyalty",
    # 装备
    "apply_set_bonuses",
    "ensure_inventory_gears",
    "equip_guest",
    "give_gear",
    "unequip_guest_item",
    # 招募
    "allocate_attribute_points",
    "available_guests",
    "bulk_finalize_candidates",
    "choose_template_from_entries",
    "convert_candidate_to_retainer",
    "finalize_guest_recruitment",
    "finalize_candidate",
    "get_active_guest_recruitment",
    "get_pool_recruitment_duration_seconds",
    "grant_template_skills",
    "has_active_guest_recruitment",
    "list_candidates",
    "list_pools",
    "refresh_guest_recruitments",
    "recruit_guest",
    "reveal_candidate_rarity",
    "start_guest_recruitment",
    "use_magnifying_glass_for_candidates",
    "CORE_POOL_TIERS",
    # 训练
    "ensure_auto_training",
    "finalize_guest_training",
    "reduce_training_time",
    "reduce_training_time_for_guest",
    "train_guest",
    "use_experience_item_for_guest",
]
