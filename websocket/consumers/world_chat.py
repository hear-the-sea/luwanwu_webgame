from __future__ import annotations

import asyncio
import logging
import sys

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django_redis import get_redis_connection

from core.utils.degradation import WORLD_CHAT_REFUND, record_degradation
from core.utils.infrastructure import (
    INFRASTRUCTURE_EXCEPTIONS,
    InfrastructureExceptions,
    combine_infrastructure_exceptions,
)
from gameplay.services.utils.cache_exceptions import CACHE_INFRASTRUCTURE_EXCEPTIONS
from websocket.backends.chat_history import TRIM_HISTORY_SCRIPT
from websocket.services.message_builder import normalize_text

from .session_guard import SingleSessionWebSocketMixin
from .world_chat_support import (
    append_history_sync_for_consumer,
    build_message_sync_for_consumer,
    filter_chat_message_payload,
    get_history_sync_for_consumer,
    next_id_sync_for_consumer,
    rate_limit_sync_for_consumer,
    remove_history_compensation,
    remove_history_sync_for_consumer,
    resolve_display_name_sync,
    safe_cache_get,
    safe_cache_set,
    send_connect_payloads,
    trim_history_by_time_fallback_for_consumer,
    trim_history_by_time_sync_for_consumer,
)

User = get_user_model()

logger = logging.getLogger(__name__)


class WorldChatInfrastructureError(RuntimeError):
    """Expected infrastructure/runtime dependency failure for world chat operations."""


WORLD_CHAT_EXPECTED_INFRASTRUCTURE_ERRORS: InfrastructureExceptions = combine_infrastructure_exceptions(
    WorldChatInfrastructureError,
    infrastructure_exceptions=INFRASTRUCTURE_EXCEPTIONS,
)


def _now_ts() -> float:
    from websocket.consumers import time as consumers_time

    return float(consumers_time.time())


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
    DISPLAY_NAME_CACHE_TTL = 300
    TRIM_HISTORY_SCRIPT = TRIM_HISTORY_SCRIPT
    user_id: int | None = None
    display_name: str = ""
    CHAT_UNAVAILABLE_MESSAGE = "世界频道暂时不可用，请稍后重试"
    CHAT_UNAVAILABLE_REFUNDED_MESSAGE = "世界频道暂时不可用，已返还小喇叭"
    CHAT_UNAVAILABLE_REFUND_FAILED_MESSAGE = "世界频道暂时不可用，请联系管理员补发小喇叭"
    HISTORY_UNAVAILABLE_MESSAGE = "历史消息暂时不可用，已跳过历史记录加载"

    _history_degraded: bool = False

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
        if not await self._ensure_valid_session():
            await self.close()
            return

        self.user_id = int(user.id)
        self.display_name = await self._get_display_name(self.user_id)

        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()

        history = await self._get_history()
        await send_connect_payloads(
            self.send_json,
            channel=self.CHANNEL,
            user_id=self.user_id,
            display_name=self.display_name,
            history=history,
            history_degraded=self._history_degraded,
            history_status_message=self.HISTORY_UNAVAILABLE_MESSAGE if self._history_degraded else "",
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
        trumpet_consumed = True
        handled_infrastructure_failure = False
        message: dict | None = None
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
            handled_infrastructure_failure = True
            refunded, history_removed = await self._compensate_failed_publish(
                message=message,
                history_written=history_written,
            )
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
        finally:
            active_exc = sys.exc_info()[1]
            if active_exc is not None and trumpet_consumed and not handled_infrastructure_failure:
                refunded, history_removed = await self._compensate_failed_publish(
                    message=message,
                    history_written=history_written,
                )
                logger.error(
                    "Unexpected world chat publish failure: user_id=%s refunded=%s history_removed=%s",
                    self.user_id,
                    refunded,
                    history_removed,
                    exc_info=True,
                    extra={
                        "component": "world_chat_publish",
                        "user_id": self.user_id,
                        "refunded": refunded,
                        "history_removed": history_removed,
                    },
                )

    async def receive_json(self, content, **kwargs):
        try:
            msg_type = content.get("type")

            if msg_type == "ping":
                await self.send_json({"type": "pong"})
                return

            if not getattr(self, "_single_session_checked_by_dispatch", False):
                if not await self._ensure_valid_session():
                    await self.close()
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
        await self.send_json(filter_chat_message_payload(event.get("payload", {})))

    def _normalize_text(self, text: str) -> str:
        return normalize_text(text)

    def _get_redis(self):
        return get_redis_connection("default")

    def _safe_cache_get(self, key: str):
        return safe_cache_get(
            cache,
            key,
            logger_instance=logger,
            cache_infrastructure_exceptions=CACHE_INFRASTRUCTURE_EXCEPTIONS,
        )

    def _safe_cache_set(self, key: str, value: str, timeout: int) -> None:
        safe_cache_set(
            cache,
            key,
            value,
            timeout,
            logger_instance=logger,
            cache_infrastructure_exceptions=CACHE_INFRASTRUCTURE_EXCEPTIONS,
        )

    @database_sync_to_async
    def _get_display_name(self, user_id: int) -> str:
        return resolve_display_name_sync(
            user_id=user_id,
            cache_key=f"user:display_name:{user_id}",
            user_model=User,
            cache_ttl=self.DISPLAY_NAME_CACHE_TTL,
            cache_get_fn=self._safe_cache_get,
            cache_set_fn=self._safe_cache_set,
            logger_instance=logger,
        )

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
        messages, degraded = get_history_sync_for_consumer(
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
        trim_history_by_time_sync_for_consumer(
            cutoff_ms,
            redis,
            history_key=self.HISTORY_KEY,
            history_limit=self.HISTORY_LIMIT,
        )

    def _trim_history_by_time_fallback(self, cutoff_ms: int, redis) -> None:
        trim_history_by_time_fallback_for_consumer(
            cutoff_ms,
            redis,
            history_key=self.HISTORY_KEY,
            history_limit=self.HISTORY_LIMIT,
        )

    def _append_history_sync(self, message: dict) -> None:
        redis = self._get_redis()
        append_history_sync_for_consumer(
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
        remove_history_sync_for_consumer(message, redis, history_key=self.HISTORY_KEY)

    async def _remove_history_compensation(self, message: dict) -> bool:
        return await remove_history_compensation(
            remove_history_sync_fn=self._remove_history_sync,
            message=message,
            expected_infrastructure_exceptions=WORLD_CHAT_EXPECTED_INFRASTRUCTURE_ERRORS,
            logger_instance=logger,
            user_id=self.user_id,
        )

    async def _compensate_failed_publish(self, *, message: dict | None, history_written: bool) -> tuple[bool, bool]:
        history_removed = True
        if history_written and message is not None:
            history_removed = await self._remove_history_compensation(message)
        refunded = await self._refund_trumpet()
        return refunded, history_removed

    def _rate_limit_sync(self, user_id: int | None) -> tuple[bool, int | None]:
        redis = self._get_redis()
        return rate_limit_sync_for_consumer(
            user_id,
            redis,
            rate_limit_window_seconds=self.RATE_LIMIT_WINDOW_SECONDS,
            rate_limit_max_messages=self.RATE_LIMIT_MAX_MESSAGES,
        )

    async def _rate_limit(self, user_id: int | None) -> tuple[bool, int | None]:
        return await sync_to_async(self._rate_limit_sync, thread_sensitive=True)(user_id)

    def _next_id_sync(self) -> int:
        redis = self._get_redis()
        return next_id_sync_for_consumer(redis, next_id_key=self.NEXT_ID_KEY)

    async def _build_message(self, text: str) -> dict:
        return await sync_to_async(
            lambda: build_message_sync_for_consumer(
                text,
                self._get_redis(),
                next_id_key=self.NEXT_ID_KEY,
                channel=self.CHANNEL,
                user_id=self.user_id,
                display_name=self.display_name,
            ),
            thread_sensitive=True,
        )()
