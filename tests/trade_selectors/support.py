from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from gameplay.services.manor.core import ensure_manor


@dataclass
class DummySellable:
    inventory_item: object
    sell_price: int


def create_manor(django_user_model, *, username: str):
    user = django_user_model.objects.create_user(username=username, password="pass12345")
    return ensure_manor(user)


def make_sellable_items(count: int):
    return [
        DummySellable(
            inventory_item=SimpleNamespace(template=SimpleNamespace(effect_type="tool"), quantity=index + 1),
            sell_price=index + 1,
        )
        for index in range(count)
    ]
