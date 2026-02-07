from __future__ import annotations

import asyncio
import html
import json
import logging
import re

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django_redis import get_redis_connection
from redis.exceptions import RedisError

from core.exceptions import InsufficientStockError

User = get_user_model()

logger = logging.getLogger(__name__)


def _now_ts() -> float:
    # Keep backwards-compatible monkeypatching via `websocket.consumers.time.time`.
    # Import inside the helper to avoid circular imports at module import time.
    from websocket import consumers as consumers_module

    return float(consumers_module.time.time())


class WorldChatConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for the world chat channel."""

    CHANNEL = "world"
    GROUP_NAME = "chat_world"

    HISTORY_KEY = "chat:world:history"
    NEXT_ID_KEY = "chat:world:next_id"

    HISTORY_LIMIT = 200
    HISTORY_ON_CONNECT = 60
    HISTORY_MESSAGE_TTL_SECONDS = 15 * 60

    MESSAGE_MAX_LEN = 200
    RATE_LIMIT_WINDOW_SECONDS = 8
    RATE_LIMIT_MAX_MESSAGES = 6

    TRUMPET_ITEM_KEY = "small_trumpet"

    user_id: int | None = None
    display_name: str = ""

    _re_control_chars = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            logger.warning(
                "WebSocket authentication failed for WorldChatConsumer",
                extra={
                    "path": self.scope.get("path"),
                    "client": self.scope.get("client"),
                },
            )
            await self.close()
            return

        self.user_id = int(user.id)
        self.display_name = await self._get_display_name(self.user_id)

        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

        history = await self._get_history()
        await self.send_json(
            {
                "type": "history",
                "channel": self.CHANNEL,
                "messages": history,
            }
        )
        await self.send_json(
            {
                "type": "status",
                "channel": self.CHANNEL,
                "status": "connected",
                "user": {"id": self.user_id, "name": self.display_name},
            }
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def receive_json(self, content, **kwargs):
        try:
            msg_type = content.get("type")

            if msg_type == "ping":
                await self.send_json({"type": "pong"})
                return

            if msg_type != "send":
                return

            raw_text = content.get("text", "")
            if not isinstance(raw_text, str):
                await self.send_json({"type": "error", "code": "invalid_text", "message": "消息格式错误"})
                return

            text = self._normalize_text(raw_text)
            if not text:
                return

            if len(text) > self.MESSAGE_MAX_LEN:
                text = text[: self.MESSAGE_MAX_LEN]

            allowed, retry_after = await self._rate_limit(self.user_id)
            if not allowed:
                tip = "发送太快，请稍候再试"
                if retry_after:
                    tip = f"发送太快，请 {retry_after}s 后再试"
                await self.send_json({"type": "error", "code": "rate_limited", "message": tip})
                return

            success, error_msg = await self._consume_trumpet()
            if not success:
                await self.send_json({"type": "error", "code": "no_trumpet", "message": error_msg})
                return

            message = await self._build_message(text)
            await self._append_history(message)

            await self.channel_layer.group_send(
                self.GROUP_NAME,
                {
                    "type": "chat_message",
                    "payload": message,
                },
            )
        except asyncio.CancelledError:
            raise
        except (ValueError, TypeError) as exc:
            logger.info("World chat message rejected due to invalid payload: %s", exc)
            await self.send_json({"type": "error", "code": "invalid_payload", "message": "消息格式错误"})
        except Exception:
            logger.exception("Unexpected error handling world chat message")
            await self.send_json({"type": "error", "code": "server_error", "message": "服务器错误，请稍后重试"})

    async def chat_message(self, event):
        payload = event.get("payload", {})
        safe_payload = {
            "type": payload.get("type"),
            "channel": payload.get("channel"),
            "id": payload.get("id"),
            "ts": payload.get("ts", payload.get("timestamp")),
            "sender": payload.get("sender"),
            "text": payload.get("text", payload.get("message")),
        }
        safe_payload = {k: v for k, v in safe_payload.items() if v is not None}
        await self.send_json(safe_payload)

    def _normalize_text(self, text: str) -> str:
        text = html.escape(text)
        cleaned = self._re_control_chars.sub("", text)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
        return cleaned.strip()

    def _get_redis(self):
        return get_redis_connection("default")

    @database_sync_to_async
    def _get_display_name(self, user_id: int) -> str:
        try:
            user = User.objects.select_related("manor").get(id=user_id)
        except User.DoesNotExist:
            logger.info("World chat user not found when resolving display name: user_id=%s", user_id)
            return "未知玩家"
        except DatabaseError:
            logger.exception("Database error when resolving world chat display name: user_id=%s", user_id)
            return "未知玩家"

        manor = getattr(user, "manor", None)
        if manor is not None:
            try:
                return str(manor.display_name)
            except (AttributeError, TypeError, ValueError) as exc:
                logger.debug("Invalid manor display_name for world chat user_id=%s: %s", user_id, exc)

        return user.get_full_name() or user.username or "玩家"

    @database_sync_to_async
    def _consume_trumpet(self) -> tuple[bool, str]:
        from gameplay.models import Manor
        from gameplay.services.inventory import consume_inventory_item, get_item_quantity

        if self.user_id is None:
            return False, "未登录，无法发言"

        try:
            manor = Manor.objects.get(user_id=int(self.user_id))
        except Manor.DoesNotExist:
            return False, "庄园不存在，无法发言"

        quantity = get_item_quantity(manor, self.TRUMPET_ITEM_KEY)
        if quantity < 1:
            return False, "小喇叭不足，无法在世界频道发言"

        try:
            consume_inventory_item(manor, self.TRUMPET_ITEM_KEY, 1)
        except InsufficientStockError:
            return False, "小喇叭不足，无法在世界频道发言"
        except ValueError as exc:
            logger.warning("Failed to consume trumpet due to invalid input: %s", exc)
            return False, "扣除小喇叭失败，请稍后重试"
        except DatabaseError:
            logger.exception("Database error when consuming trumpet for user_id=%s", self.user_id)
            return False, "扣除小喇叭失败，请稍后重试"
        except Exception:
            logger.exception("Unexpected error when consuming trumpet for user_id=%s", self.user_id)
            return False, "扣除小喇叭失败，请稍后重试"

        return True, ""

    def _get_history_sync(self) -> list[dict]:
        redis = self._get_redis()
        cutoff_ms = int((_now_ts() - float(self.HISTORY_MESSAGE_TTL_SECONDS)) * 1000)
        try:
            raw_items = redis.lrange(self.HISTORY_KEY, 0, max(0, self.HISTORY_ON_CONNECT - 1))
        except RedisError as exc:
            logger.warning("World chat history Redis read failed; returning empty history: %s", exc)
            return []

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
            self._trim_history_by_time_sync(cutoff_ms)
        except RedisError as exc:
            logger.debug("World chat history trim skipped due to Redis error: %s", exc)
        except Exception:
            logger.exception("Unexpected error while trimming world chat history")
        return messages

    async def _get_history(self) -> list[dict]:
        return await sync_to_async(self._get_history_sync, thread_sensitive=True)()

    def _trim_history_by_time_sync(self, cutoff_ms: int) -> None:
        redis = self._get_redis()
        for _ in range(int(self.HISTORY_LIMIT)):
            raw_tail = redis.lindex(self.HISTORY_KEY, -1)
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
            redis.rpop(self.HISTORY_KEY)

    def _append_history_sync(self, message: dict) -> None:
        redis = self._get_redis()
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        pipe = redis.pipeline()
        pipe.lpush(self.HISTORY_KEY, payload)
        pipe.ltrim(self.HISTORY_KEY, 0, max(0, self.HISTORY_LIMIT - 1))
        pipe.expire(self.HISTORY_KEY, int(self.HISTORY_MESSAGE_TTL_SECONDS) + 60)
        pipe.execute()

        cutoff_ms = int((_now_ts() - float(self.HISTORY_MESSAGE_TTL_SECONDS)) * 1000)
        self._trim_history_by_time_sync(cutoff_ms)

    async def _append_history(self, message: dict) -> None:
        try:
            await sync_to_async(self._append_history_sync, thread_sensitive=True)(message)
        except RedisError as exc:
            logger.debug("World chat history write skipped due to Redis error: %s", exc)
        except Exception:
            logger.exception("Unexpected error while appending world chat history")

    def _rate_limit_sync(self, user_id: int | None) -> tuple[bool, int | None]:
        if not user_id:
            return False, 3

        redis = self._get_redis()
        now_bucket = int(_now_ts() // self.RATE_LIMIT_WINDOW_SECONDS)
        key = f"chat:world:rate:{int(user_id)}:{now_bucket}"

        try:
            count = int(redis.incr(key) or 0)
            if count == 1:
                redis.expire(key, self.RATE_LIMIT_WINDOW_SECONDS + 2)
        except RedisError as exc:
            logger.debug("World chat rate limit Redis error; allowing message: %s", exc)
            return True, None

        if count > self.RATE_LIMIT_MAX_MESSAGES:
            return False, self.RATE_LIMIT_WINDOW_SECONDS
        return True, None

    async def _rate_limit(self, user_id: int | None) -> tuple[bool, int | None]:
        return await sync_to_async(self._rate_limit_sync, thread_sensitive=True)(user_id)

    def _next_id_sync(self) -> int:
        redis = self._get_redis()
        try:
            return int(redis.incr(self.NEXT_ID_KEY) or 0)
        except RedisError as exc:
            logger.debug("World chat next_id Redis error; falling back to timestamp: %s", exc)
            return int(_now_ts() * 1000)

    async def _build_message(self, text: str) -> dict:
        msg_id = await sync_to_async(self._next_id_sync, thread_sensitive=True)()
        ts_ms = int(_now_ts() * 1000)
        return {
            "type": "message",
            "channel": self.CHANNEL,
            "id": msg_id,
            "ts": ts_ms,
            "sender": {"id": self.user_id, "name": self.display_name},
            "text": text,
        }
