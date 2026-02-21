"""
WebSocket Routing Configuration

This module defines URL patterns for WebSocket connections.

Routes:
    ws/notifications/: User-specific notification delivery
    ws/online-stats/: Real-time online user statistics broadcasting
    ws/chat/world/: World chat channel
"""

from __future__ import annotations

from django.urls import path

from .consumers import NotificationConsumer, OnlineStatsConsumer, WorldChatConsumer

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi()),
    path("ws/online-stats/", OnlineStatsConsumer.as_asgi()),
    path("ws/chat/world/", WorldChatConsumer.as_asgi()),
]
