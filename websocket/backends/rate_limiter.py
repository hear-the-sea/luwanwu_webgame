"""Rate limiter backend – Redis-backed sliding-window rate limiting for world chat."""

from __future__ import annotations

import logging

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def _now_ts() -> float:
    # Keep backwards-compatible monkeypatching via `websocket.consumers.time.time`.
    from websocket import consumers as consumers_module

    return float(consumers_module.time.time())


def rate_limit_sync(
    user_id: int | None,
    redis,
    *,
    rate_limit_window_seconds: int,
    rate_limit_max_messages: int,
) -> tuple[bool, int | None]:
    """Check whether a user is within the rate limit.

    Returns (allowed, retry_after_seconds).
    """
    from websocket.consumers.world_chat import WorldChatInfrastructureError

    if not user_id:
        return False, 3

    now_bucket = int(_now_ts() // rate_limit_window_seconds)
    key = f"chat:world:rate:{int(user_id)}:{now_bucket}"

    try:
        count = int(redis.incr(key) or 0)
        if count == 1:
            redis.expire(key, rate_limit_window_seconds + 2)
    except RedisError as exc:
        logger.warning("World chat rate limit Redis error; rejecting send: %s", exc)
        raise WorldChatInfrastructureError("world chat rate limit backend unavailable") from exc

    if count > rate_limit_max_messages:
        return False, rate_limit_window_seconds
    return True, None
