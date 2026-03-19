"""Chat history backend - Redis-backed storage for world chat messages."""

from __future__ import annotations

import json
import logging

from core.utils.degradation import CHAT_HISTORY_DEGRADED, record_degradation
from core.utils.infrastructure import INFRASTRUCTURE_EXCEPTIONS
from gameplay.services.utils.cache_exceptions import (
    CACHE_INFRASTRUCTURE_EXCEPTIONS,
    is_expected_cache_infrastructure_error,
)

logger = logging.getLogger(__name__)
LUA_FALLBACK_EXCEPTIONS: tuple[type[Exception], ...] = INFRASTRUCTURE_EXCEPTIONS + (AttributeError,)

# Lua script for batch history trimming (O(1) per removed message vs O(n) round trips)
TRIM_HISTORY_SCRIPT = """
local key = KEYS[1]
local cutoff = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local removed = 0
while removed < limit do
    local tail = redis.call('LINDEX', key, -1)
    if not tail then break end
    local ok, msg = pcall(cjson.decode, tail)
    if not ok then
        redis.call('RPOP', key)
        removed = removed + 1
    elseif msg.ts and tonumber(msg.ts) < cutoff then
        redis.call('RPOP', key)
        removed = removed + 1
    else
        break
    end
end
return removed
"""


def _now_ts() -> float:
    # Preserve test monkeypatching via `websocket.consumers.time.time`.
    from websocket.consumers import time as consumers_time

    return float(consumers_time.time())


def trim_history_by_time_fallback(
    cutoff_ms: int,
    redis,
    *,
    history_key: str,
    history_limit: int,
) -> None:
    """Python fallback for trimming history when Lua is unavailable."""
    for _ in range(int(history_limit)):
        raw_tail = redis.lindex(history_key, -1)
        if not raw_tail:
            return
        try:
            if isinstance(raw_tail, (bytes, bytearray)):
                raw_tail = raw_tail.decode("utf-8")
            msg = json.loads(raw_tail)
            ts = msg.get("ts") if isinstance(msg, dict) else None
            if isinstance(ts, (int, float)) and int(ts) >= int(cutoff_ms):
                return
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.debug("Dropping corrupted world chat history tail entry: %s", exc)
        except Exception:
            logger.exception("Unexpected error while trimming world chat history tail entry")
        redis.rpop(history_key)


def trim_history_by_time_sync(
    cutoff_ms: int,
    redis,
    *,
    history_key: str,
    history_limit: int,
) -> None:
    """Trim expired messages from history using Lua script for O(1) performance."""
    try:
        redis.eval(TRIM_HISTORY_SCRIPT, 1, history_key, cutoff_ms, history_limit)
    except LUA_FALLBACK_EXCEPTIONS as exc:
        # Fallback to Python-based trimming when Lua is unavailable (e.g., in tests)
        logger.debug("Lua script unavailable, using Python fallback: %s", exc)
        trim_history_by_time_fallback(cutoff_ms, redis, history_key=history_key, history_limit=history_limit)
    except Exception:
        logger.exception("Unexpected error while trimming world chat history")


def get_history_sync(
    redis,
    *,
    history_key: str,
    history_on_connect: int,
    history_limit: int,
    history_message_ttl_seconds: int,
    user_id: int | None,
) -> tuple[list[dict], bool]:
    """Fetch recent history from Redis.

    Returns a tuple of (messages, history_degraded).
    """
    cutoff_ms = int((_now_ts() - float(history_message_ttl_seconds)) * 1000)
    try:
        raw_items = redis.lrange(history_key, 0, max(0, history_on_connect - 1))
    except INFRASTRUCTURE_EXCEPTIONS:
        record_degradation(
            CHAT_HISTORY_DEGRADED,
            component="world_chat",
            detail="history Redis read failed",
            user_id=user_id,
        )
        return [], True

    messages: list[dict] = []
    for raw in reversed(raw_items or []):
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            msg = json.loads(raw)
            if not isinstance(msg, dict):
                continue
            ts = msg.get("ts")
            if isinstance(ts, (int, float)) and int(ts) < cutoff_ms:
                continue
            messages.append(msg)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.debug("Skipping malformed world chat history entry: %s", exc)
            continue
        except Exception:
            logger.exception("Unexpected error while parsing world chat history entry")
            continue

    try:
        trim_history_by_time_sync(cutoff_ms, redis, history_key=history_key, history_limit=history_limit)
    except INFRASTRUCTURE_EXCEPTIONS as exc:
        logger.debug("World chat history trim skipped due to Redis error: %s", exc)
    except Exception:
        logger.exception("Unexpected error while trimming world chat history")
    return messages, False


def append_history_sync(
    message: dict,
    redis,
    *,
    history_key: str,
    history_limit: int,
    history_message_ttl_seconds: int,
) -> None:
    """Append a message to chat history and trim expired entries."""
    from websocket.consumers.world_chat import WorldChatInfrastructureError

    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    try:
        pipe = redis.pipeline()
        pipe.lpush(history_key, payload)
        pipe.ltrim(history_key, 0, max(0, history_limit - 1))
        pipe.expire(history_key, int(history_message_ttl_seconds) + 60)
        pipe.execute()
    except Exception as exc:
        if not is_expected_cache_infrastructure_error(exc, exceptions=CACHE_INFRASTRUCTURE_EXCEPTIONS):
            raise
        logger.warning("World chat history append failed; rejecting send: %s", exc)
        raise WorldChatInfrastructureError("world chat history backend unavailable") from exc

    cutoff_ms = int((_now_ts() - float(history_message_ttl_seconds)) * 1000)
    trim_history_by_time_sync(cutoff_ms, redis, history_key=history_key, history_limit=history_limit)


def remove_history_sync(message: dict, redis, *, history_key: str) -> None:
    """Best-effort removal for a previously appended message."""
    from websocket.consumers.world_chat import WorldChatInfrastructureError

    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    try:
        redis.lrem(history_key, 1, payload)
    except Exception as exc:
        if not is_expected_cache_infrastructure_error(exc, exceptions=CACHE_INFRASTRUCTURE_EXCEPTIONS):
            raise
        logger.warning("World chat history compensation delete failed: %s", exc)
        raise WorldChatInfrastructureError("world chat history compensation unavailable") from exc
