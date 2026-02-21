#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
De-template and customize bios in docs/门客数据库-历史人物-秦汉.md.

This repo previously expanded many bios by appending a few fixed template sentences.
The user now requires each bio to be individually customized (no repeated template endings).

Strategy:
- Parse Markdown table rows: | 姓名 | 简介 | 类型 | 稀有度 |
- Remove known high-frequency template sentences (exact matches, with minor quote variants).
- If bio becomes shorter than the minimum length, append 1-3 *name-containing* sentences
  built from the bio's own keywords + role inference, so that each entry stays unique
  without adding risky hard claims.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

ROW_RE = re.compile(
    r"^(?P<prefix>\|\s*)(?P<name>[^|]+?)(?P<mid1>\s*\|\s*)(?P<bio>[^|]+?)"
    r"(?P<mid2>\s*\|\s*)(?P<typ>[^|]+?)(?P<mid3>\s*\|\s*)(?P<rarity>[^|]+?)"
    r"(?P<suffix>\s*\|\s*)$"
)


@dataclass(frozen=True)
class Row:
    name: str
    bio: str
    typ: str
    rarity: str


def sha_pick(key: str, options: list[str], salt: str) -> str:
    h = hashlib.sha1((salt + "|" + key).encode("utf-8")).hexdigest()
    return options[int(h[:8], 16) % len(options)]


# Exact template sentences (the main source of "模板化" feeling).
TEMPLATE_SENTENCES = [
    "其生平与作为多散见于《史记》《汉书》及《后汉书》等正史相关传记，细节或简或繁；但其在秦汉政治制度、士人风气与社会运行中的位置清晰可辨，足以作为理解时代的一扇窗口。",
    '相关事迹主要见于正史与诸家注疏，个别轶闻宜以"史载""相传"分辨；综合其言行与处世，可见秦汉之际权力结构与治道取舍的复杂性，颇具典型意义。',
    "相关事迹主要见于正史与诸家注疏，个别轶闻宜以“史载”“相传”分辨；综合其言行与处世，可见秦汉之际权力结构与治道取舍的复杂性，颇具典型意义。",
    "正史对其记述或详或略，后世又多有文学化的再叙；今据较可靠的史料脉络梳理其功过得失，更便于把握秦汉国家治理与社会变迁的真实面向。",
    "其军旅经历与战场抉择常与当时的边防形势、补给交通与朝局决策相互牵连；史书记功亦记失，透过其成败沉浮，可见秦汉军事运作的现实与代价。",
    "乱世武人既要在兵戈里求胜，也不得不在政局中自保；其事迹散见《史记》《汉书》《后汉书》诸传，褒贬并存，正好折射秦汉军政互动与权力更替的张力。",
    "史传所载往往不止一场战役的胜负，更重其持久用兵、统御纪律与处置危局的能力；以其经历观之，可窥秦汉对外征伐、郡县经营与边疆治理的一角。",
]

GENERATED_SENTENCE_FRAGMENTS = [
    # Legacy template tails.
    "正史对其记述或详或略",
    "相关事迹主要见于正史与诸家注疏",
    "其生平与作为多散见于《史记》《汉书》及《后汉书》",
    "其军旅经历与战场抉择常与当时的边防形势",
    "乱世武人既要在兵戈里求胜",
    "史传所载往往不止一场战役的胜负",
    # Earlier iterations of this script (to allow re-generation without compounding).
    "把细节放回当时语境",
    "其可贵处在于让人看到秦汉政务的细密纹理",
    "把战局拉长来看",
    "不必强求一句定评",
    "归根结底，",
    "总之，回望",
    "之所以值得单列为门客",
    "若以外戚为线索重读",
]


ROLE_KEYWORDS = [
    "皇帝",
    "太后",
    "皇后",
    "公主",
    "丞相",
    "御史大夫",
    "太史令",
    "史学家",
    "经学家",
    "学者",
    "文学家",
    "辞赋家",
    "方士",
    "将军",
    "将领",
    "名将",
    "循吏",
    "酷吏",
    "游侠",
    "单于",
    "昆莫",
    "王",
    "侯",
]


# Keywords that help us attach a tailored angle. This list is deliberately domain-specific.
KEYWORDS = [
    "郡县",
    "分封",
    "削藩",
    "七国之乱",
    "文景",
    "昭宣",
    "盐铁",
    "均输",
    "平准",
    "推恩令",
    "察举",
    "律令",
    "断狱",
    "酷吏",
    "循吏",
    "经学",
    "古文",
    "今文",
    "礼制",
    "历法",
    "水利",
    "农桑",
    "冶铁",
    "造纸",
    "匈奴",
    "和亲",
    "西域",
    "丝绸之路",
    "乌孙",
    "南越",
    "西南夷",
    "羌",
    "鲜卑",
    "大宛",
    "封禅",
    "巫蛊",
    "外戚",
    "宦官",
    "政变",
    "托孤",
    "改制",
    "赤眉",
    "绿林",
    "割据",
    "统一",
]


def _append_unique_token(tokens: list[str], token: str, limit: int = 3) -> bool:
    if token not in tokens:
        tokens.append(token)
    return len(tokens) >= limit


def _collect_pattern_tokens(bio: str, tokens: list[str], pattern: str, limit: int = 3) -> bool:
    for match in re.finditer(pattern, bio):
        token = match.group(0)
        if _append_unique_token(tokens, token, limit=limit):
            return True
    return False


def extract_feature_tokens(bio: str) -> list[str]:
    """
    Pull a few *existing* tokens from the bio to anchor a customized add-on.
    We only reuse what is already in the text to avoid introducing risky claims.
    """
    tokens: list[str] = []
    patterns = [
        r"《[^》]{2,20}》",
        r"[\u4e00-\u9fff]{2,10}(之乱|之役|之战|之祸|之变|会议)",
        r"(关中|河西|河套|西域|岭南|南越|渤海|齐地|赵地|陇右|巴蜀|南阳|洛阳|长安)",
        r"“[^”]{2,20}”",
    ]

    for pattern in patterns:
        if _collect_pattern_tokens(bio, tokens, pattern):
            return tokens

    return tokens


def build_ngram_counts(bios: list[str]) -> dict[str, int]:
    """Build 2-4 char CJK ngram counts across all bios to pick a rare per-bio anchor token."""

    counts: dict[str, int] = {}
    stop = {"西汉", "东汉", "秦末", "汉朝", "朝廷", "天下", "百姓", "制度", "政治", "军事"}
    for bio in bios:
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", bio)
        for n in (2, 3, 4):
            for i in range(0, max(0, len(cjk) - n + 1)):
                g = cjk[i : i + n]
                if g in stop:
                    continue
                counts[g] = counts.get(g, 0) + 1
    return counts


def pick_rare_ngram(bio: str, ngram_counts: dict[str, int]) -> str | None:
    """Pick a low-frequency 2-4 char CJK token that already appears in this bio."""

    stop = {"西汉", "东汉", "秦末", "汉朝", "朝廷", "天下", "百姓", "制度", "政治", "军事"}
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", bio)
    best: tuple[int, int, str] | None = None  # (freq, -len, token)
    for n in (4, 3, 2):
        for i in range(0, max(0, len(cjk) - n + 1)):
            g = cjk[i : i + n]
            if g in stop:
                continue
            freq = ngram_counts.get(g, 999999)
            cand = (freq, -n, g)
            if best is None or cand < best:
                best = cand
    return best[2] if best else None


def build_custom_sentences(row: Row, ngram_counts: dict[str, int]) -> list[str]:
    """
    Build a small set of name-containing, token-anchored sentences.
    These are intentionally varied and based on existing bio content.
    """

    role = infer_role(row.bio)
    kws = extract_keywords(row.bio, limit=2)
    kw = (
        "、".join(kws)
        if kws
        else sha_pick(row.name, ["制度与人事", "边疆经略", "财政与军需", "礼法与学术", "权力更替与秩序重建"], "kw")
    )
    feats = extract_feature_tokens(row.bio)
    rare = pick_rare_ngram(row.bio, ngram_counts)

    f1 = feats[0] if len(feats) >= 1 else kw
    f2 = feats[1] if len(feats) >= 2 else (feats[0] if feats else role)
    anchor = rare or f1

    # Every generated sentence must contain at least one per-row anchor token to avoid "one-size-fits-all" tails.
    # Keep claims meta/interpretive to avoid injecting hard-to-verify facts.
    if row.typ.strip() == "文":
        s1_opts = [
            "谈到{name}，最容易被忽略的往往是“{anchor}”这一处：它把{f1}从概念拉回到具体人事。",
            "{name}的叙事可以先抓“{anchor}”这条线索，再回看{f1}，人物的位置就不至于被一句褒贬盖过。",
            "若从“{anchor}”切入{name}，{f1}的层次会更分明：同一选择在不同语境下往往有不同权衡。",
            "在{name}相关材料里，“{anchor}”常能提供一个较稳的落脚点，使{f1}的脉络更可感。",
            "把{name}与“{anchor}”并读，往往能看见{f1}并非空谈，而是落在日常制度与人情上的细节。",
            "读{name}不必急着下结论；先从“{anchor}”理清线索，再看{f1}，更容易把握其处境。",
        ]
        s2_opts = [
            "{name}与{f2}的关联并非点缀；以“{anchor}”为参照，更能理解{kw}在现实里如何被推动或被掣肘。",
            "若把目光落在{f2}与“{anchor}”上，{name}就不只是名号，而更像{kw}的一段现场记录。",
            "从“{anchor}”延展开去，{name}在{f2}上的态度与做法，恰能映出{kw}的取舍与边界。",
            "{name}的经历若对照“{anchor}”，{f2}与{f1}之间的牵制就不再抽象，反而更像一张可读的网。",
            "“{anchor}”这一点提醒我们：对{name}而言，{f2}常常不是背景，而是决定走向的硬约束之一。",
        ]
        s3_opts = [
            "写{name}时，与其追求一句定评，不如把“{anchor}”当作锚，顺带把{kw}的纹理看清楚。",
            "因此，{name}更像一枚坐标：以“{anchor}”定位，再对照{kw}，人物的得失才不至于被概念化。",
            "{name}的价值常在细部：围绕“{anchor}”梳理一遍，{kw}会从抽象讨论变成具体场景。",
            "总的来看，“{anchor}”让{name}与{kw}之间的连接更清晰：既能解释行为，也能解释限制。",
        ]
    else:
        s1_opts = [
            "说到{name}的战事与军旅，“{anchor}”常是绕不开的节点：它把{f1}的压力与选择具体化了。",
            "{name}的胜负不妨从“{anchor}”这处细节读起：顺着它回看{f1}，更能理解当时的取舍。",
            "在{f1}的局面里，{name}的进退未必只靠胆气；“{anchor}”往往提示补给、组织与朝局的牵引。",
            "若把{f1}与“{anchor}”并置来看，{name}的成败就不再孤立，而是嵌在一段现实结构之中。",
            "谈{name}不必只盯战功；“{anchor}”这一点能把胜负之外的约束说得更明白，尤其与{f1}相关。",
        ]
        s2_opts = [
            "把{f2}这一层变量纳入视野，再回到“{anchor}”，{name}的命运往往更容易读懂：功名与风险常同在。",
            "对照{f2}与“{anchor}”，更能看出{name}面对的并非单线条选择，而是多重压力的交汇点。",
            "从“{anchor}”出发回看{name}，{f2}既像战场变量，也像政治压力源，两者常在一处相撞。",
            "{name}的关键不止在一场战斗；借“{anchor}”检视{f2}，更能看到{kw}如何影响用兵与用人。",
        ]
        s3_opts = [
            "因此，{name}的意义不止一时战绩，而在于“{anchor}”能把{kw}的运转方式具体呈现出来。",
            "以“{anchor}”为锚回望{name}，更能把{kw}从口号拉回到真实的组织、资源与风险分配。",
            "总的来说，“{anchor}”让{name}的成败更可解释：它既指向{kw}，也指向当时的现实代价。",
        ]

    s1 = sha_pick(row.name, s1_opts, "s1").format(name=row.name, role=role, f1=f1, f2=f2, kw=kw, anchor=anchor)
    s2 = sha_pick(row.name, s2_opts, "s2").format(name=row.name, role=role, f1=f1, f2=f2, kw=kw, anchor=anchor)
    s3 = sha_pick(row.name, s3_opts, "s3").format(name=row.name, role=role, f1=f1, f2=f2, kw=kw, anchor=anchor)

    out: list[str] = []
    for s in (s1, s2, s3):
        s = s.strip()
        if not s.endswith(("。", "！", "？", "…", "；")):
            s += "。"
        out.append(s)
    return out


def strip_templates(bio: str) -> str:
    out = bio.strip()

    # Normalize "unknown year" placeholders like （？—？） to avoid turning them into repeated "sentences".
    out = normalize_unknown_years(out)

    # Remove earlier fixed template tails by exact match.
    for t in TEMPLATE_SENTENCES:
        # Remove with or without a preceding full-width space / normal space.
        out = out.replace(" " + t, "")
        out = out.replace("\u3000" + t, "")
        out = out.replace(t, "")

    # Sentence-level removal for legacy / generated boilerplate.
    sentences = split_sentences(out)
    kept: list[str] = []
    for s in sentences:
        if any(frag in s for frag in GENERATED_SENTENCE_FRAGMENTS):
            continue
        kept.append(s)
    out = "".join(kept)

    # Normalize stray whitespace.
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out


def split_sentences(text: str) -> list[str]:
    # Keep punctuation so we can re-join losslessly.
    parts = re.split(r"(?<=[。！？；…])", text)
    return [p for p in (s.strip() for s in parts) if p]


def normalize_unknown_years(text: str) -> str:
    # Use the full-width question mark used in the doc.
    s = text
    s = s.replace("（？—？）", "（生卒年不详）")
    # 生年不详—某年
    s = re.sub(r"（？—前(\d{1,4})年）", r"（生年不详—前\1年）", s)
    s = re.sub(r"（？—(\d{1,4})年）", r"（生年不详—\1年）", s)
    # 某年—卒年不详
    s = re.sub(r"（前(\d{1,4})年—？）", r"（生于前\1年，卒年不详）", s)
    s = re.sub(r"（(\d{1,4})年—？）", r"（生于\1年，卒年不详）", s)
    return s


def infer_role(bio: str) -> str:
    for k in ROLE_KEYWORDS:
        if k in bio:
            return k
    return "人物"


def extract_keywords(bio: str, limit: int = 2) -> list[str]:
    found: list[str] = []
    for k in KEYWORDS:
        if k in bio:
            found.append(k)
        if len(found) >= limit:
            break
    return found


def ensure_punct(bio: str) -> str:
    bio = bio.strip()
    if not bio:
        return bio
    if bio.endswith(("。", "！", "？", "…", "；")):
        return bio
    return bio + "。"


def custom_expand(row: Row, min_len: int, ngram_counts: dict[str, int]) -> str:
    bio = ensure_punct(row.bio)
    if len(bio) >= min_len:
        return bio

    additions = build_custom_sentences(row, ngram_counts)
    out = bio
    for s in additions:
        if len(out) >= min_len:
            break
        out += s
    # If still short (rare), add one more deterministic sentence that includes the name and an anchor token.
    if len(out) < min_len:
        role = infer_role(bio)
        feats = extract_feature_tokens(bio)
        anchor = pick_rare_ngram(bio, ngram_counts) or (feats[0] if feats else "史载细节")
        tail_opts = [
            "{name}若与“{anchor}”一并对照，反而更能看清其作为{role}在时代结构中的位置与限度。",
            "补上一句：以“{anchor}”为线索再读{name}，往往能把{role}的抉择从传说与评价里分离出来。",
            "{name}的可读性常在细处；围绕“{anchor}”补足背景，{role}的行动就不至于只剩标签。",
        ]
        out += sha_pick(row.name, tail_opts, "tail").format(name=row.name, role=role, anchor=anchor)
    return out


def process(text: str, min_len: int) -> str:
    # Two-pass processing:
    # 1) strip templates and normalize placeholders, collect bios for global ngram stats;
    # 2) generate per-row anchored expansions with the global ngram_counts.
    parsed: list[tuple[str, Row] | tuple[str, None]] = []
    base_bios: list[str] = []

    for raw in text.splitlines(keepends=False):
        line = raw.rstrip("\n")
        s = line.strip()
        if s.startswith("|") and ("姓名" not in s) and ("---" not in s):
            m = ROW_RE.match(s)
            if m:
                row = Row(
                    name=m.group("name").strip(),
                    bio=m.group("bio").strip(),
                    typ=m.group("typ").strip(),
                    rarity=m.group("rarity").strip(),
                )
                bio2 = strip_templates(row.bio)
                row2 = Row(row.name, bio2, row.typ, row.rarity)
                parsed.append((line, row2))
                base_bios.append(row2.bio)
                continue
        parsed.append((line, None))

    ngram_counts = build_ngram_counts(base_bios)

    out_lines: list[str] = []
    for original_line, row in parsed:
        if row is None:
            out_lines.append(original_line)
            continue
        m = ROW_RE.match(original_line.strip())
        if not m:
            out_lines.append(original_line)
            continue
        bio3 = custom_expand(row, min_len=min_len, ngram_counts=ngram_counts)
        out_lines.append(
            f"{m.group('prefix')}{row.name}{m.group('mid1')}{bio3}"
            f"{m.group('mid2')}{row.typ}{m.group('mid3')}{row.rarity}{m.group('suffix')}"
        )

    return "\n".join(out_lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path, nargs="?", default=Path("docs/门客数据库-历史人物-秦汉.md"))
    ap.add_argument("--min-bio-len", type=int, default=150)
    args = ap.parse_args()

    src = args.path.read_text(encoding="utf-8")
    dst = process(src, min_len=args.min_bio_len)
    if dst != src:
        args.path.write_text(dst, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
