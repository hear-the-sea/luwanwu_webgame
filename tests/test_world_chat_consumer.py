from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from django.test import SimpleTestCase

from websocket.consumers import WorldChatConsumer


class WorldChatConsumerTests(SimpleTestCase):
    def _build_consumer(self) -> WorldChatConsumer:
        consumer = WorldChatConsumer()
        consumer.user_id = 1
        consumer.display_name = "玩家A"
        consumer.channel_name = "test-channel"
        consumer.channel_layer = AsyncMock()
        consumer.send_json = AsyncMock()
        return consumer

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

    def test_normalize_text_escapes_and_removes_controls(self):
        consumer = WorldChatConsumer()
        raw = "<b>hi</b>\x01\n\n\n\nworld  "
        normalized = consumer._normalize_text(raw)
        self.assertEqual(normalized, "&lt;b&gt;hi&lt;/b&gt;\n\n\nworld")

    def test_receive_json_ping_returns_pong(self):
        consumer = self._build_consumer()

        asyncio.run(consumer.receive_json({"type": "ping"}))

        consumer.send_json.assert_awaited_once_with({"type": "pong"})

    def test_receive_json_rejects_non_string_text(self):
        consumer = self._build_consumer()

        asyncio.run(consumer.receive_json({"type": "send", "text": {"bad": True}}))

        consumer.send_json.assert_awaited_once_with(
            {"type": "error", "code": "invalid_text", "message": "消息格式错误"}
        )

    def test_receive_json_rate_limited_short_circuits(self):
        consumer = self._build_consumer()
        consumer._rate_limit = AsyncMock(return_value=(False, 8))
        consumer._consume_trumpet = AsyncMock(return_value=(True, ""))

        asyncio.run(consumer.receive_json({"type": "send", "text": "hello"}))

        payload = consumer.send_json.await_args.args[0]
        self.assertEqual(payload["code"], "rate_limited")
        self.assertIn("8s", payload["message"])
        consumer._consume_trumpet.assert_not_awaited()

    def test_receive_json_no_trumpet_returns_error(self):
        consumer = self._build_consumer()
        consumer._rate_limit = AsyncMock(return_value=(True, None))
        consumer._consume_trumpet = AsyncMock(return_value=(False, "小喇叭不足"))

        asyncio.run(consumer.receive_json({"type": "send", "text": "hello"}))

        consumer.send_json.assert_awaited_once_with({"type": "error", "code": "no_trumpet", "message": "小喇叭不足"})

    def test_receive_json_success_broadcasts_to_group(self):
        consumer = self._build_consumer()
        consumer._rate_limit = AsyncMock(return_value=(True, None))
        consumer._consume_trumpet = AsyncMock(return_value=(True, ""))
        consumer._append_history = AsyncMock()

        message = {
            "type": "message",
            "channel": "world",
            "id": 1,
            "ts": 1700000000000,
            "sender": {"id": 1, "name": "玩家A"},
            "text": "hello",
        }
        consumer._build_message = AsyncMock(return_value=message)

        asyncio.run(consumer.receive_json({"type": "send", "text": "hello"}))

        consumer._append_history.assert_awaited_once_with(message)
        consumer.channel_layer.group_send.assert_awaited_once_with(
            consumer.GROUP_NAME,
            {
                "type": "chat_message",
                "payload": message,
            },
        )
