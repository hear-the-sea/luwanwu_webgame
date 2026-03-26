from __future__ import annotations

import logging

from django.db import DatabaseError

from websocket.backends.chat_history import (
    append_history_sync,
    get_history_sync,
    remove_history_sync,
    trim_history_by_time_fallback,
    trim_history_by_time_sync,
)
from websocket.backends.rate_limiter import rate_limit_sync
from websocket.services.message_builder import build_message_sync, next_id_sync

from ..utils import filter_payload


def safe_cache_get(
    cache_backend,
    key: str,
    *,
    logger_instance: logging.Logger,
    cache_infrastructure_exceptions,
):
    try:
        return cache_backend.get(key)
    except cache_infrastructure_exceptions as exc:
        logger_instance.warning(
            "World chat cache.get failed: key=%s error=%s",
            key,
            exc,
            exc_info=True,
            extra={"degraded": True, "component": "world_chat_cache"},
        )
        return None


def safe_cache_set(
    cache_backend,
    key: str,
    value: str,
    timeout: int,
    *,
    logger_instance: logging.Logger,
    cache_infrastructure_exceptions,
) -> None:
    try:
        cache_backend.set(key, value, timeout=timeout)
    except cache_infrastructure_exceptions as exc:
        logger_instance.warning(
            "World chat cache.set failed: key=%s error=%s",
            key,
            exc,
            exc_info=True,
            extra={"degraded": True, "component": "world_chat_cache"},
        )


def resolve_display_name_sync(
    *,
    user_id: int,
    cache_key: str,
    user_model,
    cache_ttl: int,
    cache_get_fn,
    cache_set_fn,
    logger_instance: logging.Logger,
) -> str:
    cached = cache_get_fn(cache_key)
    if cached is not None:
        return cached

    try:
        user = user_model.objects.select_related("manor").get(id=user_id)
    except user_model.DoesNotExist:
        logger_instance.info("World chat user not found when resolving display name: user_id=%s", user_id)
        return "未知玩家"
    except DatabaseError:
        logger_instance.exception("Database error when resolving world chat display name: user_id=%s", user_id)
        return "未知玩家"

    manor = getattr(user, "manor", None)
    if manor is not None:
        try:
            display_name = str(manor.display_name)
        except (AttributeError, TypeError, ValueError) as exc:
            logger_instance.debug("Invalid manor display_name for world chat user_id=%s: %s", user_id, exc)
            display_name = user.get_full_name() or user.username or "玩家"
    else:
        display_name = user.get_full_name() or user.username or "玩家"

    cache_set_fn(cache_key, display_name, cache_ttl)
    return display_name


def get_history_sync_for_consumer(
    redis,
    *,
    history_key: str,
    history_on_connect: int,
    history_limit: int,
    history_message_ttl_seconds: int,
    user_id: int | None,
) -> tuple[list[dict], bool]:
    return get_history_sync(
        redis,
        history_key=history_key,
        history_on_connect=history_on_connect,
        history_limit=history_limit,
        history_message_ttl_seconds=history_message_ttl_seconds,
        user_id=user_id,
    )


def trim_history_by_time_sync_for_consumer(
    cutoff_ms: int,
    redis,
    *,
    history_key: str,
    history_limit: int,
) -> None:
    trim_history_by_time_sync(
        cutoff_ms,
        redis,
        history_key=history_key,
        history_limit=history_limit,
    )


def trim_history_by_time_fallback_for_consumer(
    cutoff_ms: int,
    redis,
    *,
    history_key: str,
    history_limit: int,
) -> None:
    trim_history_by_time_fallback(
        cutoff_ms,
        redis,
        history_key=history_key,
        history_limit=history_limit,
    )


def append_history_sync_for_consumer(
    message: dict,
    redis,
    *,
    history_key: str,
    history_limit: int,
    history_message_ttl_seconds: int,
) -> None:
    append_history_sync(
        message,
        redis,
        history_key=history_key,
        history_limit=history_limit,
        history_message_ttl_seconds=history_message_ttl_seconds,
    )


def remove_history_sync_for_consumer(message: dict, redis, *, history_key: str) -> None:
    remove_history_sync(message, redis, history_key=history_key)


def rate_limit_sync_for_consumer(
    user_id: int | None,
    redis,
    *,
    rate_limit_window_seconds: int,
    rate_limit_max_messages: int,
) -> tuple[bool, int | None]:
    return rate_limit_sync(
        user_id,
        redis,
        rate_limit_window_seconds=rate_limit_window_seconds,
        rate_limit_max_messages=rate_limit_max_messages,
    )


def next_id_sync_for_consumer(redis, *, next_id_key: str) -> int:
    return next_id_sync(redis, next_id_key=next_id_key)


def build_message_sync_for_consumer(
    text: str,
    redis,
    *,
    next_id_key: str,
    channel: str,
    user_id: int | None,
    display_name: str,
) -> dict:
    return build_message_sync(
        text,
        redis,
        next_id_key=next_id_key,
        channel=channel,
        user_id=user_id,
        display_name=display_name,
    )


async def send_connect_payloads(
    send_json_fn,
    *,
    channel: str,
    user_id: int | None,
    display_name: str,
    history: list[dict],
    history_degraded: bool,
    history_status_message: str,
) -> None:
    await send_json_fn(
        {
            "type": "history",
            "channel": channel,
            "messages": history,
        }
    )
    await send_json_fn(
        {
            "type": "status",
            "channel": channel,
            "status": "connected",
            "user": {"id": user_id, "name": display_name},
            "history_degraded": history_degraded,
            "history_status_message": history_status_message,
        }
    )


def filter_chat_message_payload(payload: dict) -> dict:
    safe_payload = filter_payload(payload, ["type", "channel", "id", "ts", "sender", "text"])
    if "ts" not in safe_payload and "timestamp" in payload:
        safe_payload["ts"] = payload["timestamp"]
    if "text" not in safe_payload and "message" in payload:
        safe_payload["text"] = payload["message"]
    return safe_payload


async def remove_history_compensation(
    *,
    remove_history_sync_fn,
    message: dict,
    expected_infrastructure_exceptions,
    logger_instance: logging.Logger,
    user_id: int | None,
) -> bool:
    from asgiref.sync import sync_to_async

    try:
        await sync_to_async(remove_history_sync_fn, thread_sensitive=True)(message)
        return True
    except expected_infrastructure_exceptions:
        logger_instance.exception(
            "World chat compensation delete failed: user_id=%s message_id=%s",
            user_id,
            message.get("id"),
            extra={
                "degraded": True,
                "component": "world_chat_publish",
                "user_id": user_id,
                "message_id": message.get("id"),
            },
        )
        return False
