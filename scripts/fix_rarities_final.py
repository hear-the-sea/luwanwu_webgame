
file_path = 'docs/门客数据库-历史人物-秦汉.md'

rarity_map = {
    "刘邦": "orange", "刘彻": "orange", "刘秀": "orange",
    "项羽": "purple", "韩信": "purple", "张良": "purple", "萧何": "purple", "司马迁": "purple",
    "霍去病": "purple", "卫青": "purple", "蔡伦": "purple", "张衡": "purple", "班超": "purple",
    "霍光": "purple", "郑玄": "purple", "严光": "purple", "扬雄": "purple", "檀石槐": "purple",
    "公输班": "purple", "墨翟": "purple"
}


def fix_rarities(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    data = {'orange': [], 'purple': [], 'blue': [], 'green': []}

    for line in lines:
        if line.strip().startswith('|') and '姓名' not in line and '---' not in line:
            parts = [p.strip() for p in line.split('|') if p]
            if len(parts) >= 4:
                name = parts[0]
                bio = parts[1]
                type_ = parts[2]
                current_rarity = parts[3].lower()

                if name in rarity_map:
                    new_rarity = rarity_map[name]
                else:
                    new_rarity = current_rarity

                # Validation
                if new_rarity not in data:
                    new_rarity = 'green'

                data[new_rarity].append({'name': name, 'bio': bio, 'type': type_, 'rarity': new_rarity})

    output = """## 历史人物篇 - 秦汉时期

> 包含：秦朝、秦末、西汉、新朝、东汉时期的历史人物
> 注：秦统一前的人物（如嬴政、白起、王翦、李斯等）请参见"先秦时期"文档

"""
    display_map = {
        'orange': '🟠 橙色',
        'purple': '🟣 紫色',
        'blue': '🔵 蓝色',
        'green': '🟢 绿色'
    }

    order = ['orange', 'purple', 'blue', 'green']

    for r in order:
        output += f"### {display_map[r]}\n\n"
        output += "| 姓名 | 简介 | 类型 | 稀有度 |\n"
        output += "|------|------|------|--------|\n"

        sorted_entries = sorted(data[r], key=lambda x: (x['type'], x['name']))

        for e in sorted_entries:
            output += f"| {e['name']} | {e['bio']} | {e['type']} | {e['rarity']} |\n"

        output += "\n"

    counts = {r: len(data[r]) for r in order}
    total = sum(counts.values())

    footer = f"""---

**文档统计**：
- 🟠 橙色：{counts['orange']}人
- 🟣 紫色：{counts['purple']}人
- 🔵 蓝色：{counts['blue']}人
- 🟢 绿色：{counts['green']}人
- **总计：{total}人**

*文档持续更新中... 有新的门客想法随时添加喵～* ฅ(＾・ω・＾ฅ)
"""
    output += footer

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(output)

    print(f"Rarities Fixed. Total: {total}")


if __name__ == "__main__":
    fix_rarities(file_path)