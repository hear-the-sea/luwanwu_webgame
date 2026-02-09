"""
消息相关异常
"""

from __future__ import annotations

from .base import GameError


class MessageError(GameError):
    """消息相关错误基类"""

    error_code = "MESSAGE_ERROR"


class MessageNotFoundError(MessageError):
    """消息不存在"""

    error_code = "MESSAGE_NOT_FOUND"
    default_message = "该消息不存在"


class AttachmentNotFoundError(MessageError):
    """附件不存在"""

    error_code = "ATTACHMENT_NOT_FOUND"
    default_message = "该消息没有附件"


class AttachmentAlreadyClaimedError(MessageError):
    """附件已领取"""

    error_code = "ATTACHMENT_ALREADY_CLAIMED"
    default_message = "附件已经领取过了"


class NoAttachmentError(MessageError):
    """消息没有附件"""

    error_code = "NO_ATTACHMENT"
    default_message = "该消息没有附件"
