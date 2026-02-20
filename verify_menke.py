import re
import sys


SUSPICIOUS_NAMES = [
    "师", "王", "夫人", "婆婆", "仙", "皇", "帝", "祖", "圣", "神", "老", "怪", "童", "君", "使", "侠", "僧"
]

ALLOWED_NAMES = [
    "王重阳", "王语嫣", "王处一", "李秋水", "张三丰", "风清扬", "任我行", "谢逊",
    "张无忌", "赵敏", "洪七公", "欧阳锋", "周伯通", "黄蓉", "小龙女", "金轮法王",
    "林平之", "岳不群", "左冷禅", "令狐冲", "任盈盈", "韦小宝", "陈近南",
    "袁承志", "胡斐", "狄云", "石破天", "陈家洛", "霍青桐", "香香公主",
    "虚竹", "段誉", "萧峰", "慕容复", "鸠摩智", "殷素素", "张翠山", "谢烟客",
    "石中玉", "白自在", "程灵素", "苗若兰", "水笙", "丁典", "凌霜华", "血刀老祖", "戚长发",
    "阿朱", "阿紫", "阿碧", "包不同", "风波恶", "叶二娘", "云中鹤", "段正淳", "丁春秋",
    "游坦之", "木婉清", "钟灵", "康敏", "全冠清", "玄慈", "薛慕华", "马大元", "白世镜",
    "邓百川", "公冶乾", "甘宝宝", "秦红棉", "阮星竹", "刀白凤", "褚万里", "苏荃", "曾柔",
    "方怡", "沐剑屏", "茅十八", "海大富", "多隆", "索额图", "陈圆圆", "吴应熊", "韦春花",
    "风际中", "归辛树", "归二娘", "澄观", "夏青青", "温青青", "南兰", "福康安", "万圭",
    "凌退思", "花铁干", "言达平", "汪啸风", "阎基", "穆人清", "木桑道人", "何铁手", "焦公礼", "安小慧",
    "李自成", "余鱼同", "文泰来", "骆冰", "徐天宏", "赵半山", "无尘道长", "白阿绣", "丁不四",
    "丁不三", "贝海石", "梅芳姑", "田归农",
    "殷天正", "韦一笑", "谢逊", "金毛狮王", "紫衫龙王", "杨逍", "范遥", "殷梨亭", "莫声谷",
    "宋远桥", "俞莲舟", "张松溪", "俞岱岩", "纪晓芙", "周芷若", "灭绝师太", "方证大师", "冲虚道长",
    "一灯大师", "达摩祖师", "扫地僧", "独孤求败", "东方不败", "天山童姥", "李秋水", "无崖子", "慕容博", "萧远山",
    "黄药师", "欧阳克", "梅超风", "陈玄风", "完颜洪烈", "杨康", "穆念慈", "朱聪", "韩宝驹", "南希仁",
    "张阿生", "全金发", "韩小莹", "马钰", "丘处机", "谭处端", "刘处玄", "孙不二", "郝大通", "冯默风",
    "陆乘风", "曲灵风", "朱子柳", "武三通", "杨铁心", "包惜弱", "沙通天", "侯通海", "彭连虎",
    "灵智上人", "李莫愁", "郭芙", "耶律齐", "程英", "陆无双", "霍都", "达尔巴", "裘千尺", "公孙止",
    "公孙绿萼", "郭破虏", "郭襄", "尹志平", "洪凌波", "陆展元", "尹克西", "潇湘子", "武敦儒", "武修文",
    "赵志敬", "孙婆婆", "完颜萍", "陆冠英", "宋青书", "黛绮丝", "彭莹玉", "张中", "周颠", "冷谦", "铁冠道人",
    "阳顶天", "觉远", "渡厄", "渡劫", "渡难", "殷野王", "双儿", "阿珂", "建宁公主", "九难", "冯锡范",
    "吴三桂", "郑克塽", "李莫愁", "黄衫女子", "林朝英", "袁紫衣", "瑛姑", "柯镇恶", "裘千仞"
]

TABLE_PATTERN = re.compile(r'\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|')


def _parse_entries(content: str) -> list[dict]:
    entries: list[dict] = []
    for line in content.split('\n'):
        if not line.strip().startswith('|') or '---' in line or '姓名' in line:
            continue

        match = TABLE_PATTERN.match(line)
        if not match:
            continue

        name = match.group(1).strip()
        if not name:
            continue

        entries.append(
            {
                "name": name,
                "bio": match.group(2).strip(),
                "type": match.group(3).strip(),
                "rarity": match.group(4).strip(),
                "source": match.group(5).strip(),
            }
        )
    return entries


def _collect_entry_issues(entry: dict) -> list[str]:
    issues: list[str] = []
    name = entry['name']

    if name not in ALLOWED_NAMES:
        for keyword in SUSPICIOUS_NAMES:
            if keyword in name:
                issues.append(f"Suspicious name: '{name}' contains '{keyword}'. Check if it's a title.")
                break

    if len(entry['bio']) < 50:
        issues.append(f"Bio too short for {name}: {len(entry['bio'])} chars")

    return issues


def _collect_rarity_stats(entries: list[dict]) -> tuple[dict[str, int], list[str]]:
    rarity_counts = {"orange": 0, "purple": 0, "blue": 0, "green": 0}
    issues: list[str] = []

    for entry in entries:
        rarity = entry['rarity']
        if rarity in rarity_counts:
            rarity_counts[rarity] += 1
        else:
            issues.append(f"Unknown rarity '{rarity}' for {entry['name']}")

    return rarity_counts, issues


def _print_rarity_stats(rarity_counts: dict[str, int], total: int) -> None:
    if total <= 0:
        return

    print("\nRarity Distribution:")
    print(f"Orange: {rarity_counts['orange']} ({rarity_counts['orange']/total*100:.1f}%)")
    print(f"Purple: {rarity_counts['purple']} ({rarity_counts['purple']/total*100:.1f}%)")
    print(f"Blue: {rarity_counts['blue']} ({rarity_counts['blue']/total*100:.1f}%)")
    print(f"Green: {rarity_counts['green']} ({rarity_counts['green']/total*100:.1f}%)")


def verify_menke_db(file_path):
    print(f"Verifying {file_path}...")

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    entries = _parse_entries(content)
    print(f"Total entries found: {len(entries)}")

    rarity_counts, issues = _collect_rarity_stats(entries)
    for entry in entries:
        issues.extend(_collect_entry_issues(entry))

    _print_rarity_stats(rarity_counts, len(entries))

    print("\nPotential Issues Found:")
    for issue in issues:
        print(f"- {issue}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        verify_menke_db(sys.argv[1])
    else:
        verify_menke_db("docs/门客数据库-金庸.md")
