import re
from typing import Iterable


def _parse_table_line(parts: list[str]) -> tuple[bool, str, str, str] | None:
    if len(parts) < 5:
        return None

    valid_rarities = {"orange", "purple", "blue", "green"}
    rarity = parts[-2]
    if rarity not in valid_rarities:
        return None

    try:
        int(parts[1])
        return True, parts[1], parts[2], parts[3]
    except (TypeError, ValueError, IndexError):
        return False, "N/A", parts[1], parts[2]


def _collect_entry_issues(
    *,
    line_no: int,
    name: str,
    bio: str,
    entry_id: str,
    is_green: bool,
    names: set[str],
    ids: set[str],
) -> list[str]:
    issues: list[str] = []

    if name in names:
        issues.append(f"行 {line_no}: 重复姓名 '{name}'")
    names.add(name)

    if is_green:
        if entry_id in ids:
            issues.append(f"行 {line_no}: 重复编号 '{entry_id}'")
        ids.add(entry_id)

    clean_bio = re.sub(r"[^\u4e00-\u9fa5]", "", bio)
    if len(clean_bio) < 140:
        issues.append(f"行 {line_no}: '{name}' 简介字数不足 ({len(clean_bio)}字)")

    if not re.match(r"^[（(][0-9]{4}年—[0-9]{4}年[）)]", bio.strip()):
        issues.append(f"行 {line_no}: '{name}' 生卒年格式错误")

    death_year_match = re.search(r"—([0-9]{4})年", bio)
    if death_year_match:
        death_year = int(death_year_match.group(1))
        if death_year > 1860:
            issues.append(f"行 {line_no}: '{name}' 卒年越界 ({death_year}年)")

    return issues


def _iter_table_lines(lines: Iterable[str]):
    for line_no, line in enumerate(lines, start=1):
        if "|" not in line or "稀有度" in line or "---" in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        parsed = _parse_table_line(parts)
        if parsed is None:
            continue
        yield line_no, parsed


def audit() -> None:
    path = "docs/门客数据库-历史人物-明清.md"
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    names: set[str] = set()
    ids: set[str] = set()
    errors: list[str] = []
    green_count = 0

    for line_no, (is_green, entry_id, name, bio) in _iter_table_lines(lines):
        if is_green:
            green_count += 1
        errors.extend(
            _collect_entry_issues(
                line_no=line_no,
                name=name,
                bio=bio,
                entry_id=entry_id,
                is_green=is_green,
                names=names,
                ids=ids,
            )
        )

    print("--- 审计完成 ---")
    print(f"已扫描人物总数: {len(names)}")
    print(f"已识别绿色门客数: {green_count}")
    if not errors:
        print("✅ 完美！未发现任何合规性问题。")
        return

    print(f"❌ 发现 {len(errors)} 处错误:")
    for err in errors[:20]:
        print(err)


if __name__ == "__main__":
    audit()
