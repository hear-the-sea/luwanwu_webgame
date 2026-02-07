"""Backwards-compatible import path for WebSocket consumers.

Historically, consumers lived in this single file. It has been split into
`websocket/consumers/*` for maintainability, while keeping this module as a
stable import target for routing and tests.
"""

from __future__ import annotations

import time  # re-exported for tests that monkeypatch websocket.consumers.time

from .consumers import NotificationConsumer, OnlineStatsConsumer, WorldChatConsumer

__all__ = [
    "NotificationConsumer",
    "OnlineStatsConsumer",
    "WorldChatConsumer",
    "time",
]
