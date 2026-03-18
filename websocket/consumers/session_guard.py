from __future__ import annotations

import logging
import time

from channels.db import database_sync_to_async

from core.middleware.single_session import SessionValidationUnavailable, is_single_session_request_valid
from core.utils.degradation import SESSION_SYNC_FAILURE, record_degradation

logger = logging.getLogger(__name__)


class WebSocketSessionValidationUnavailable(RuntimeError):
    """Raised when websocket session validation cannot reach authoritative state."""


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
        except Exception as exc:
            raise WebSocketSessionValidationUnavailable("session existence check unavailable") from exc

    try:
        session_user_id = session.get("_auth_user_id")
    except Exception as exc:
        raise WebSocketSessionValidationUnavailable("session payload check unavailable") from exc

    if str(session_user_id) != str(user.id):
        return False

    try:
        return is_single_session_request_valid(int(user.id), str(current_session_key))
    except SessionValidationUnavailable as exc:
        raise WebSocketSessionValidationUnavailable("single-session validation unavailable") from exc


class SingleSessionWebSocketMixin:
    SESSION_VALIDATION_CACHE_SECONDS = 5.0
    _single_session_valid_until: float = 0.0
    _single_session_checked_by_dispatch: bool = False

    def _session_validation_now(self) -> float:
        return time.monotonic()

    def _has_recent_session_validation(self) -> bool:
        return self._session_validation_now() < float(getattr(self, "_single_session_valid_until", 0.0) or 0.0)

    def _remember_session_validation(self) -> None:
        self._single_session_valid_until = self._session_validation_now() + float(self.SESSION_VALIDATION_CACHE_SECONDS)

    async def dispatch(self, message):
        if not await self._guard_single_session(message):
            return
        self._single_session_checked_by_dispatch = True
        try:
            await super().dispatch(message)
        finally:
            self._single_session_checked_by_dispatch = False

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
        if not force and self._has_recent_session_validation():
            return True

        try:
            is_valid = await database_sync_to_async(is_websocket_session_valid, thread_sensitive=True)(self.scope)  # type: ignore[attr-defined]
        except WebSocketSessionValidationUnavailable:
            record_degradation(
                SESSION_SYNC_FAILURE,
                component="single_session_websocket",
                detail="websocket session validation unavailable, keeping connection",
                user_id=getattr(user, "id", None),
            )
            logger.warning(
                "WebSocket session validation unavailable; keeping connection: consumer=%s user_id=%s path=%s",
                self.__class__.__name__,
                getattr(user, "id", None),
                self.scope.get("path"),  # type: ignore[attr-defined]
                exc_info=True,
            )
            self._remember_session_validation()
            return True

        if is_valid:
            self._remember_session_validation()
        return is_valid
