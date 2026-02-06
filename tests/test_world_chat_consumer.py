from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from django.test import SimpleTestCase

from websocket.consumers import WorldChatConsumer


class WorldChatConsumerTests(SimpleTestCase):
    def test_chat_message_forwards_expected_fields(self):
        consumer = WorldChatConsumer()
        consumer.send_json = AsyncMock()

        event = {
            "payload": {
                "type": "message",
                "channel": "world",
                "id": 123,
                "ts": 1700000000000,
                "sender": {"id": 7, "name": "玩家A"},
                "text": "hello",
            }
        }

        asyncio.run(consumer.chat_message(event))

        consumer.send_json.assert_awaited_once_with(
            {
                "type": "message",
                "channel": "world",
                "id": 123,
                "ts": 1700000000000,
                "sender": {"id": 7, "name": "玩家A"},
                "text": "hello",
            }
        )

    def test_chat_message_supports_legacy_keys(self):
        consumer = WorldChatConsumer()
        consumer.send_json = AsyncMock()

        event = {
            "payload": {
                "type": "message",
                "message": "legacy",
                "timestamp": 1700000000001,
                "sender": {"id": 8, "name": "玩家B"},
            }
        }

        asyncio.run(consumer.chat_message(event))

        payload = consumer.send_json.await_args.args[0]
        self.assertEqual(payload["text"], "legacy")
        self.assertEqual(payload["ts"], 1700000000001)
