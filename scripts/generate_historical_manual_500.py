from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import requests
import yaml

API = "https://zh.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "web_game_v5_guest_manual_builder/1.0"}

TARGET_QUOTAS = {
    "xianqin": 70,
    "qinhan": 90,
    "sljnbc": 100,
    "suitang": 90,
    "songliaojinyuan": 90,
    "mingqing": 60,
}

ERA_CONFIG = {
    "xianqin": {
        "label": "先秦",
        "categories": [
            "春秋人",
            "戰國人",
            "春秋戰國人物",
            "戰國歷史人物",
            "春秋政治人物",
            "春秋军事人物",
            "春秋战国政治人物",
            "春秋战国军事人物",
        ],
        "outfile": "data/guests/history_xianqin_10.yaml",
        "key_prefix": "hist_xianqin",
    },
    "qinhan": {
        "label": "秦汉",
        "categories": [
            "秦朝人",
            "秦朝政治人物",
            "秦朝軍事人物",
            "西汉人",
            "西汉政治人物",
            "西汉军事人物",
            "东汉人",
            "东汉政治人物",
            "东汉军事人物",
            "西汉女性人物",
            "东汉女性人物",
        ],
        "outfile": "data/guests/history_qinhan_09.yaml",
        "key_prefix": "hist_qinhan",
    },
    "sljnbc": {
        "label": "三国两晋南北朝",
        "categories": [
            "三國軍事人物",
            "三國政治人物",
            "三国志立传人物",
            "南北朝人",
            "南北朝政治人物",
            "南北朝女性人物",
            "西晉宗教人物",
            "東晉宗教人物",
            "西晉道教人物",
            "東晉道教人物",
        ],
        "outfile": "data/guests/history_sljnbc_11.yaml",
        "key_prefix": "hist_sljnbc",
    },
    "suitang": {
        "label": "隋唐五代",
        "categories": [
            "隋朝人",
            "隋朝政治人物",
            "隋朝军人",
            "唐朝人",
            "唐朝政治人物",
            "唐朝軍事人物小作品",
            "五代十國軍事人物",
            "五代十國政治人物",
            "五代十國詞人",
            "五代十國詩人",
        ],
        "outfile": "data/guests/history_suitang_10.yaml",
        "key_prefix": "hist_suitang",
    },
    "songliaojinyuan": {
        "label": "宋辽金元",
        "categories": [
            "北宋人",
            "北宋政治人物",
            "北宋军事人物",
            "南宋人",
            "南宋政治人物",
            "南宋军事人物",
            "金朝人",
            "金朝政治人物",
            "金朝女性人物",
            "元朝人",
            "元朝政治人物",
            "元朝女性人物",
        ],
        "outfile": "data/guests/history_songliaojinyuan_11.yaml",
        "key_prefix": "hist_songliaojinyuan",
    },
    "mingqing": {
        "label": "明清",
        "categories": [
            "明朝人",
            "明朝人物",
            "明朝叛乱人物",
            "清朝人",
            "清朝人物",
            "清朝中法戰爭人物",
            "清朝上海政治人物",
            "清朝云南政治人物",
        ],
        "outfile": "data/guests/history_mingqing_09.yaml",
        "key_prefix": "hist_mingqing",
    },
}

RARITY_GROWTH = {
    "green": [3, 7],
    "blue": [5, 9],
    "purple": [6, 11],
    "orange": [6, 14],
}

NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
BAD_SUFFIXES = ("帝", "宗", "祖", "王", "后", "妃", "皇")
BAD_EXACT = {
    "太祖",
    "太宗",
    "高祖",
    "高宗",
    "世宗",
    "仁宗",
    "神宗",
    "英宗",
    "徽宗",
    "钦宗",
    "宁宗",
    "寧宗",
    "理宗",
    "度宗",
    "恭帝",
    "文帝",
    "武帝",
}

MIL_KEYS = ("军", "軍", "武", "将", "將", "叛乱", "叛亂", "戰")
FEMALE_CAT_KEYS = ("女性",)
BLUE_CAT_KEYS = ("政治人物", "军事人物", "軍事人物", "詩人", "詞人")

CIVIL_FLAVORS = [
    "（生卒年不详）{era}人物{name}，在文教、政务或地方治理领域具有代表性。其活动多见于制度执行与社会秩序维护层面，能够在复杂环境下保持稳定判断。后世论及{era}政治文化演进时，常将{name}作为观察官僚运作与士人风气的重要样本。",
    "（生卒年不详）{era}人物{name}，以理政能力与文治见长。其经历体现了当时朝廷决策、地方执行与社会反馈之间的张力，也反映出个人才识对历史进程的实际作用。围绕{name}的讨论，往往聚焦于{era}时代治理方式的成效与边界。",
    "（生卒年不详）{era}人物{name}，在{era}公共事务中留下了可辨识的历史轨迹。其事功未必全部体现在显赫头衔，却通过政策落实、文化传播或行政协调持续影响当时社会。后人评价虽有分歧，但{name}在同代人物谱系中的位置较为稳固。",
]

MILITARY_FLAVORS = [
    "（生卒年不详）{era}人物{name}，以统兵、守御或征讨事务见长。其军事价值不仅体现在战场胜负，更在于能否维持补给、军纪与地方秩序，使战果转化为持续稳定的治理能力。后世讨论{era}军政结构时，常把{name}视作关键样本。",
    "（生卒年不详）{era}人物{name}，长期活跃于战事与防务一线。其作战风格强调执行效率与资源调度，能够在高压局势下维持队伍完整并完成阶段性目标。围绕{name}的史事，常被用于分析{era}时期军事体系的强弱与转折。",
    "（生卒年不详）{era}人物{name}，属于{era}时期兼具战场经验与组织能力的武职代表。其经历覆盖野战、守城与区域防务等多种场景，展现了军事行动与国家治理之间的紧密联动。后世评价其历史意义时，多强调其在乱局中的稳定作用。",
]


def api_get(params: dict) -> dict:
    r = requests.get(API, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def looks_like_original_name(name: str) -> bool:
    if not NAME_RE.fullmatch(name):
        return False
    if name in BAD_EXACT:
        return False
    if any(name.endswith(x) for x in BAD_SUFFIXES):
        return False
    return True


def fetch_members(category: str, limit: int = 140) -> list[str]:
    out: list[str] = []
    cont: dict = {}
    while len(out) < limit:
        params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmtype": "page",
            "cmnamespace": 0,
            "cmlimit": "max",
        }
        params.update(cont)
        try:
            data = api_get(params)
        except Exception:
            break
        rows = data.get("query", {}).get("categorymembers", [])
        out.extend([x.get("title", "").strip() for x in rows if x.get("title")])
        if "continue" not in data:
            break
        cont = data["continue"]
    return out[:limit]


def load_existing_names_and_max_idx() -> tuple[set[str], dict[str, int]]:
    existing: set[str] = set()
    max_idx = {cfg["key_prefix"]: 0 for cfg in ERA_CONFIG.values()}
    key_res = {kp: re.compile(rf"^{re.escape(kp)}_(\d+)") for kp in max_idx}

    for p in Path("data/guests").glob("*.yaml"):
        try:
            payload = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        heroes = payload.get("heroes")
        if not isinstance(heroes, dict):
            continue
        for rows in heroes.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                n = str(row.get("name") or "").strip()
                if n:
                    existing.add(n)
                k = str(row.get("key") or "")
                for kp, rx in key_res.items():
                    m = rx.match(k)
                    if m:
                        max_idx[kp] = max(max_idx[kp], int(m.group(1)))
    return existing, max_idx


def infer_archetype(category: str) -> str:
    return "military" if any(k in category for k in MIL_KEYS) else "civil"


def infer_gender(category: str) -> str:
    return "female" if any(k in category for k in FEMALE_CAT_KEYS) else "male"


def infer_rarity(category: str, name: str) -> str:
    h = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16)
    if any(k in category for k in BLUE_CAT_KEYS) and h % 4 == 0:
        return "blue"
    return "green"


def build_weights(name: str, archetype: str, rarity: str) -> dict[str, int]:
    h = int(hashlib.sha1(name.encode("utf-8")).hexdigest(), 16)
    if archetype == "military":
        force = 42 + (h % 7)
        intellect = 11 + ((h >> 5) % 8)
        defense = 22 + ((h >> 9) % 7)
        agility = 100 - force - intellect - defense
    else:
        force = 11 + (h % 7)
        intellect = 50 + ((h >> 5) % 9)
        defense = 16 + ((h >> 9) % 8)
        agility = 100 - force - intellect - defense

    if rarity == "blue":
        if archetype == "military":
            force += 2
            defense += 1
            intellect -= 1
            agility -= 2
        else:
            intellect += 2
            defense += 1
            force -= 1
            agility -= 2

    vals = {"force": force, "intellect": intellect, "defense": defense, "agility": agility}
    for k in vals:
        vals[k] = max(8, min(60, int(vals[k])))
    vals["agility"] += 100 - sum(vals.values())
    return vals


def build_flavor(name: str, era: str, archetype: str, idx: int) -> str:
    if archetype == "military":
        tpl = MILITARY_FLAVORS[idx % len(MILITARY_FLAVORS)]
    else:
        tpl = CIVIL_FLAVORS[idx % len(CIVIL_FLAVORS)]
    return tpl.format(name=name, era=era)


def collect_names(existing: set[str]) -> dict[str, list[tuple[str, str]]]:
    # era -> [(name, category)]
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    used = set(existing)

    for era, cfg in ERA_CONFIG.items():
        for cat in cfg["categories"]:
            for n in fetch_members(cat):
                if not looks_like_original_name(n):
                    continue
                if n in used:
                    continue
                used.add(n)
                out[era].append((n, cat))
        print(f"[collect] era={era} names={len(out[era])}")

    return out


def build_payload(
    candidates: dict[str, list[tuple[str, str]]], max_idx: dict[str, int]
) -> dict[str, dict[str, list[dict]]]:
    payload: dict[str, dict[str, list[dict]]] = {era: defaultdict(list) for era in ERA_CONFIG}

    for era, cfg in ERA_CONFIG.items():
        quota = TARGET_QUOTAS[era]
        pool = candidates.get(era, [])
        if len(pool) < quota:
            raise RuntimeError(f"era={era} names not enough: {len(pool)} < {quota}")

        cursor = max_idx[cfg["key_prefix"]]
        for i, (name, cat) in enumerate(pool[:quota], start=1):
            archetype = infer_archetype(cat)
            gender = infer_gender(cat)
            rarity = infer_rarity(cat, name)
            cursor += 1
            row = {
                "key": f"{cfg['key_prefix']}_{cursor:04d}",
                "name": name,
                "default_gender": gender,
                "archetype": archetype,
                "flavor": build_flavor(name, cfg["label"], archetype, i),
                "growth_range": RARITY_GROWTH[rarity],
                "attribute_weights": build_weights(name, archetype, rarity),
            }
            payload[era][rarity].append(row)
        print(f"[build] era={era} selected={quota}")

    return payload


def write_files(payload: dict[str, dict[str, list[dict]]]) -> None:
    order = ["orange", "purple", "blue", "green", "red", "gray", "black"]
    for era, cfg in ERA_CONFIG.items():
        rarity_map = payload[era]
        heroes = {r: rarity_map[r] for r in order if rarity_map.get(r)}
        out = {"heroes": heroes}
        path = Path(cfg["outfile"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")


def main() -> None:
    existing, max_idx = load_existing_names_and_max_idx()
    candidates = collect_names(existing)
    payload = build_payload(candidates, max_idx)
    write_files(payload)

    stats = {}
    total = 0
    for era in ERA_CONFIG:
        c = sum(len(v) for v in payload[era].values())
        total += c
        stats[era] = {"count": c, "rarity": {k: len(v) for k, v in payload[era].items()}}

    print(json.dumps({"total": total, "stats": stats}, ensure_ascii=False))


if __name__ == "__main__":
    main()
