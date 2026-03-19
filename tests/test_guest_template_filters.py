from __future__ import annotations

from types import SimpleNamespace

from guests.models import GuestRarity
from guests.templatetags import guest_extras


def test_rarity_filters_normalize_known_values():
    assert guest_extras.rarity_class(GuestRarity.GREEN) == "rarity-green"
    assert guest_extras.rarity_class("unknown") == "rarity-default"
    assert guest_extras.rarity_label(GuestRarity.ORANGE) == "橙"
    assert guest_extras.rarity_label("unknown") == "未知稀有度"


def test_gear_summary_combines_description_stats_and_set_bonus():
    template = SimpleNamespace(
        description="佩剑",
        attack_bonus=12,
        defense_bonus=5,
        extra_stats={"luck": 3},
        set_key="青龙",
        set_bonus={"pieces": 2, "bonus": {"attack": 8}},
    )

    assert guest_extras.gear_summary(template) == ("佩剑；攻击+12、防御+5、运势+3；青龙（2件）：攻击+8")


def test_gear_tooltip_renders_lines_for_stats_and_set_members():
    template = SimpleNamespace(
        description="佩剑",
        attack_bonus=12,
        defense_bonus=0,
        extra_stats={"luck": 3},
        set_key="青龙",
    )
    set_map = {
        "青龙": {
            "description": "青龙套装",
            "members": [{"name": "青龙剑", "slot": "weapon"}],
            "bonus": {"attack": 8, "luck": 2},
        }
    }

    html = str(guest_extras.gear_tooltip(template, set_map))

    assert "佩剑" in html
    assert "攻击 +12" in html
    assert "运势 +3" in html
    assert "套装：青龙套装" in html
    assert "weapon·青龙剑" in html
    assert "套装属性：" in html
    assert "攻击+8" in html
    assert "运势+2" in html


def test_attribute_icons_renders_expected_icon_pack():
    html = str(guest_extras.attribute_icons(85))

    assert html.count("attr-crown") == 1
    assert html.count("attr-sun") == 1
    assert html.count("attr-moon") == 1
    assert html.count("attr-star") == 1
    assert guest_extras.attribute_icons(0) == ""
