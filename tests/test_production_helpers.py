import pytest

from gameplay.views.production_helpers import (
    annotate_blueprint_synthesis_options,
    build_categories_with_all,
    get_filtered_equipment_options,
    normalize_forge_category,
    resolve_decompose_category,
    sort_equipment_options,
)


@pytest.mark.parametrize(
    ("raw_category", "expected"),
    [
        ("all", "all"),
        ("helmet", "helmet"),
        ("sword", "weapon"),
        ("invalid", "all"),
        (None, "all"),
    ],
)
def test_normalize_forge_category_merges_and_validates(raw_category, expected):
    assert (
        normalize_forge_category(
            raw_category,
            active_categories={"helmet": "头盔", "weapon": "武器", "device": "器械"},
            weapon_categories={"sword", "dao", "spear"},
        )
        == expected
    )


def test_sort_equipment_options_prioritizes_forgeable_then_requirement():
    sorted_items = sort_equipment_options(
        [
            {"key": "locked_r9", "is_unlocked": False, "can_afford": False, "required_forging": 9},
            {"key": "forgeable_r1", "is_unlocked": True, "can_afford": True, "required_forging": 1},
            {"key": "forgeable_r7", "is_unlocked": True, "can_afford": True, "required_forging": 7},
            {"key": "unlocked_not_affordable_r8", "is_unlocked": True, "can_afford": False, "required_forging": 8},
        ]
    )

    assert [item["key"] for item in sorted_items] == [
        "forgeable_r7",
        "forgeable_r1",
        "locked_r9",
        "unlocked_not_affordable_r8",
    ]


def test_get_filtered_equipment_options_uses_weapon_bucket_and_sorting():
    calls = []

    def _get_equipment_options(_manor, category=None):
        calls.append(category)
        options = [
            {"key": "helmet_a", "category": "helmet", "is_unlocked": True, "can_afford": True, "required_forging": 1},
            {"key": "sword_a", "category": "sword", "is_unlocked": True, "can_afford": True, "required_forging": 3},
            {"key": "dao_a", "category": "dao", "is_unlocked": True, "can_afford": True, "required_forging": 5},
        ]
        if category is None:
            return options
        return [item for item in options if item["category"] == category]

    weapon_items = get_filtered_equipment_options(
        manor=object(),
        current_category="weapon",
        weapon_categories={"sword", "dao", "spear"},
        get_equipment_options=_get_equipment_options,
    )
    helmet_items = get_filtered_equipment_options(
        manor=object(),
        current_category="helmet",
        weapon_categories={"sword", "dao", "spear"},
        get_equipment_options=_get_equipment_options,
    )

    assert [item["key"] for item in weapon_items] == ["dao_a", "sword_a"]
    assert [item["key"] for item in helmet_items] == ["helmet_a"]
    assert calls == [None, "helmet"]


def test_annotate_blueprint_synthesis_options_enriches_and_filters():
    recipes = [
        {"result_key": "sword_1", "result_effect_type": "equip_weapon", "name": "Sword"},
        {"result_key": "device_1", "result_effect_type": "equip_device", "name": "Device"},
    ]

    def _infer_equipment_category(result_key, _effect_type):
        if result_key.startswith("sword"):
            return "sword"
        return "device"

    def _to_decompose_category(category):
        return "weapon" if category == "sword" else category

    annotated = annotate_blueprint_synthesis_options(
        recipes,
        active_categories={"weapon": "武器", "device": "器械"},
        current_category="device",
        infer_equipment_category=_infer_equipment_category,
        to_decompose_category=_to_decompose_category,
    )

    assert annotated == [
        {
            "result_key": "device_1",
            "result_effect_type": "equip_device",
            "name": "Device",
            "result_category": "device",
            "result_category_name": "器械",
        }
    ]


def test_build_categories_with_all_and_resolve_decompose_category():
    assert build_categories_with_all({"helmet": "头盔"}) == {"all": "全部", "helmet": "头盔"}
    assert resolve_decompose_category("all") is None
    assert resolve_decompose_category("helmet") == "helmet"
