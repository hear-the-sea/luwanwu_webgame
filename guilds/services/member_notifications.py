from __future__ import annotations

import logging

from gameplay.models import Manor

from .guild_platform import create_message


def resolve_display_name(user_id: int) -> str:
    manor = Manor.objects.filter(user_id=user_id).first()
    if manor is None:
        return f"用户{user_id}"
    return manor.display_name


def send_system_message_to_user(
    user_id: int,
    *,
    title: str,
    body: str,
    action: str,
    guild_name: str,
    logger: logging.Logger,
) -> bool:
    manor = Manor.objects.filter(user_id=user_id).first()
    if manor is None:
        logger.warning(
            "Guild %s follow-up message skipped because manor missing: target_user_id=%s guild=%s",
            action,
            user_id,
            guild_name,
        )
        return False

    try:
        create_message(
            manor=manor,
            kind="system",
            title=title,
            body=body,
        )
    except Exception as exc:
        logger.warning(
            "Guild %s follow-up message failed: target_user_id=%s guild=%s error=%s",
            action,
            user_id,
            guild_name,
            exc,
            exc_info=True,
        )
        return False

    return True
