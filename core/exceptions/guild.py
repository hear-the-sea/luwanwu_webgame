"""
帮会相关异常
"""

from __future__ import annotations

from .base import GameError


class GuildError(GameError):
    """帮会相关错误基类"""

    error_code = "GUILD_ERROR"


class GuildMembershipError(GuildError):
    """帮会成员状态相关错误"""

    error_code = "GUILD_MEMBERSHIP_ERROR"


class GuildPermissionError(GuildError):
    """帮会权限相关错误"""

    error_code = "GUILD_PERMISSION_ERROR"


class GuildValidationError(GuildError):
    """帮会输入与创建校验错误"""

    error_code = "GUILD_VALIDATION_ERROR"


class GuildContributionError(GuildError):
    """帮会捐赠相关错误"""

    error_code = "GUILD_CONTRIBUTION_ERROR"


class GuildTechnologyError(GuildError):
    """帮会科技相关错误"""

    error_code = "GUILD_TECHNOLOGY_ERROR"


class GuildWarehouseError(GuildError):
    """帮会仓库相关错误"""

    error_code = "GUILD_WAREHOUSE_ERROR"
