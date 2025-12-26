#!/usr/bin/env python
"""Split guest_templates.yaml heroes into separate files by source/author."""

from pathlib import Path

import yaml


def detect_source(hero: dict) -> str:
    """Detect the source/author of a hero based on flavor text or key."""
    flavor = hero.get("flavor", "").lower()
    key = hero.get("key", "").lower()

    # Check for base/generic templates
    if key.startswith("base_"):
        return "base"

    # Check for special heroes
    if key.startswith("special_hero_"):
        return "special"

    # Check flavor text for source indicators
    if "古龙" in flavor or "古龙小说" in hero.get("flavor", ""):
        return "gulong"
    if "梁羽生" in flavor or "梁羽生小说" in hero.get("flavor", ""):
        return "liangyshen"
    if "温瑞安" in flavor or "温瑞安小说" in hero.get("flavor", ""):
        return "wenruian"
    if "黄易" in flavor or "黄易小说" in hero.get("flavor", ""):
        return "huangyi"
    if "隋唐演义" in flavor or "隋唐" in hero.get("flavor", ""):
        return "suitang"
    if "天龙八部" in flavor or "神雕侠侣" in flavor or "笑傲江湖" in flavor:
        return "jinyong"

    # Check for known author patterns in flavor
    gulong_works = [
        "多情剑客无情剑", "楚留香", "陆小凤", "绝代双骄", "萧十一郎",
        "三少爷的剑", "天涯明月刀", "边城浪子", "武林外史", "流星蝴蝶剑",
        "白玉老虎", "欢乐英雄", "七种武器", "大旗英雄传", "英雄无泪",
        "圆月弯刀", "浣花洗剑录", "大人物", "七杀手", "血鹦鹉",
        "碧血洗银枪", "飘香剑雨", "名剑风流", "大地飞鹰", "九月鹰飞",
    ]
    for work in gulong_works:
        if work in hero.get("flavor", ""):
            return "gulong"

    liangyshen_works = [
        "七剑下天山", "白发魔女传", "萍踪侠影录", "冰川天女传", "云海玉弓缘",
        "江湖三女侠", "女帝奇英传", "大唐游侠传",
    ]
    for work in liangyshen_works:
        if work in hero.get("flavor", ""):
            return "liangyshen"

    wenruian_works = [
        "四大名捕", "神州奇侠", "说英雄谁是英雄", "逆水寒", "布衣神相",
    ]
    for work in wenruian_works:
        if work in hero.get("flavor", ""):
            return "wenruian"

    huangyi_works = [
        "寻秦记", "大唐双龙传", "覆雨翻云", "破碎虚空",
    ]
    for work in huangyi_works:
        if work in hero.get("flavor", ""):
            return "huangyi"

    # Check key patterns
    if "pubayi" in key:
        return "original"

    # Default to original
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


def main():
    base_dir = Path("/home/daniel/code/web_game_v5/data")
    backup_file = base_dir / "guest_templates_full.yaml"
    input_file = backup_file if backup_file.exists() else base_dir / "guest_templates.yaml"
    output_dir = base_dir / "guests"
    output_dir.mkdir(exist_ok=True)

    # Use ruamel.yaml for better parsing of complex YAML
    try:
        from ruamel.yaml import YAML
        ryaml = YAML()
        ryaml.preserve_quotes = True
        with open(input_file, "r", encoding="utf-8") as f:
            data = to_plain(ryaml.load(f))
    except ImportError:
        # Fallback to PyYAML with safe_load
        with open(input_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

    # Extract heroes by source
    heroes_by_source: dict[str, dict[str, list]] = {}
    heroes_data = data.get("heroes", {})

    for rarity, heroes in heroes_data.items():
        for hero in heroes:
            source = detect_source(hero)
            if source not in heroes_by_source:
                heroes_by_source[source] = {}
            if rarity not in heroes_by_source[source]:
                heroes_by_source[source][rarity] = []
            heroes_by_source[source][rarity].append(hero)

    # Write separate files
    for source, heroes in heroes_by_source.items():
        output_file = output_dir / f"{source}.yaml"
        output_data = {"heroes": heroes}
        with open(output_file, "w", encoding="utf-8") as f:
            # Add header comment
            if source == "gulong":
                f.write("# 古龙作品门客\n")
            elif source == "liangyshen":
                f.write("# 梁羽生作品门客\n")
            elif source == "wenruian":
                f.write("# 温瑞安作品门客\n")
            elif source == "huangyi":
                f.write("# 黄易作品门客\n")
            elif source == "suitang":
                f.write("# 隋唐演义门客\n")
            elif source == "jinyong":
                f.write("# 金庸作品门客\n")
            elif source == "base":
                f.write("# 基础门客模板\n")
            elif source == "special":
                f.write("# 特殊/隐藏BOSS门客\n")
            else:
                f.write("# 原创门客\n")
            f.write("\n")
            yaml.safe_dump(output_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # Count heroes
        total = sum(len(h) for h in heroes.values())
        print(f"Created {output_file.name}: {total} heroes")

    # Create new main config without heroes
    new_main_data = {k: v for k, v in data.items() if k != "heroes"}
    new_main_file = base_dir / "guest_templates_new.yaml"
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
        f.write("# - special.yaml: 特殊/隐藏BOSS\n")
        f.write("\n")
        yaml.safe_dump(new_main_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"Created {new_main_file.name}")

    print("\nDone! Review the new files and if satisfied, replace guest_templates.yaml with guest_templates_new.yaml")


if __name__ == "__main__":
    main()
