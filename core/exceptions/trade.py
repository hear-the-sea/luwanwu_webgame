"""
交易相关异常
"""

from __future__ import annotations

from .base import GameError


class TradeError(GameError):
    """交易相关错误基类"""

    error_code = "TRADE_ERROR"


class ShopValidationError(TradeError):
    """商店买卖请求参数校验错误"""

    error_code = "SHOP_VALIDATION_ERROR"

    def __init__(self, *, action: str, message: str | None = None):
        if message is None:
            if action == "buy":
                message = "购买数量必须大于 0"
            elif action == "sell":
                message = "出售数量必须大于 0"
            else:
                message = "商店请求参数无效"
        super().__init__(message, action=action)
