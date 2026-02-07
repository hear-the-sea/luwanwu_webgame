from __future__ import annotations

import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for per-user notifications."""

    group_name: str | None = None

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            logger.warning(
                "WebSocket authentication failed for NotificationConsumer",
                extra={
                    "path": self.scope.get("path"),
                    "client": self.scope.get("client"),
                },
            )
            await self.close()
            return

        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notify_message(self, event):
        payload = event.get("payload", {})
        safe_payload = {
            "type": payload.get("type"),
            "title": payload.get("title"),
            "message": payload.get("message"),
            "data": payload.get("data"),
            "timestamp": payload.get("timestamp"),
        }
        safe_payload = {k: v for k, v in safe_payload.items() if v is not None}
        await self.send_json(safe_payload)
