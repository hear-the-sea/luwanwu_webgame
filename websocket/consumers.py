"""
WebSocket Consumers

This module provides WebSocket consumers for real-time communication features.

Classes:
    NotificationConsumer: Handles per-user notification delivery via WebSocket
    OnlineStatsConsumer: Broadcasts real-time online user statistics
    WorldChatConsumer: World channel chat via WebSocket
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import DatabaseError
from django_redis import get_redis_connection
from redis.exceptions import RedisError

from core.exceptions import InsufficientStockError

User = get_user_model()

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for per-user notifications.

    Connects authenticated users to a user-specific channel group and delivers
    notifications in real-time. Only authenticated users are allowed.

    Attributes:
        group_name: The channel group name for this user (format: "user_{id}")
    """

    group_name: str | None = None

    async def connect(self):
        """
        Handle WebSocket connection establishment.

        Validates user authentication, creates a user-specific group,
        and accepts the connection.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            # 审计日志：记录认证失败的连接尝试
            logger.warning(
                "WebSocket authentication failed for NotificationConsumer",
                extra={
                    "path": self.scope.get("path"),
                    "client": self.scope.get("client"),
                }
            )
            await self.close()
            return

        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        """
        Handle WebSocket disconnection.

        Removes the user from their channel group.

        Args:
            close_code: WebSocket close code
        """
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notify_message(self, event):
        """
        Handle notification message events from channel layer.

        Args:
            event: Event dict containing "payload" key with notification data
        """
        # 验证 payload 结构，只转发预期的字段
        payload = event.get("payload", {})
        safe_payload = {
            "type": payload.get("type"),
            "title": payload.get("title"),
            "message": payload.get("message"),
            "data": payload.get("data"),
            "timestamp": payload.get("timestamp"),
        }
        # 移除 None 值
        safe_payload = {k: v for k, v in safe_payload.items() if v is not None}
        await self.send_json(safe_payload)


class OnlineStatsConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for real-time online user statistics.

    Tracks online users using a Redis sorted-set with last-seen timestamps.
    A lightweight heartbeat updates last-seen while the WebSocket is connected.
    Expired entries are cleaned up on read.

    Only authenticated non-staff/non-superuser accounts are counted as "real users".

    Attributes:
        STATS_GROUP: Channel group name for broadcasting statistics
        ONLINE_USERS_KEY: Redis key for the online users ZSET
        ONLINE_USERS_TTL: TTL window (seconds) for auto-cleanup (30 minutes)
        ONLINE_USERS_HEARTBEAT_INTERVAL: Heartbeat interval (seconds)
        user_id: ID of the connected user (None if not authenticated)
        is_real_user: Whether the user is a non-staff/non-superuser account
    """

    STATS_GROUP = "online_stats"
    ONLINE_USERS_KEY = "online_users_zset"
    ONLINE_USERS_TTL = 1800  # 30 minutes window for auto-cleanup
    ONLINE_USERS_HEARTBEAT_INTERVAL = 300  # refresh every 5 minutes
    ONLINE_USER_CONN_COUNT_KEY_PREFIX = "online_user_conn_count:"

    # Cache keys for performance optimization
    ONLINE_COUNT_CACHE_KEY = "stats:online_users_count"
    TOTAL_COUNT_CACHE_KEY = "stats:total_users_count"
    ONLINE_COUNT_CACHE_TTL = 5  # 5 seconds cache for online count
    TOTAL_COUNT_CACHE_TTL = 300  # 5 minutes cache for total count

    # Initialize instance attributes with defaults to prevent AttributeError
    # in edge cases where disconnect is called before successful authentication
    user_id: int | None = None
    is_real_user: bool = False
    heartbeat_task: asyncio.Task | None = None

    async def connect(self):
        """
        Handle WebSocket connection establishment.

        Validates authentication, adds the user to the online users set,
        sends current statistics, and broadcasts the update.
        """
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            # 审计日志：记录认证失败的连接尝试
            logger.warning(
                "WebSocket authentication failed for OnlineStatsConsumer",
                extra={
                    "path": self.scope.get("path"),
                    "client": self.scope.get("client"),
                }
            )
            await self.close()
            return

        self.user_id = user.id
        self.is_real_user = not (user.is_staff or user.is_superuser)

        # Join statistics broadcast group
        await self.channel_layer.group_add(self.STATS_GROUP, self.channel_name)
        await self.accept()

        # Add real user to online tracking + start heartbeat
        if self.is_real_user:
            await self.add_online_connection(self.user_id)
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Send current statistics to the connecting client
        stats = await self.get_stats()
        await self.send_json(stats)

        # Broadcast updated statistics to all connected clients
        await self.channel_layer.group_send(
            self.STATS_GROUP,
            {
                "type": "stats_update",
                "stats": stats,
            },
        )

    async def disconnect(self, close_code):
        """
        Handle WebSocket disconnection.

        Removes the user from the online set, leaves the broadcast group,
        and broadcasts updated statistics.

        Args:
            close_code: WebSocket close code
        """
        # Stop heartbeat first to avoid updating after disconnect.
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
            finally:
                self.heartbeat_task = None

        # Remove real user from online tracking
        if self.is_real_user:
            await self.remove_online_connection(self.user_id)

        # Leave statistics broadcast group
        await self.channel_layer.group_discard(self.STATS_GROUP, self.channel_name)

        # Broadcast updated statistics to remaining clients
        stats = await self.get_stats()
        await self.channel_layer.group_send(
            self.STATS_GROUP,
            {
                "type": "stats_update",
                "stats": stats,
            },
        )

    async def stats_update(self, event):
        """
        Handle statistics update broadcast from channel layer.

        Args:
            event: Event dict containing "stats" key with statistics data
        """
        await self.send_json(event["stats"])

    # Redis Operations (synchronous, thread-safe)
    # --------------------------------------------

    def _get_redis(self):
        """
        Get Redis connection for atomic operations.

        Returns:
            Redis connection instance
        """
        return get_redis_connection("default")

    def _touch_online_user_sync(self, user_id: int, now_ts: float) -> None:
        """
        Upsert user's last-seen timestamp in the online users ZSET.

        Also refreshes the per-user connection counter TTL so long-lived sockets
        don't lose their "online" marker due to key expiration.

        Args:
            user_id: User ID to upsert
            now_ts: Current time (epoch seconds)
        """
        redis = self._get_redis()
        count_key = f"{self.ONLINE_USER_CONN_COUNT_KEY_PREFIX}{int(user_id)}"
        redis.zadd(self.ONLINE_USERS_KEY, {int(user_id): float(now_ts)})
        # Best-effort key expiration so a completely idle key is eventually removed.
        redis.expire(self.ONLINE_USERS_KEY, self.ONLINE_USERS_TTL * 2)
        redis.expire(count_key, self.ONLINE_USERS_TTL * 2)

    def _add_online_connection_sync(self, user_id: int, now_ts: float) -> None:
        """
        Increment per-user active connection count and mark user as online.

        This prevents under-counting when a single user opens multiple tabs.
        """
        redis = self._get_redis()
        count_key = f"{self.ONLINE_USER_CONN_COUNT_KEY_PREFIX}{int(user_id)}"
        pipe = redis.pipeline()
        pipe.incr(count_key)
        pipe.expire(count_key, self.ONLINE_USERS_TTL * 2)
        pipe.zadd(self.ONLINE_USERS_KEY, {int(user_id): float(now_ts)})
        pipe.expire(self.ONLINE_USERS_KEY, self.ONLINE_USERS_TTL * 2)
        pipe.execute()

        cache.delete(self.ONLINE_COUNT_CACHE_KEY)

    def _remove_online_connection_sync(self, user_id: int) -> int:
        """
        Decrement per-user active connection count and remove user when it hits 0.

        Returns:
            Remaining active connections for the user (best-effort).
        """
        redis = self._get_redis()
        count_key = f"{self.ONLINE_USER_CONN_COUNT_KEY_PREFIX}{int(user_id)}"

        # Atomic decrement + conditional ZREM (multiple tabs support).
        script = """
        local count_key = KEYS[1]
        local zset_key = KEYS[2]
        local user_id = ARGV[1]
        local ttl = tonumber(ARGV[2])

        local current = redis.call('GET', count_key)
        if not current then
          redis.call('ZREM', zset_key, user_id)
          return 0
        end
        current = tonumber(current)
        if current <= 1 then
          redis.call('DEL', count_key)
          redis.call('ZREM', zset_key, user_id)
          return 0
        end

        local new_count = redis.call('DECR', count_key)
        redis.call('EXPIRE', count_key, ttl)
        return new_count
        """

        remaining = int(
            redis.eval(
                script,
                2,
                count_key,
                self.ONLINE_USERS_KEY,
                str(int(user_id)),
                str(int(self.ONLINE_USERS_TTL * 2)),
            )
            or 0
        )

        cache.delete(self.ONLINE_COUNT_CACHE_KEY)
        return remaining

    def _cleanup_expired_users_sync(self, now_ts: float) -> int:
        """
        Remove entries whose last-seen is older than the TTL window.

        Returns:
            Number of removed entries (best-effort)
        """
        redis = self._get_redis()
        cutoff = float(now_ts) - float(self.ONLINE_USERS_TTL)
        try:
            return int(redis.zremrangebyscore(self.ONLINE_USERS_KEY, "-inf", cutoff) or 0)
        except RedisError as exc:
            # Expected infra failure: Redis may be temporarily unavailable; keep the WS consumer alive.
            logger.warning("Online stats Redis cleanup failed; skipping (cutoff=%s): %s", cutoff, exc)
            return 0

    def _get_online_count_sync(self) -> int:
        """
        Get current online user count with short-lived cache.

        Uses a 5-second cache to reduce Redis read frequency during
        high-concurrency scenarios (e.g., multiple users connecting simultaneously).

        Returns:
            Number of active users in the online window
        """
        # Check cache first to avoid repeated Redis reads
        cached_count = cache.get(self.ONLINE_COUNT_CACHE_KEY)
        if cached_count is not None:
            return int(cached_count)

        # Cache miss - read from Redis and cache the result
        now_ts = time.time()
        self._cleanup_expired_users_sync(now_ts)
        redis = self._get_redis()
        count = int(redis.zcard(self.ONLINE_USERS_KEY) or 0)
        cache.set(self.ONLINE_COUNT_CACHE_KEY, count, timeout=self.ONLINE_COUNT_CACHE_TTL)

        return count

    # Async Wrappers
    # --------------

    async def touch_online_user(self, user_id: int):
        """Async wrapper: upsert user's last-seen timestamp."""
        await sync_to_async(self._touch_online_user_sync, thread_sensitive=True)(user_id, time.time())

    async def add_online_connection(self, user_id: int):
        """Async wrapper: increment per-user connection count and mark online."""
        await sync_to_async(self._add_online_connection_sync, thread_sensitive=True)(user_id, time.time())

    async def remove_online_connection(self, user_id: int):
        """Async wrapper: decrement per-user connection count and remove when 0."""
        await sync_to_async(self._remove_online_connection_sync, thread_sensitive=True)(user_id)

    async def _heartbeat_loop(self) -> None:
        """
        Periodically refresh last-seen while the socket is connected.
        """
        interval = max(30, min(self.ONLINE_USERS_HEARTBEAT_INTERVAL, self.ONLINE_USERS_TTL // 2))
        while True:
            try:
                await asyncio.sleep(interval)
                if not self.is_real_user or not self.user_id:
                    return
                await self.touch_online_user(self.user_id)
            except asyncio.CancelledError:
                return
            except RedisError as exc:
                # Expected infra failure: keep retrying in the next tick.
                logger.debug("Online stats heartbeat Redis error; will retry: %s", exc)
                continue
            except Exception:
                # Unexpected failure: log full traceback but keep the socket alive.
                logger.exception("Unexpected error in online stats heartbeat loop")
                continue

    async def get_stats(self):
        """
        Get current user statistics.

        Returns:
            Dict with "online_count" and "total_count" keys
        """
        # Keep stats best-effort: avoid killing the WS connection on Redis/DB issues.
        try:
            online_count = await sync_to_async(self._get_online_count_sync, thread_sensitive=True)()
        except RedisError as exc:
            logger.warning("Online stats Redis read failed; reporting 0 online users: %s", exc)
            online_count = 0
        except Exception:
            logger.exception("Unexpected error while getting online count; reporting 0 online users")
            online_count = 0

        try:
            total_count = await self.get_total_users()
        except DatabaseError as exc:
            logger.warning("Online stats DB read failed; reporting 0 total users: %s", exc)
            total_count = 0
        except Exception:
            logger.exception("Unexpected error while getting total users; reporting 0 total users")
            total_count = 0

        return {
            "online_count": online_count,
            "total_count": total_count,
        }

    @database_sync_to_async
    def get_total_users(self):
        """
        Get total number of real users (excluding staff/superusers) with cache.

        Uses a 5-minute cache to minimize expensive database COUNT queries.
        This significantly reduces DB load during high-frequency connect/disconnect events.

        Returns:
            Count of non-staff, non-superuser accounts
        """
        # Check cache first to avoid expensive database COUNT
        cached_total = cache.get(self.TOTAL_COUNT_CACHE_KEY)
        if cached_total is not None:
            return int(cached_total)

        # Cache miss - query database and cache the result
        try:
            total = User.objects.filter(is_staff=False, is_superuser=False).count()
        except DatabaseError as exc:
            # Expected infra failure: DB might be temporarily unavailable.
            logger.warning("Failed to COUNT total users; returning 0: %s", exc)
            return 0

        cache.set(self.TOTAL_COUNT_CACHE_KEY, total, timeout=self.TOTAL_COUNT_CACHE_TTL)

        return total


class WorldChatConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for the world chat channel.

    Features:
    - Single shared channel group (world)
    - Server-side message validation and rate limiting
    - Redis-backed rolling history for new connections
    """

    CHANNEL = "world"
    GROUP_NAME = "chat_world"

    HISTORY_KEY = "chat:world:history"
    NEXT_ID_KEY = "chat:world:next_id"

    HISTORY_LIMIT = 200
    HISTORY_ON_CONNECT = 60
    HISTORY_MESSAGE_TTL_SECONDS = 15 * 60  # keep messages for 15 minutes

    MESSAGE_MAX_LEN = 200
    RATE_LIMIT_WINDOW_SECONDS = 8
    RATE_LIMIT_MAX_MESSAGES = 6

    # 世界频道发言需要消耗的道具
    TRUMPET_ITEM_KEY = "small_trumpet"

    user_id: int | None = None
    display_name: str = ""

    _re_control_chars = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            # 审计日志：记录认证失败的连接尝试
            logger.warning(
                "WebSocket authentication failed for WorldChatConsumer",
                extra={
                    "path": self.scope.get("path"),
                    "client": self.scope.get("client"),
                }
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
        # Defensive boundary: never let exceptions bubble up and kill the WS connection.
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

            # 检查并扣除小喇叭道具
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
            # Expected input/serialization errors: log and keep the socket alive.
            logger.info("World chat message rejected due to invalid payload: %s", exc)
            await self.send_json({"type": "error", "code": "invalid_payload", "message": "消息格式错误"})
        except Exception:
            # Unexpected errors: record full stack for debugging, but do not drop the WS connection.
            logger.exception("Unexpected error handling world chat message")
            await self.send_json({"type": "error", "code": "server_error", "message": "服务器错误，请稍后重试"})

    async def chat_message(self, event):
        # 验证 payload 结构，只转发预期的字段
        payload = event.get("payload", {})
        safe_payload = {
            "type": payload.get("type"),
            "message": payload.get("message"),
            "sender": payload.get("sender"),
            "timestamp": payload.get("timestamp"),
            "is_trumpet": payload.get("is_trumpet"),
        }
        # 移除 None 值
        safe_payload = {k: v for k, v in safe_payload.items() if v is not None}
        await self.send_json(safe_payload)

    def _normalize_text(self, text: str) -> str:
        """
        清理和规范化聊天消息文本。

        安全措施：
        1. 转义HTML特殊字符，防止XSS攻击
        2. 移除控制字符
        3. 规范化换行符
        4. 限制空行数量

        Args:
            text: 原始消息文本

        Returns:
            清理后的安全文本
        """
        # 首先转义HTML特殊字符（防止XSS攻击）
        text = html.escape(text)

        # 移除控制字符，规范化换行符，并修剪空格
        cleaned = self._re_control_chars.sub("", text)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        # 限制过多的空行（最多3个连续换行）
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
                # Expected formatting issues: fall back to user names.
                logger.debug("Invalid manor display_name for world chat user_id=%s: %s", user_id, exc)
                pass

        return user.get_full_name() or user.username or "玩家"

    @database_sync_to_async
    def _consume_trumpet(self) -> tuple[bool, str]:
        """
        检查并扣除小喇叭道具。

        Returns:
            (success, error_message): 成功返回 (True, "")，失败返回 (False, 错误信息)
        """
        # Lazy import to avoid pulling Django models/services into ASGI startup unless needed.
        from gameplay.models import Manor
        from gameplay.services.inventory import consume_inventory_item, get_item_quantity

        try:
            manor = Manor.objects.get(user_id=self.user_id)
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
            # Expected business/input error: invalid item key/quantity should not crash WS.
            logger.warning("Failed to consume trumpet due to invalid input: %s", exc)
            return False, "扣除小喇叭失败，请稍后重试"
        except DatabaseError:
            # Infra error: log full traceback for debugging but keep user experience stable.
            logger.exception("Database error when consuming trumpet for user_id=%s", self.user_id)
            return False, "扣除小喇叭失败，请稍后重试"
        except Exception:
            logger.exception("Unexpected error when consuming trumpet for user_id=%s", self.user_id)
            return False, "扣除小喇叭失败，请稍后重试"

        return True, ""

    def _get_history_sync(self) -> list[dict]:
        redis = self._get_redis()
        cutoff_ms = int((time.time() - float(self.HISTORY_MESSAGE_TTL_SECONDS)) * 1000)
        try:
            raw_items = redis.lrange(self.HISTORY_KEY, 0, max(0, self.HISTORY_ON_CONNECT - 1))
        except RedisError as exc:
            # Expected infra failure: history is best-effort.
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
                # Expected data issues: history entries may be corrupted/partial; skip safely.
                logger.debug("Skipping malformed world chat history entry: %s", exc)
                continue
            except Exception:
                logger.exception("Unexpected error while parsing world chat history entry")
                continue

        # Best-effort cleanup to avoid returning stale tail entries after long idle periods.
        try:
            self._trim_history_by_time_sync(cutoff_ms)
        except RedisError as exc:
            logger.debug("World chat history trim skipped due to Redis error: %s", exc)
        except Exception:
            logger.exception("Unexpected error while trimming world chat history")
            pass
        return messages

    async def _get_history(self) -> list[dict]:
        return await sync_to_async(self._get_history_sync, thread_sensitive=True)()

    def _trim_history_by_time_sync(self, cutoff_ms: int) -> None:
        """
        Remove history entries older than cutoff_ms from the list tail.

        The list is stored as LPUSH(newest)->head, so the oldest entries are at the tail.
        """
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
                # Corrupted tail entry: drop it to keep the list healthy.
                logger.debug("Dropping corrupted world chat history tail entry: %s", exc)
                pass
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

        cutoff_ms = int((time.time() - float(self.HISTORY_MESSAGE_TTL_SECONDS)) * 1000)
        self._trim_history_by_time_sync(cutoff_ms)

    async def _append_history(self, message: dict) -> None:
        try:
            await sync_to_async(self._append_history_sync, thread_sensitive=True)(message)
        except RedisError as exc:
            # Best-effort: chat should still work even if history write fails.
            logger.debug("World chat history write skipped due to Redis error: %s", exc)
            return
        except Exception:
            logger.exception("Unexpected error while appending world chat history")
            return

    def _rate_limit_sync(self, user_id: int | None) -> tuple[bool, int | None]:
        if not user_id:
            return False, 3

        redis = self._get_redis()
        now_bucket = int(time.time() // self.RATE_LIMIT_WINDOW_SECONDS)
        key = f"chat:world:rate:{int(user_id)}:{now_bucket}"

        try:
            count = int(redis.incr(key) or 0)
            if count == 1:
                redis.expire(key, self.RATE_LIMIT_WINDOW_SECONDS + 2)
        except RedisError as exc:
            # If Redis has issues, fall back to allowing the message (avoid false negatives).
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
            return int(time.time() * 1000)

    async def _build_message(self, text: str) -> dict:
        msg_id = await sync_to_async(self._next_id_sync, thread_sensitive=True)()
        ts_ms = int(time.time() * 1000)
        return {
            "type": "message",
            "channel": self.CHANNEL,
            "id": msg_id,
            "ts": ts_ms,
            "sender": {"id": self.user_id, "name": self.display_name},
            "text": text,
        }
