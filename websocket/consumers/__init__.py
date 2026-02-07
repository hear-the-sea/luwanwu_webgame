"""WebSocket consumers.

We keep backwards-compatible re-exports so existing imports like
`from websocket.consumers import OnlineStatsConsumer` keep working.
"""

from __future__ import annotations

import time  # re-exported for tests monkeypatching websocket.consumers.time.time

from .notifications import NotificationConsumer
from .online_stats import OnlineStatsConsumer
from .world_chat import WorldChatConsumer

__all__ = [
    "NotificationConsumer",
    "OnlineStatsConsumer",
    "WorldChatConsumer",
    "time",
]
