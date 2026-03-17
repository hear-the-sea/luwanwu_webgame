"""
WebSocket Module

This module provides WebSocket consumers and routing for real-time communication.

Components:
    - NotificationConsumer: Handles user-specific notifications
    - OnlineStatsConsumer: Tracks and broadcasts online user statistics
    - websocket_urlpatterns: URL routing for WebSocket connections
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "NotificationConsumer",
    "OnlineStatsConsumer",
    "WorldChatConsumer",
    "consumers",
    "routing",
    "websocket_urlpatterns",
]


def __getattr__(name: str) -> Any:
    if name in {"NotificationConsumer", "OnlineStatsConsumer", "WorldChatConsumer"}:
        return getattr(import_module(".consumers", __name__), name)
    if name == "consumers":
        return import_module(".consumers", __name__)
    if name == "routing":
        return import_module(".routing", __name__)
    if name == "websocket_urlpatterns":
        return getattr(import_module(".routing", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
