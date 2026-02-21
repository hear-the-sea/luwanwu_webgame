"""
帮会视图模块

拆分为以下子模块：
- core: 帮会大厅、列表、创建、详情
- membership: 成员管理、申请、职位
- contribution: 捐献、贡献排名
- technology: 帮会科技
- warehouse: 仓库交换
- announcement: 公告
"""

from .announcement import announcement_list, create_announcement
from .contribution import contribution_ranking, donate_resource, donation_logs, resource_logs, resource_status
from .core import create_guild, guild_detail, guild_hall, guild_info, guild_list, guild_search
from .membership import (
    application_list,
    apply_to_guild,
    appoint_admin,
    approve_application,
    demote_admin,
    disband_guild,
    kick_member,
    leave_guild,
    member_list,
    reject_application,
    transfer_leadership,
    upgrade_guild,
)
from .technology import technology_list, upgrade_technology
from .warehouse import exchange_item, exchange_logs, warehouse

__all__ = [
    # core
    "guild_hall",
    "guild_list",
    "guild_search",
    "create_guild",
    "guild_detail",
    "guild_info",
    # membership
    "apply_to_guild",
    "application_list",
    "approve_application",
    "reject_application",
    "member_list",
    "kick_member",
    "appoint_admin",
    "demote_admin",
    "transfer_leadership",
    "leave_guild",
    "upgrade_guild",
    "disband_guild",
    # contribution
    "donate_resource",
    "contribution_ranking",
    "donation_logs",
    "resource_logs",
    "resource_status",
    # technology
    "technology_list",
    "upgrade_technology",
    # warehouse
    "warehouse",
    "exchange_item",
    "exchange_logs",
    # announcement
    "announcement_list",
    "create_announcement",
]
