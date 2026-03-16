"""Message builder – constructs outgoing world chat message dicts."""

from __future__ import annotations

import html
import logging
import re

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_re_control_chars = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _now_ts() -> float:
    # Keep backwards-compatible monkeypatching via `websocket.consumers.time.time`.
    from websocket import consumers as consumers_module

    return float(consumers_module.time.time())


def normalize_text(text: str) -> str:
    """Sanitize user-submitted chat text."""
    text = html.escape(text)
    cleaned = _re_control_chars.sub("", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned.strip()


def next_id_sync(redis, *, next_id_key: str) -> int:
    """Atomically generate the next message ID from Redis."""
    from websocket.consumers.world_chat import WorldChatInfrastructureError

    try:
        return int(redis.incr(next_id_key) or 0)
    except RedisError as exc:
        logger.warning("World chat next_id Redis error; rejecting send: %s", exc)
        raise WorldChatInfrastructureError("world chat id backend unavailable") from exc


def build_message_sync(
    text: str,
    redis,
    *,
    next_id_key: str,
    channel: str,
    user_id: int | None,
    display_name: str,
) -> dict:
    """Build a chat message dict with an auto-incremented ID and current timestamp."""
    msg_id = next_id_sync(redis, next_id_key=next_id_key)
    ts_ms = int(_now_ts() * 1000)
    return {
        "type": "message",
        "channel": channel,
        "id": msg_id,
        "ts": ts_ms,
        "sender": {"id": user_id, "name": display_name},
        "text": text,
    }
