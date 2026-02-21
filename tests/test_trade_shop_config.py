from __future__ import annotations

import textwrap

import pytest

from trade.services import shop_config


@pytest.mark.django_db
def test_load_shop_config_normalizes_invalid_entries(tmp_path, monkeypatch):
    cfg_path = tmp_path / "shop_items.yaml"
    cfg_path.write_text(
        textwrap.dedent(
            """
            items:
              - item_key: item_a
                price: -5
                stock: -3
                daily_refresh: "true"
              - item_key: item_b
                price: foo
                stock: bar
                daily_refresh: "false"
              - item_key: ""
                stock: 1
              - bad_entry
            """
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(shop_config, "SHOP_CONFIG_PATH", cfg_path)

    configs = shop_config.load_shop_config()
    assert [c.item_key for c in configs] == ["item_a", "item_b"]

    assert configs[0].price is None
    assert configs[0].stock == 0
    assert configs[0].daily_refresh is True

    assert configs[1].price is None
    assert configs[1].stock == 0
    assert configs[1].daily_refresh is False
