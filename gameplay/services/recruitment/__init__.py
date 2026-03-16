"""
招募系统服务模块

本模块包含招募相关功能：
- recruitment: 护院募兵服务
- troops: 部队管理和损失计算
"""

from __future__ import annotations

# 护院募兵生命周期（lifecycle.py）
from .lifecycle import finalize_troop_recruitment

# 护院募兵查询（queries.py）
from .queries import get_active_recruitments, get_player_troops, refresh_troop_recruitments

# 护院募兵配置/创建（recruitment.py）
from .recruitment import (
    calculate_recruitment_duration,
    check_recruitment_requirements,
    clear_troop_cache,
    get_recruit_config,
    get_recruitment_options,
    get_troop_template,
    has_active_recruitment,
    load_troop_templates,
    start_troop_recruitment,
)

# 部队管理（troops.py）
from .troops import apply_defender_troop_losses

__all__ = [
    # recruitment
    "calculate_recruitment_duration",
    "check_recruitment_requirements",
    "clear_troop_cache",
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
    # troops
    "apply_defender_troop_losses",
]
