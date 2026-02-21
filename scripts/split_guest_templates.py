#!/usr/bin/env python
"""Split guest_templates.yaml heroes into separate files by source/author.

This is a utility script for maintaining YAML-driven guest templates.

By default it assumes it is run from within the repo and will locate
`data/` relative to this file. You can override the location with
`--base-dir`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

_SOURCE_HEADER_MAP = {
    "gulong": "# 古龙作品门客",
    "liangyshen": "# 梁羽生作品门客",
    "wenruian": "# 温瑞安作品门客",
    "huangyi": "# 黄易作品门客",
    "suitang": "# 隋唐演义门客",
    "jinyong": "# 金庸作品门客",
    "base": "# 基础门客模板",
    "special": "# 特殊/隐藏BOSS门客",
}

_SOURCE_INDICATORS = [
    ("gulong", ["古龙", "古龙小说"]),
    ("liangyshen", ["梁羽生", "梁羽生小说"]),
    ("wenruian", ["温瑞安", "温瑞安小说"]),
    ("huangyi", ["黄易", "黄易小说"]),
    ("suitang", ["隋唐演义", "隋唐"]),
]

_WORKS_BY_SOURCE = {
    "gulong": [
        "多情剑客无情剑",
        "楚留香",
        "陆小凤",
        "绝代双骄",
        "萧十一郎",
        "三少爷的剑",
        "天涯明月刀",
        "边城浪子",
        "武林外史",
        "流星蝴蝶剑",
        "白玉老虎",
        "欢乐英雄",
        "七种武器",
        "大旗英雄传",
        "英雄无泪",
        "圆月弯刀",
        "浣花洗剑录",
        "大人物",
        "七杀手",
        "血鹦鹉",
        "碧血洗银枪",
        "飘香剑雨",
        "名剑风流",
        "大地飞鹰",
        "九月鹰飞",
    ],
    "liangyshen": [
        "七剑下天山",
        "白发魔女传",
        "萍踪侠影录",
        "冰川天女传",
        "云海玉弓缘",
        "江湖三女侠",
        "女帝奇英传",
        "大唐游侠传",
    ],
    "wenruian": ["四大名捕", "神州奇侠", "说英雄谁是英雄", "逆水寒", "布衣神相"],
    "huangyi": ["寻秦记", "大唐双龙传", "覆雨翻云", "破碎虚空"],
}


def _matches_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _detect_from_flavor(flavor: str) -> str | None:
    for source, keywords in _SOURCE_INDICATORS:
        if _matches_any(flavor, keywords):
            return source

    if any(work in flavor for work in ["天龙八部", "神雕侠侣", "笑傲江湖"]):
        return "jinyong"

    for source, works in _WORKS_BY_SOURCE.items():
        if _matches_any(flavor, works):
            return source

    return None


def detect_source(hero: dict) -> str:
    """Detect the source/author of a hero based on flavor text or key."""
    key = str(hero.get("key", "")).lower()
    flavor = str(hero.get("flavor", ""))

    if key.startswith("base_"):
        return "base"
    if key.startswith("special_hero_"):
        return "special"

    detected = _detect_from_flavor(flavor)
    if detected:
        return detected

    if "pubayi" in key:
        return "original"

    return "original"


def to_plain(value):
    """Convert ruamel types into plain dict/list for safe PyYAML dumping."""
    if isinstance(value, dict):
        return {key: to_plain(val) for key, val in value.items()}
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    return value


def _resolve_paths(base_dir: Path) -> tuple[Path, Path, Path]:
    data_dir = base_dir / "data"
    backup_file = data_dir / "guest_templates_full.yaml"
    input_file = backup_file if backup_file.exists() else data_dir / "guest_templates.yaml"
    output_dir = data_dir / "guests"
    output_dir.mkdir(exist_ok=True)
    return data_dir, input_file, output_dir


def _load_templates(input_file: Path) -> dict:
    try:
        from ruamel.yaml import YAML

        ryaml = YAML()
        ryaml.preserve_quotes = True
        with open(input_file, "r", encoding="utf-8") as f:
            return to_plain(ryaml.load(f))
    except ImportError:
        with open(input_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)


def _split_heroes_by_source(data: dict) -> dict[str, dict[str, list]]:
    heroes_by_source: dict[str, dict[str, list]] = {}
    heroes_data = data.get("heroes", {})

    for rarity, heroes in heroes_data.items():
        for hero in heroes:
            source = detect_source(hero)
            heroes_by_source.setdefault(source, {}).setdefault(rarity, []).append(hero)

    return heroes_by_source


def _write_source_hero_files(output_dir: Path, heroes_by_source: dict[str, dict[str, list]]) -> None:
    for source, heroes in heroes_by_source.items():
        output_file = output_dir / f"{source}.yaml"
        output_data = {"heroes": heroes}
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(_SOURCE_HEADER_MAP.get(source, "# 原创门客") + "\n\n")
            yaml.safe_dump(output_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        total = sum(len(hero_list) for hero_list in heroes.values())
        print(f"Created {output_file.name}: {total} heroes")


def _write_main_stub(data_dir: Path, data: dict) -> None:
    new_main_data = {key: value for key, value in data.items() if key != "heroes"}
    new_main_file = data_dir / "guest_templates_new.yaml"

    with open(new_main_file, "w", encoding="utf-8") as f:
        f.write("# 门客模板配置\n")
        f.write("# 门客英雄数据已拆分到 data/guests/ 目录下\n")
        f.write("# - gulong.yaml: 古龙作品\n")
        f.write("# - liangyshen.yaml: 梁羽生作品\n")
        f.write("# - wenruian.yaml: 温瑞安作品\n")
        f.write("# - huangyi.yaml: 黄易作品\n")
        f.write("# - suitang.yaml: 隋唐演义\n")
        f.write("# - base.yaml: 基础模板\n")
        f.write("# - original.yaml: 原创门客\n")
        f.write("# - special.yaml: 特殊/隐藏BOSS\n\n")
        yaml.safe_dump(new_main_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"Created {new_main_file.name}")


def main():
    parser = argparse.ArgumentParser(description="Split guest_templates.yaml heroes by source")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        help="Repo base directory (defaults to repo root detected from script location)",
    )
    args = parser.parse_args()

    repo_root = args.base_dir or Path(__file__).resolve().parents[1]
    data_dir, input_file, output_dir = _resolve_paths(repo_root)
    data = _load_templates(input_file)

    heroes_by_source = _split_heroes_by_source(data)
    _write_source_hero_files(output_dir, heroes_by_source)
    _write_main_stub(data_dir, data)

    print("\nDone! Review the new files and if satisfied, replace guest_templates.yaml with guest_templates_new.yaml")


if __name__ == "__main__":
    main()
