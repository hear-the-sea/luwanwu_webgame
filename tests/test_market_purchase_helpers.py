from __future__ import annotations

from types import SimpleNamespace

from trade.services import market_purchase_helpers


def test_grant_listing_item_to_buyer_locked_delegates_to_inventory_platform():
    calls: list[tuple[object, str, int]] = []
    buyer = SimpleNamespace(id=11)
    item_template = SimpleNamespace(key="equip_qingfeng")

    market_purchase_helpers.grant_listing_item_to_buyer_locked(
        buyer_locked=buyer,
        item_template=item_template,
        quantity=2,
        grant_item_locked=lambda locked_manor, *, item_key, quantity: calls.append((locked_manor, item_key, quantity)),
    )

    assert calls == [(buyer, "equip_qingfeng", 2)]
