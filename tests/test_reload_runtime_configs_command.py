from __future__ import annotations

from io import StringIO

from django.core.management import call_command

from gameplay.services.runtime_configs import format_runtime_config_summary


def test_format_runtime_config_summary_orders_known_keys():
    summary = {
        "shop_items": 3,
        "auction_items": 2,
        "warehouse_techs": 1,
        "forge_equipment": 4,
    }

    rendered = format_runtime_config_summary(summary)

    assert rendered == "shop_items=3, auction_items=2, warehouse_techs=1, forge_equipment=4"


def test_reload_runtime_configs_command_renders_summary(monkeypatch):
    out = StringIO()
    monkeypatch.setattr(
        "gameplay.management.commands.reload_runtime_configs.reload_runtime_configs",
        lambda: {
            "shop_items": 3,
            "auction_items": 2,
            "warehouse_techs": 1,
            "forge_equipment": 4,
            "guest_growth_rarities": 7,
        },
    )

    call_command("reload_runtime_configs", stdout=out, verbosity=0)
    rendered = out.getvalue()

    assert "[OK] 运行期配置已刷新:" in rendered
    assert "shop_items=3" in rendered
    assert "forge_equipment=4" in rendered
    assert "guest_growth_rarities=7" in rendered
