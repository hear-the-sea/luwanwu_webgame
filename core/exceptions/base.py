"""
游戏错误基类模块
"""

from __future__ import annotations

from typing import Any


class GameError(Exception):
    """
    游戏错误基类

    所有游戏业务逻辑相关的异常都应继承此类。
    提供统一的错误代码和消息格式化机制。
    """

    error_code: str = "GAME_ERROR"
    default_message: str = "游戏发生错误"

    def __init__(self, message: str | None = None, **context: Any):
        self.message = message or self.default_message
        self.context = context
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message
