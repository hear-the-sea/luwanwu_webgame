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

# Building views
from .buildings import UpgradeBuildingView

# Core views
from .core import DashboardView, HomeView, RankingView, SettingsView, rename_manor_view

# Inventory views
from .inventory import (
    RecruitmentHallView,
    WarehouseView,
    move_item_to_treasury_view,
    move_item_to_warehouse_view,
    use_guest_rebirth_card_view,
    use_item_view,
    use_xidianka_view,
    use_xisuidan_view,
)

# Jail / Oath grove
from .jail import (
    JailView,
    OathGroveView,
    add_oath_bond_api,
    add_oath_bond_view,
    draw_pie_api,
    draw_pie_view,
    jail_status_api,
    oath_status_api,
    recruit_prisoner_api,
    recruit_prisoner_view,
    release_prisoner_api,
    release_prisoner_view,
    remove_oath_bond_api,
    remove_oath_bond_view,
)

# Map views
from .map import (
    MapView,
    RaidConfigView,
    manor_detail_api,
    map_search_api,
    protection_status_api,
    raid_status_api,
    retreat_raid_api,
    start_raid_api,
    start_scout_api,
)

# Message views
from .messages import (
    MessageListView,
    claim_attachment_view,
    delete_all_messages_view,
    delete_messages_view,
    mark_all_messages_read_view,
    mark_messages_read_view,
    view_message,
)

# Mission views
from .missions import AcceptMissionView, TaskBoardView, retreat_mission_view, retreat_scout_view, use_mission_card_view

# Production views
from .production import (
    ForgeView,
    RanchView,
    SmithyView,
    StableView,
    decompose_equipment_view,
    start_equipment_forging_view,
    start_horse_production_view,
    start_livestock_production_view,
    start_smelting_production_view,
    synthesize_blueprint_equipment_view,
)

# Recruitment views
from .recruitment import (
    TroopRecruitmentView,
    deposit_troop_to_bank_view,
    start_troop_recruitment_view,
    withdraw_troop_from_bank_view,
)

# Technology views
from .technology import TechnologyView, upgrade_technology_view

# Work views
from .work import WorkView, assign_work_view, claim_work_reward_view, recall_work_view

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
    "use_mission_card_view",
    # Inventory
    "RecruitmentHallView",
    "WarehouseView",
    "use_item_view",
    "use_guest_rebirth_card_view",
    "use_xisuidan_view",
    "use_xidianka_view",
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
    "decompose_equipment_view",
    "synthesize_blueprint_equipment_view",
    # Recruitment
    "TroopRecruitmentView",
    "start_troop_recruitment_view",
    "deposit_troop_to_bank_view",
    "withdraw_troop_from_bank_view",
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
    # Jail / Oath grove
    "jail_status_api",
    "recruit_prisoner_api",
    "add_oath_bond_api",
    "remove_oath_bond_api",
    "draw_pie_api",
    "draw_pie_view",
    "release_prisoner_api",
    "release_prisoner_view",
    "JailView",
    "recruit_prisoner_view",
    "add_oath_bond_view",
    "remove_oath_bond_view",
    "OathGroveView",
    "oath_status_api",
]
