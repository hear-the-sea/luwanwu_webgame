"""
gameplay views package

将原有的单一 views.py 拆分为多个模块，按功能分类：
- core: 核心页面（首页、仪表盘、设置）
- missions: 任务系统
- inventory: 仓库和物品管理
- messages: 消息系统
- production: 生产系统（马房、畜牧、冶炼、锻造）
- technology: 科技研究
- work: 打工系统
- recruitment: 募兵系统
- map: 地图和踢馆系统
"""

# Core views
from .core import (
    DashboardView,
    HomeView,
    SettingsView,
    RankingView,
    rename_manor_view,
)

# Mission views
from .missions import (
    TaskBoardView,
    AcceptMissionView,
    retreat_mission_view,
    retreat_scout_view,
)

# Inventory views
from .inventory import (
    RecruitmentHallView,
    WarehouseView,
    use_item_view,
    move_item_to_treasury_view,
    move_item_to_warehouse_view,
)

# Message views
from .messages import (
    MessageListView,
    view_message,
    delete_messages_view,
    delete_all_messages_view,
    mark_messages_read_view,
    mark_all_messages_read_view,
    claim_attachment_view,
)

# Building views
from .buildings import (
    UpgradeBuildingView,
)

# Technology views
from .technology import (
    TechnologyView,
    upgrade_technology_view,
)

# Work views
from .work import (
    WorkView,
    assign_work_view,
    recall_work_view,
    claim_work_reward_view,
)

# Production views
from .production import (
    StableView,
    RanchView,
    SmithyView,
    ForgeView,
    start_horse_production_view,
    start_livestock_production_view,
    start_smelting_production_view,
    start_equipment_forging_view,
)

# Recruitment views
from .recruitment import (
    TroopRecruitmentView,
    start_troop_recruitment_view,
)

# Map views
from .map import (
    MapView,
    RaidConfigView,
    map_search_api,
    manor_detail_api,
    start_scout_api,
    start_raid_api,
    retreat_raid_api,
    raid_status_api,
    protection_status_api,
)

__all__ = [
    # Core
    "DashboardView",
    "HomeView",
    "SettingsView",
    "RankingView",
    "rename_manor_view",
    # Missions
    "TaskBoardView",
    "AcceptMissionView",
    "retreat_mission_view",
    "retreat_scout_view",
    # Inventory
    "RecruitmentHallView",
    "WarehouseView",
    "use_item_view",
    "move_item_to_treasury_view",
    "move_item_to_warehouse_view",
    # Messages
    "MessageListView",
    "view_message",
    "delete_messages_view",
    "delete_all_messages_view",
    "mark_messages_read_view",
    "mark_all_messages_read_view",
    "claim_attachment_view",
    # Buildings
    "UpgradeBuildingView",
    # Technology
    "TechnologyView",
    "upgrade_technology_view",
    # Work
    "WorkView",
    "assign_work_view",
    "recall_work_view",
    "claim_work_reward_view",
    # Production
    "StableView",
    "RanchView",
    "SmithyView",
    "ForgeView",
    "start_horse_production_view",
    "start_livestock_production_view",
    "start_smelting_production_view",
    "start_equipment_forging_view",
    # Recruitment
    "TroopRecruitmentView",
    "start_troop_recruitment_view",
    # Map
    "MapView",
    "RaidConfigView",
    "map_search_api",
    "manor_detail_api",
    "start_scout_api",
    "start_raid_api",
    "retreat_raid_api",
    "raid_status_api",
    "protection_status_api",
]
