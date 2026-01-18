
file_path = 'docs/门客数据库-历史人物-秦汉.md'

# Extensive Rarity Map
rarity_map = {
    # Orange
    "刘邦": "orange", "刘彻": "orange", "刘秀": "orange",

    # Purple (Top Tier)
    "项羽": "purple", "韩信": "purple", "张良": "purple", "萧何": "purple", "司马迁": "purple",
    "霍去病": "purple", "卫青": "purple", "蔡伦": "purple", "张衡": "purple", "班超": "purple",
    "霍光": "purple", "郑玄": "purple", "严光": "purple", "扬雄": "purple", "王莽": "purple",
    "吕雉": "purple", "王昭君": "purple", "蔡文姬": "purple", "李斯": "purple", "蒙恬": "purple",
    "冒顿": "purple", "檀石槐": "purple", "公输班": "purple", "墨翟": "purple", "窦武": "purple",
    "陈蕃": "purple", "李固": "purple", "杨震": "purple",

    # Blue (High Tier)
    "陈平": "blue", "彭越": "blue", "英布": "blue", "樊哙": "blue", "周亚夫": "blue", "张骞": "blue",
    "李广": "blue", "马援": "blue", "邓禹": "blue", "吴汉": "blue", "冯异": "blue", "耿弇": "blue",
    "岑彭": "blue", "寇恂": "blue", "贾复": "blue", "陈胜": "blue", "吴广": "blue", "项梁": "blue",
    "赵佗": "blue", "公孙述": "blue", "樊崇": "blue", "曹参": "blue", "周勃": "blue", "灌婴": "blue",
    "夏侯婴": "blue", "季布": "blue", "郦食其": "blue", "陆贾": "blue", "贾谊": "blue", "晁错": "blue",
    "袁盎": "blue", "桑弘羊": "blue", "李陵": "blue", "赵破奴": "blue", "李广利": "blue", "魏相": "blue",
    "丙吉": "blue", "黄霸": "blue", "东方朔": "blue", "卓文君": "blue", "卫子夫": "blue", "赵飞燕": "blue",
    "许平君": "blue", "淳于意": "blue", "京房": "blue", "许慎": "blue", "班婕妤": "blue", "赵合德": "blue",
    "李夫人": "blue", "蔡邕": "blue", "马融": "blue", "刘向": "blue", "刘歆": "blue", "班固": "blue",
    "华佗": "blue", "张机": "blue", "苏武": "blue", "冯辽": "blue", "尉缭": "blue", "窦漪房": "blue",
    "路博德": "blue", "老上": "blue", "呼韩邪": "blue", "解忧公主": "blue", "司马相如": "blue", "祭遵": "blue",
    "铫期": "blue", "王梁": "blue", "王霸": "blue", "王常": "blue", "刘植": "blue", "郑吉": "blue",
    "傅介子": "blue", "陈汤": "blue", "甘英": "blue", "袁安": "blue", "张纲": "blue", "崔寔": "blue",
    "班勇": "blue", "傅燮": "blue", "杜诗": "blue", "耿秉": "blue", "张奂": "blue", "于定国": "blue",
    "召信臣": "blue", "文翁": "blue", "刘玄": "blue", "来歙": "blue", "臧宫": "blue", "班昭": "blue",
    "梁鸿": "blue", "蒙毅": "blue", "冯劫": "blue", "甘罗": "blue", "项伯": "blue", "项庄": "blue",
    "田横": "blue", "田荣": "blue", "田儋": "blue", "魏豹": "blue", "赵歇": "blue", "陈馀": "blue",
    "张耳": "blue", "纪信": "blue", "周苛": "blue", "审食其": "blue", "栾布": "blue", "周昌": "blue",
    "叔孙通": "blue", "刘濞": "blue", "窦婴": "blue", "田蚡": "blue", "灌夫": "blue", "王政君": "blue",
    "王凤": "blue", "王匡": "blue", "梁冀": "blue", "窦太后": "blue", "曹节": "blue", "何进": "blue"
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
                
                # Default to green if not in map, otherwise use map
                if name in rarity_map:
                    rarity = rarity_map[name]
                else:
                    rarity = 'green'
                
                data[rarity].append({'name': name, 'bio': bio, 'type': type_, 'rarity': rarity})

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
    
    print(f"Final Rarity Fix V2. Total: {total}")
    print(f"New Counts: {counts}")

if __name__ == "__main__":
    fix_rarities(file_path)