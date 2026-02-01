import re


def audit() -> None:
    path = "docs/门客数据库-历史人物-明清.md"
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    names = set()
    ids = set()
    errors = []
    green_count = 0
    total_count = 0
    valid_rarities = {"orange", "purple", "blue", "green"}

    # 匹配人物表格行（排除统计表/占位行等非人物行）
    for i, line in enumerate(lines):
        if "|" not in line or "稀有度" in line or "---" in line:
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue

        # 只处理稀有度字段为有效值的行，避免把统计表当成门客行
        rarity = parts[-2]
        if rarity not in valid_rarities:
            continue

        total_count += 1

        # 判断是否是绿色门客表格行 (编号在第一列，且是数字)
        is_green = False
        try:
            int(parts[1])
            is_green = True
            green_count += 1
            entry_id = parts[1]
            name = parts[2]
            bio = parts[3]
        except (TypeError, ValueError, IndexError):
            # 可能是橙/紫/蓝 (姓名在第一列)
            entry_id = "N/A"
            name = parts[1]
            bio = parts[2]

        # 1. 唯一性检查
        if name in names:
            errors.append(f"行 {i+1}: 重复姓名 '{name}'")
        names.add(name)

        if is_green:
            if entry_id in ids:
                errors.append(f"行 {i+1}: 重复编号 '{entry_id}'")
            ids.add(entry_id)

        # 2. 字数检查 (粗略中文字符统计)
        clean_bio = re.sub(r"[^\u4e00-\u9fa5]", "", bio)
        if len(clean_bio) < 140:  # 150字包含标点，纯中文140算及格线
            errors.append(f"行 {i+1}: '{name}' 简介字数不足 ({len(clean_bio)}字)")

        # 3. 生卒年格式检查
        if not re.match(r"^[（(][0-9]{4}年—[0-9]{4}年[）)]", bio.strip()):
            errors.append(f"行 {i+1}: '{name}' 生卒年格式错误")

        # 4. 时间线检查 (卒年不能 > 1860)
        death_year_match = re.search(r"—([0-9]{4})年", bio)
        if death_year_match:
            death_year = int(death_year_match.group(1))
            if death_year > 1860:
                errors.append(f"行 {i+1}: '{name}' 卒年越界 ({death_year}年)")

    print("--- 审计完成 ---")
    print(f"已扫描人物总数: {len(names)}")
    print(f"已识别绿色门客数: {green_count}")
    if not errors:
        print("✅ 完美！未发现任何合规性问题。")
    else:
        print(f"❌ 发现 {len(errors)} 处错误:")
        for err in errors[:20]:  # 只显示前20个
            print(err)


if __name__ == "__main__":
    audit()
