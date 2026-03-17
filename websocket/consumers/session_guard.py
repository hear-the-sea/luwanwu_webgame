from __future__ import annotations

import logging

from channels.db import database_sync_to_async

from core.middleware.single_session import is_single_session_request_valid

logger = logging.getLogger(__name__)


def is_websocket_session_valid(scope: dict) -> bool:
    user = scope.get("user")
    if not user or not getattr(user, "is_authenticated", False):
        return False

    session = scope.get("session")
    if session is None:
        logger.warning("WebSocket session missing for authenticated user: user_id=%s", getattr(user, "id", None))
        return False

    current_session_key = getattr(session, "session_key", None)
    if not current_session_key:
        return False

    exists = getattr(session, "exists", None)
    if callable(exists):
        try:
            if not exists(current_session_key):
                return False
        except Exception:
            logger.warning(
                "WebSocket session existence check failed; rejecting connection: user_id=%s",
                getattr(user, "id", None),
                exc_info=True,
            )
            return False

    try:
        session_user_id = session.get("_auth_user_id")
    except Exception:
        logger.warning(
            "WebSocket session payload check failed; rejecting connection: user_id=%s",
            getattr(user, "id", None),
            exc_info=True,
        )
        return False

    if str(session_user_id) != str(user.id):
        return False

    try:
        return is_single_session_request_valid(int(user.id), str(current_session_key))
    except Exception:
        logger.warning(
            "WebSocket single-session validation failed; rejecting connection: user_id=%s",
            getattr(user, "id", None),
            exc_info=True,
        )
        return False


class SingleSessionWebSocketMixin:
    async def dispatch(self, message):
        if not await self._guard_single_session(message):
            return
        await super().dispatch(message)

    async def _guard_single_session(self, message: dict) -> bool:
        message_type = str(message.get("type", ""))
        if message_type == "websocket.disconnect":
            return True

        is_valid = await self._ensure_valid_session(force=(message_type == "websocket.connect"))
        if is_valid:
            return True

        logger.info(
            "Closing stale WebSocket session: consumer=%s user_id=%s path=%s message_type=%s",
            self.__class__.__name__,
            getattr(self.scope.get("user"), "id", None),  # type: ignore[attr-defined]
            self.scope.get("path"),  # type: ignore[attr-defined]
            message_type,
        )
        await self.close()  # type: ignore[attr-defined]
        return False

    async def _ensure_valid_session(self, *, force: bool = False) -> bool:
        user = self.scope.get("user")  # type: ignore[attr-defined]
        if not user or not getattr(user, "is_authenticated", False):
            return False

        return await database_sync_to_async(is_websocket_session_valid, thread_sensitive=True)(self.scope)  # type: ignore[attr-defined]
