"""
任务、打工和工资相关异常
"""

from __future__ import annotations

from typing import Any

from .base import GameError

# ============ 任务相关异常 ============


class MissionError(GameError):
    """任务相关错误基类"""

    error_code = "MISSION_ERROR"


class MissionDailyLimitError(MissionError):
    """任务次数已耗尽"""

    error_code = "MISSION_DAILY_LIMIT"
    default_message = "今日该任务次数已耗尽"


class MissionGuestSelectionError(MissionError):
    """任务门客选择错误"""

    error_code = "MISSION_GUEST_SELECTION_ERROR"


class MissionSquadSizeExceededError(MissionError):
    """任务出征人数超限"""

    error_code = "MISSION_SQUAD_SIZE_EXCEEDED"

    def __init__(self, limit: int, message: str | None = None):
        if message is None:
            message = f"最多只能派出 {limit} 名门客出征"
        super().__init__(message, limit=limit)


class MissionTroopLoadoutError(MissionError):
    """任务护院配置错误"""

    error_code = "MISSION_TROOP_LOADOUT_ERROR"


class MissionCannotRetreatError(MissionError):
    """无法撤退"""

    error_code = "MISSION_CANNOT_RETREAT"

    def __init__(self, reason: str = "ended", message: str | None = None):
        if message is None:
            if reason == "ended":
                message = "任务已结束，无法撤退"
            elif reason == "retreating":
                message = "任务已在撤退中"
            elif reason == "returning":
                message = "已进入返程，无法撤退"
            else:
                message = "无法撤退"
        super().__init__(message, reason=reason)


# ============ 竞技场相关异常 ============


class ArenaError(GameError):
    """竞技场相关错误基类"""

    error_code = "ARENA_ERROR"


class ArenaGuestSelectionError(ArenaError):
    """竞技场门客选择错误"""

    error_code = "ARENA_GUEST_SELECTION_ERROR"


class ArenaParticipationLimitError(ArenaError):
    """竞技场每日参与次数超限"""

    error_code = "ARENA_PARTICIPATION_LIMIT"

    def __init__(self, limit: int, message: str | None = None):
        if message is None:
            message = f"每日最多参加 {limit} 次竞技场"
        super().__init__(message, limit=limit)


class ArenaEntryStateError(ArenaError):
    """竞技场报名或撤销状态错误"""

    error_code = "ARENA_ENTRY_STATE_ERROR"


class ArenaCancellationError(ArenaEntryStateError):
    """竞技场撤销报名错误"""

    error_code = "ARENA_CANCELLATION_ERROR"


class ArenaBusyError(ArenaError):
    """竞技场系统忙碌"""

    error_code = "ARENA_BUSY"
    default_message = "竞技场报名繁忙，请稍后重试"


class ArenaExchangeError(ArenaError):
    """竞技场兑换错误"""

    error_code = "ARENA_EXCHANGE_ERROR"


class ArenaInsufficientCoinsError(ArenaExchangeError):
    """角斗币不足"""

    error_code = "ARENA_INSUFFICIENT_COINS"

    def __init__(self, required: int, available: int, message: str | None = None):
        if message is None:
            message = "角斗币不足"
        super().__init__(message, required=required, available=available)


class ArenaRewardLimitError(ArenaExchangeError):
    """竞技场奖励兑换次数超限"""

    error_code = "ARENA_REWARD_LIMIT"

    def __init__(self, reward_name: str, daily_limit: int, message: str | None = None):
        if message is None:
            message = f"{reward_name} 今日最多可兑换 {daily_limit} 次"
        super().__init__(message, reward_name=reward_name, daily_limit=daily_limit)


# ============ 打工相关异常 ============


class WorkError(GameError):
    """打工相关错误基类"""

    error_code = "WORK_ERROR"


class WorkNotInProgressError(WorkError):
    """不在打工中"""

    error_code = "WORK_NOT_IN_PROGRESS"
    default_message = "该任务不是打工中状态，无法召回"


class WorkNotCompletedError(WorkError):
    """任务未完成"""

    error_code = "WORK_NOT_COMPLETED"
    default_message = "该任务未完成，无法领取报酬"


class WorkRewardClaimedError(WorkError):
    """报酬已领取"""

    error_code = "WORK_REWARD_CLAIMED"
    default_message = "报酬已经领取过了"


class WorkLimitExceededError(WorkError):
    """打工人数超限"""

    error_code = "WORK_LIMIT_EXCEEDED"
    default_message = "打工人数已达上限"

    def __init__(self, limit: int):
        super().__init__(f"最多允许 {limit} 名门客同时打工")
        self.limit = limit


# ============ 工资相关异常 ============


class SalaryError(GameError):
    """工资相关错误基类"""

    error_code = "SALARY_ERROR"


class SalaryAlreadyPaidError(SalaryError):
    """工资已支付"""

    error_code = "SALARY_ALREADY_PAID"

    def __init__(self, guest: Any = None, message: str | None = None):
        if guest:
            guest_name = getattr(guest, "display_name", str(guest))
            if message is None:
                message = f"{guest_name} 今日工资已支付"
            super().__init__(message, guest_name=guest_name)
        else:
            if message is None:
                message = "所有门客今日工资已支付"
            super().__init__(message)


class NoGuestToPayError(SalaryError):
    """没有门客需要支付"""

    error_code = "NO_GUEST_TO_PAY"
    default_message = "所有门客今日工资已支付"
