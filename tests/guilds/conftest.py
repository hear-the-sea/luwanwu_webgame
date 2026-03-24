from __future__ import annotations

import pytest

from gameplay.models import InventoryItem, ItemTemplate


@pytest.fixture
def gold_bar_template(db):
    template, _ = ItemTemplate.objects.get_or_create(
        key="gold_bar",
        defaults={
            "name": "金条",
            "effect_type": "none",
        },
    )
    return template


@pytest.fixture
def user_with_gold_bars(django_user_model, gold_bar_template):
    user = django_user_model.objects.create_user(username="guild_test_user", password="pass12345")
    from gameplay.services.manor.core import ensure_manor

    manor = ensure_manor(user)
    InventoryItem.objects.create(manor=manor, template=gold_bar_template, quantity=10, storage_location="warehouse")
    return user


@pytest.fixture
def second_user(django_user_model):
    user = django_user_model.objects.create_user(username="guild_test_user2", password="pass12345")
    from gameplay.services.manor.core import ensure_manor

    ensure_manor(user)
    return user
