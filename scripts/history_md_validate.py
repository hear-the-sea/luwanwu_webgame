#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validate the history guest Markdown tables.

This repo stores historical figures in Markdown tables with 4 columns:
| 姓名 | 简介 | 类型 | 稀有度 |

This script checks:
- Each row parses correctly
- No duplicate names
- Bio length >= a configurable minimum (default: 150 chars)
- No Han末/三国-era figures slip into the Sui-Tang-FiveDynasties list (heuristic)
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")


@dataclass(frozen=True)
class Row:
    line_no: int
    name: str
    bio: str
    typ: str
    rarity: str


THREE_KINGDOMS_NAMES = {
    # Extremely common / high risk; keep the set short to reduce false positives.
    "刘备",
    "关羽",
    "张飞",
    "诸葛亮",
    "曹操",
    "曹丕",
    "曹植",
    "孙权",
    "周瑜",
    "司马懿",
    "司马昭",
    "司马炎",
}

# Heuristic keywords; avoid overly broad tokens like "汉末" which can false-positive
# on "南汉末主" (Five Dynasties' Southern Han).
THREE_KINGDOMS_KEYWORDS = ("汉末三国", "三国", "魏蜀吴", "东汉末", "建安", "赤壁")


def parse_rows(text: str) -> list[Row]:
    rows: list[Row] = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line.startswith("|"):
            continue
        if "姓名" in line or "---" in line:
            continue
        m = ROW_RE.match(line)
        if not m:
            raise ValueError(f"Unparseable table row at line {i}: {raw!r}")
        name, bio, typ, rarity = (g.strip() for g in m.groups())
        rows.append(Row(i, name, bio, typ, rarity))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--min-bio-len", type=int, default=150)
    args = ap.parse_args()

    text = args.path.read_text(encoding="utf-8")
    rows = parse_rows(text)

    issues: list[str] = []
    if not rows:
        issues.append("No rows found.")

    # Duplicates
    name_counts = Counter(r.name for r in rows)
    dups = [n for n, c in name_counts.items() if c > 1]
    for n in sorted(dups):
        lines = [str(r.line_no) for r in rows if r.name == n]
        issues.append(f"Duplicate name '{n}' at lines: {', '.join(lines)}")

    # Bio length
    for r in rows:
        if len(r.bio) < args.min_bio_len:
            issues.append(f"Bio too short ({len(r.bio)}) for '{r.name}' at line {r.line_no}")

    # Three Kingdoms (heuristic)
    for r in rows:
        if r.name in THREE_KINGDOMS_NAMES:
            issues.append(f"Disallowed era (Han末/三国) name '{r.name}' at line {r.line_no}")
        if any(k in r.bio for k in THREE_KINGDOMS_KEYWORDS):
            issues.append(f"Bio mentions Han末/三国 keywords for '{r.name}' at line {r.line_no}")

    if issues:
        print(f"[FAIL] {args.path} issues: {len(issues)}")
        for it in issues[:200]:
            print(f"- {it}")
        if len(issues) > 200:
            print(f"... ({len(issues) - 200} more)")
        return 1

    # Basic stats
    rarity_counts = Counter(r.rarity for r in rows)
    type_counts = Counter(r.typ for r in rows)
    print(f"[OK] {args.path}")
    print(f"- rows: {len(rows)}")
    print(f"- rarity: {dict(rarity_counts)}")
    print(f"- type: {dict(type_counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
