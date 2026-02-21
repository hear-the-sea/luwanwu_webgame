"""
WebSocket Module

This module provides WebSocket consumers and routing for real-time communication.

Components:
    - NotificationConsumer: Handles user-specific notifications
    - OnlineStatsConsumer: Tracks and broadcasts online user statistics
    - websocket_urlpatterns: URL routing for WebSocket connections
"""

from __future__ import annotations

from .consumers import NotificationConsumer, OnlineStatsConsumer
from .routing import websocket_urlpatterns

__all__ = ["NotificationConsumer", "OnlineStatsConsumer", "websocket_urlpatterns"]
