"""
招募和属性点相关异常
"""

from __future__ import annotations

from .base import GameError


# ============ 招募相关异常 ============


class RecruitmentError(GameError):
    """招募相关错误基类"""

    error_code = "RECRUITMENT_ERROR"


class PoolNotConfiguredError(RecruitmentError):
    """卡池未配置"""

    error_code = "POOL_NOT_CONFIGURED"
    default_message = "卡池尚未配置门客"


class NoTemplateAvailableError(RecruitmentError):
    """没有可用模板"""

    error_code = "NO_TEMPLATE_AVAILABLE"
    default_message = "缺少可用的门客模板，请更新 guest_templates.yaml 并重新加载"


# ============ 属性点相关异常 ============


class AttributePointError(GameError):
    """属性点相关错误基类"""

    error_code = "ATTRIBUTE_POINT_ERROR"


class InvalidAllocationError(AttributePointError):
    """无效的加点请求"""

    error_code = "INVALID_ALLOCATION"

    def __init__(self, reason: str, message: str | None = None):
        if message is None:
            if reason == "zero_points":
                message = "加点数量必须大于 0"
            elif reason == "insufficient":
                message = "属性点不足"
            elif reason == "unknown_attribute":
                message = "未知的加点属性"
            else:
                message = "无效的加点请求"
        super().__init__(message, reason=reason)
