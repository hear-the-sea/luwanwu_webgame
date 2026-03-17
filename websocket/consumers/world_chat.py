from __future__ import annotations

import asyncio
import logging

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import DatabaseError
from django_redis import get_redis_connection
from redis.exceptions import RedisError

from core.utils.degradation import WORLD_CHAT_REFUND, record_degradation
from websocket.backends.chat_history import (
    TRIM_HISTORY_SCRIPT,
    append_history_sync,
    get_history_sync,
    remove_history_sync,
    trim_history_by_time_fallback,
    trim_history_by_time_sync,
)
from websocket.backends.rate_limiter import rate_limit_sync
from websocket.services.message_builder import build_message_sync, next_id_sync, normalize_text

from ..utils import filter_payload
from .session_guard import SingleSessionWebSocketMixin

User = get_user_model()

logger = logging.getLogger(__name__)


class WorldChatInfrastructureError(RuntimeError):
    """Expected infrastructure/runtime dependency failure for world chat operations."""


WORLD_CHAT_EXPECTED_INFRASTRUCTURE_ERRORS = (
    WorldChatInfrastructureError,
    RedisError,
    ConnectionError,
    OSError,
    TimeoutError,
)


def _now_ts() -> float:
    # Keep backwards-compatible monkeypatching via `websocket.consumers.time.time`.
    # Import inside the helper to avoid circular imports at module import time.
    from websocket import consumers as consumers_module

    return float(consumers_module.time.time())


class WorldChatConsumer(SingleSessionWebSocketMixin, AsyncJsonWebsocketConsumer):
    """WebSocket consumer for the world chat channel."""

    CHANNEL = "world"
    GROUP_NAME = "chat_world"

    HISTORY_KEY = "chat:world:history"
    NEXT_ID_KEY = "chat:world:next_id"

    HISTORY_LIMIT = 200
    HISTORY_ON_CONNECT = 60
    HISTORY_MESSAGE_TTL_SECONDS = 24 * 60 * 60

    MESSAGE_MAX_LEN = 200
    RATE_LIMIT_WINDOW_SECONDS = 8
    RATE_LIMIT_MAX_MESSAGES = 6

    TRUMPET_ITEM_KEY = "small_trumpet"

    # Display name cache TTL (5 minutes)
    DISPLAY_NAME_CACHE_TTL = 300

    # Lua script kept as class attribute for backwards compatibility
    TRIM_HISTORY_SCRIPT = TRIM_HISTORY_SCRIPT

    user_id: int | None = None
    display_name: str = ""
    CHAT_UNAVAILABLE_MESSAGE = "世界频道暂时不可用，请稍后重试"
    CHAT_UNAVAILABLE_REFUNDED_MESSAGE = "世界频道暂时不可用，已返还小喇叭"
    CHAT_UNAVAILABLE_REFUND_FAILED_MESSAGE = "世界频道暂时不可用，请联系管理员补发小喇叭"
    HISTORY_UNAVAILABLE_MESSAGE = "历史消息暂时不可用，已跳过历史记录加载"

    _history_degraded: bool = False

    def _is_expected_infrastructure_error(self, exc: Exception) -> bool:
        return isinstance(exc, WORLD_CHAT_EXPECTED_INFRASTRUCTURE_ERRORS)

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
        if not await self._ensure_valid_session(force=True):
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
                "history_degraded": self._history_degraded,
                "history_status_message": self.HISTORY_UNAVAILABLE_MESSAGE if self._history_degraded else "",
            }
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def _process_send_message(self, content: dict) -> None:
        raw_text = content.get("text", "")
        if not isinstance(raw_text, str):
            await self.send_json({"type": "error", "code": "invalid_text", "message": "消息格式错误"})
            return

        text = self._normalize_text(raw_text)
        if not text:
            return
        if len(text) > self.MESSAGE_MAX_LEN:
            text = text[: self.MESSAGE_MAX_LEN]

        try:
            allowed, retry_after = await self._rate_limit(self.user_id)
        except WorldChatInfrastructureError:
            await self.send_json(
                {"type": "error", "code": "chat_unavailable", "message": self.CHAT_UNAVAILABLE_MESSAGE}
            )
            return
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

        history_written = False
        try:
            message = await self._build_message(text)
            await self._append_history(message)
            history_written = True
            await self.channel_layer.group_send(
                self.GROUP_NAME,
                {
                    "type": "chat_message",
                    "payload": message,
                },
            )
        except WORLD_CHAT_EXPECTED_INFRASTRUCTURE_ERRORS:
            history_removed = True
            if history_written:
                history_removed = await self._remove_history_compensation(message)
            refunded = await self._refund_trumpet()
            record_degradation(
                WORLD_CHAT_REFUND,
                component="world_chat",
                detail=f"publish failed, refunded={refunded}, history_removed={history_removed}",
                user_id=self.user_id,
            )
            logger.exception(
                "World chat publish failed after consuming trumpet: user_id=%s refunded=%s history_removed=%s",
                self.user_id,
                refunded,
                history_removed,
                extra={
                    "degraded": True,
                    "component": "world_chat_publish",
                    "user_id": self.user_id,
                    "refunded": refunded,
                    "history_removed": history_removed,
                },
            )
            await self.send_json(
                {
                    "type": "error",
                    "code": "chat_unavailable",
                    "message": (
                        self.CHAT_UNAVAILABLE_REFUNDED_MESSAGE
                        if refunded
                        else self.CHAT_UNAVAILABLE_REFUND_FAILED_MESSAGE
                    ),
                }
            )
        except Exception:
            logger.error(
                "Unexpected world chat publish failure: user_id=%s",
                self.user_id,
                exc_info=True,
                extra={"degraded": True, "component": "world_chat_publish", "user_id": self.user_id},
            )
            raise

    async def receive_json(self, content, **kwargs):
        try:
            if not await self._ensure_valid_session():
                await self.close()
                return

            msg_type = content.get("type")

            if msg_type == "ping":
                await self.send_json({"type": "pong"})
                return

            if msg_type != "send":
                return
            await self._process_send_message(content)
        except asyncio.CancelledError:
            raise
        except (ValueError, TypeError) as exc:
            logger.info("World chat message rejected due to invalid payload: %s", exc)
            await self.send_json({"type": "error", "code": "invalid_payload", "message": "消息格式错误"})

    async def chat_message(self, event):
        payload = event.get("payload", {})
        safe_payload = filter_payload(payload, ["type", "channel", "id", "ts", "sender", "text"])
        # 兼容旧字段名
        if "ts" not in safe_payload and "timestamp" in payload:
            safe_payload["ts"] = payload["timestamp"]
        if "text" not in safe_payload and "message" in payload:
            safe_payload["text"] = payload["message"]
        await self.send_json(safe_payload)

    # -- Delegating methods ------------------------------------------------
    # These thin wrappers preserve the existing instance-method interface
    # (used by tests via monkeypatching) while delegating to extracted modules.

    def _normalize_text(self, text: str) -> str:
        return normalize_text(text)

    def _get_redis(self):
        return get_redis_connection("default")

    def _safe_cache_get(self, key: str):
        try:
            return cache.get(key)
        except Exception as exc:
            logger.warning(
                "World chat cache.get failed: key=%s error=%s",
                key,
                exc,
                exc_info=True,
                extra={"degraded": True, "component": "world_chat_cache"},
            )
            return None

    def _safe_cache_set(self, key: str, value: str, timeout: int) -> None:
        try:
            cache.set(key, value, timeout=timeout)
        except Exception as exc:
            logger.warning(
                "World chat cache.set failed: key=%s error=%s",
                key,
                exc,
                exc_info=True,
                extra={"degraded": True, "component": "world_chat_cache"},
            )

    @database_sync_to_async
    def _get_display_name(self, user_id: int) -> str:
        cache_key = f"user:display_name:{user_id}"
        cached = self._safe_cache_get(cache_key)
        if cached is not None:
            return cached

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
                display_name = str(manor.display_name)
            except (AttributeError, TypeError, ValueError) as exc:
                logger.debug("Invalid manor display_name for world chat user_id=%s: %s", user_id, exc)
                display_name = user.get_full_name() or user.username or "玩家"
        else:
            display_name = user.get_full_name() or user.username or "玩家"

        self._safe_cache_set(cache_key, display_name, timeout=self.DISPLAY_NAME_CACHE_TTL)
        return display_name

    @database_sync_to_async
    def _consume_trumpet(self) -> tuple[bool, str]:
        from gameplay.services.chat import consume_trumpet

        if self.user_id is None:
            return False, "未登录，无法发言"
        return consume_trumpet(self.user_id)

    @database_sync_to_async
    def _refund_trumpet(self) -> bool:
        from gameplay.services.chat import refund_trumpet

        if self.user_id is None:
            return False
        return refund_trumpet(self.user_id)

    def _get_history_sync(self) -> list[dict]:
        redis = self._get_redis()
        messages, degraded = get_history_sync(
            redis,
            history_key=self.HISTORY_KEY,
            history_on_connect=self.HISTORY_ON_CONNECT,
            history_limit=self.HISTORY_LIMIT,
            history_message_ttl_seconds=self.HISTORY_MESSAGE_TTL_SECONDS,
            user_id=self.user_id,
        )
        self._history_degraded = degraded
        return messages

    async def _get_history(self) -> list[dict]:
        return await sync_to_async(self._get_history_sync, thread_sensitive=True)()

    def _trim_history_by_time_sync(self, cutoff_ms: int) -> None:
        redis = self._get_redis()
        trim_history_by_time_sync(
            cutoff_ms,
            redis,
            history_key=self.HISTORY_KEY,
            history_limit=self.HISTORY_LIMIT,
        )

    def _trim_history_by_time_fallback(self, cutoff_ms: int, redis) -> None:
        trim_history_by_time_fallback(
            cutoff_ms,
            redis,
            history_key=self.HISTORY_KEY,
            history_limit=self.HISTORY_LIMIT,
        )

    def _append_history_sync(self, message: dict) -> None:
        redis = self._get_redis()
        append_history_sync(
            message,
            redis,
            history_key=self.HISTORY_KEY,
            history_limit=self.HISTORY_LIMIT,
            history_message_ttl_seconds=self.HISTORY_MESSAGE_TTL_SECONDS,
        )

    async def _append_history(self, message: dict) -> None:
        await sync_to_async(self._append_history_sync, thread_sensitive=True)(message)

    def _remove_history_sync(self, message: dict) -> None:
        redis = self._get_redis()
        remove_history_sync(message, redis, history_key=self.HISTORY_KEY)

    async def _remove_history_compensation(self, message: dict) -> bool:
        try:
            await sync_to_async(self._remove_history_sync, thread_sensitive=True)(message)
            return True
        except WORLD_CHAT_EXPECTED_INFRASTRUCTURE_ERRORS:
            logger.exception(
                "World chat compensation delete failed: user_id=%s message_id=%s",
                self.user_id,
                message.get("id"),
                extra={
                    "degraded": True,
                    "component": "world_chat_publish",
                    "user_id": self.user_id,
                    "message_id": message.get("id"),
                },
            )
            return False

    def _rate_limit_sync(self, user_id: int | None) -> tuple[bool, int | None]:
        redis = self._get_redis()
        return rate_limit_sync(
            user_id,
            redis,
            rate_limit_window_seconds=self.RATE_LIMIT_WINDOW_SECONDS,
            rate_limit_max_messages=self.RATE_LIMIT_MAX_MESSAGES,
        )

    async def _rate_limit(self, user_id: int | None) -> tuple[bool, int | None]:
        return await sync_to_async(self._rate_limit_sync, thread_sensitive=True)(user_id)

    def _next_id_sync(self) -> int:
        redis = self._get_redis()
        return next_id_sync(redis, next_id_key=self.NEXT_ID_KEY)

    async def _build_message(self, text: str) -> dict:
        return await sync_to_async(
            lambda: build_message_sync(
                text,
                self._get_redis(),
                next_id_key=self.NEXT_ID_KEY,
                channel=self.CHANNEL,
                user_id=self.user_id,
                display_name=self.display_name,
            ),
            thread_sensitive=True,
        )()
