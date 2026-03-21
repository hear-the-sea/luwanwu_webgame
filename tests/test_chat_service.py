from __future__ import annotations

from types import SimpleNamespace

from core.exceptions import InsufficientStockError
from gameplay.services import chat as chat_service


def test_consume_trumpet_returns_no_stock_message(monkeypatch):
    monkeypatch.setattr(chat_service, "_get_manor_for_user", lambda _user_id: SimpleNamespace(id=1))
    monkeypatch.setattr(
        chat_service,
        "consume_inventory_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(InsufficientStockError("小喇叭", 1, 0)),
    )

    assert chat_service.consume_trumpet(1) == (False, "小喇叭不足，无法在世界频道发言")


def test_consume_trumpet_treats_value_error_as_unexpected_failure(monkeypatch):
    monkeypatch.setattr(chat_service, "_get_manor_for_user", lambda _user_id: SimpleNamespace(id=1))
    monkeypatch.setattr(
        chat_service,
        "consume_inventory_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("legacy invalid input")),
    )

    assert chat_service.consume_trumpet(1) == (False, "扣除小喇叭失败，请稍后重试")
