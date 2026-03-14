from __future__ import annotations

from pathlib import Path

import yaml

ITEM_TEMPLATES_PATH = Path(__file__).resolve().parent.parent / "data" / "item_templates.yaml"
FORGE_EQUIPMENT_PATH = Path(__file__).resolve().parent.parent / "data" / "forge_equipment.yaml"
SUPPORTED_EQUIPMENT_STATS = {"hp", "force", "intellect", "defense", "agility", "luck", "troop_capacity"}


def _load_item_templates() -> dict[str, dict]:
    payload = yaml.safe_load(ITEM_TEMPLATES_PATH.read_text(encoding="utf-8"))
    return {row["key"]: row for row in payload["items"]}


def _load_forge_equipment() -> dict[str, dict]:
    payload = yaml.safe_load(FORGE_EQUIPMENT_PATH.read_text(encoding="utf-8"))
    return payload["equipment"]


def _equipment_score(effect_payload: dict) -> float:
    return (
        float(effect_payload.get("hp", 0)) / 18.0
        + float(effect_payload.get("defense", 0)) * 3.0
        + float(effect_payload.get("force", 0))
        + float(effect_payload.get("intellect", 0))
        + float(effect_payload.get("agility", 0)) * 0.8
        + float(effect_payload.get("luck", 0)) * 0.6
        + float(effect_payload.get("troop_capacity", 0)) * 0.25
    )


def test_equipment_payload_uses_supported_stats_only():
    items = _load_item_templates()

    invalid_stats_by_item: dict[str, list[str]] = {}
    for key, item in items.items():
        effect_type = str(item.get("effect_type") or "")
        if not effect_type.startswith("equip_"):
            continue

        payload = item.get("effect_payload") or {}
        invalid_stats = [
            stat
            for stat, value in payload.items()
            if isinstance(value, (int, float)) and stat not in SUPPORTED_EQUIPMENT_STATS
        ]
        if invalid_stats:
            invalid_stats_by_item[key] = sorted(invalid_stats)

    assert invalid_stats_by_item == {}


def test_forgeable_equipment_progresses_with_recipe_tier():
    items = _load_item_templates()
    forge_equipment = _load_forge_equipment()
    forgeable_lines = {
        "helmet": ["equip_bumao", "equip_niupimao", "equip_tieyekui", "equip_yulindin", "equip_baihongkui"],
        "armor": ["equip_bupao", "equip_shengpijia", "equip_housipao", "equip_shapijia"],
        "shoes": ["equip_buxie", "equip_yangpixue", "equip_gangpianxue", "equip_yanyuxue"],
        "sword": ["equip_duanjian", "equip_changjian", "equip_qingmangjian", "equip_duanmajian"],
        "dao": ["equip_duandao", "equip_dakandao", "equip_tongchangdao", "equip_jingtiedao"],
        "spear": ["equip_changqiang", "equip_baoweiqiang", "equip_hutoumao", "equip_pansheqiang"],
        "bow": ["equip_changgong", "equip_fanqugong", "equip_tietaigong", "equip_shenbigong"],
        "whip": [
            "equip_changbian",
            "equip_niupibian",
            "equip_jicibian",
            "equip_jiulonggangbian",
            "equip_mingshejiebian",
        ],
    }

    for line_name, keys in forgeable_lines.items():
        required_forging_levels = [int(forge_equipment[key]["required_forging"]) for key in keys]
        assert required_forging_levels == sorted(required_forging_levels), line_name

        scores = [_equipment_score(items[key]["effect_payload"]) for key in keys]
        assert scores == sorted(scores), f"{line_name}: {scores}"
        assert len(set(scores)) == len(scores), f"{line_name}: {scores}"


def test_forgeable_weapon_lines_have_distinct_secondary_roles():
    items = _load_item_templates()

    sword = items["equip_duanmajian"]["effect_payload"]
    dao = items["equip_jingtiedao"]["effect_payload"]
    spear = items["equip_pansheqiang"]["effect_payload"]
    bow = items["equip_shenbigong"]["effect_payload"]
    whip = items["equip_mingshejiebian"]["effect_payload"]

    assert sword.get("agility", 0) > 0
    assert sword.get("hp", 0) == 0
    assert sword.get("troop_capacity", 0) == 0

    assert dao.get("hp", 0) > 0
    assert dao.get("troop_capacity", 0) == 0

    assert spear.get("troop_capacity", 0) > 0
    assert spear.get("agility", 0) > 0

    assert bow.get("agility", 0) > 0
    assert bow.get("intellect", 0) > 0

    assert whip.get("luck", 0) > 0
    assert whip.get("agility", 0) > 0
