from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django_redis.exceptions import ConnectionInterrupted

from gameplay.services.utils import notifications as notification_utils
from gameplay.services.utils.notifications import notify_user


def test_notify_user_returns_false_on_connection_interrupted(monkeypatch):
    logger = MagicMock()
    monkeypatch.setattr(notification_utils, "logger", logger)
    monkeypatch.setattr(notification_utils, "async_to_sync", lambda fn: fn)
    monkeypatch.setattr(
        notification_utils,
        "get_channel_layer",
        lambda: MagicMock(group_send=lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionInterrupted("down"))),
    )

    assert notify_user(1, {"kind": "system", "title": "t"}) is False
    logger.warning.assert_called_once()


def test_notify_user_returns_false_on_unexpected_runtime_error(monkeypatch):
    logger = MagicMock()
    monkeypatch.setattr(notification_utils, "logger", logger)
    monkeypatch.setattr(notification_utils, "async_to_sync", lambda fn: fn)
    monkeypatch.setattr(
        notification_utils,
        "get_channel_layer",
        lambda: MagicMock(group_send=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad payload"))),
    )

    with pytest.raises(RuntimeError, match="bad payload"):
        notify_user(1, {"kind": "system", "title": "t"})

    logger.exception.assert_called_once()
