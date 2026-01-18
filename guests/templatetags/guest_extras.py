from __future__ import annotations

from django import template
from django.utils.html import conditional_escape, format_html, format_html_join

from guests.models import GuestRarity

register = template.Library()

RARITY_CLASS_MAP = {
    GuestRarity.BLACK: "rarity-black",
    GuestRarity.GRAY: "rarity-gray",
    GuestRarity.GREEN: "rarity-green",
    GuestRarity.BLUE: "rarity-blue",
    GuestRarity.RED: "rarity-red",
    GuestRarity.PURPLE: "rarity-purple",
    GuestRarity.ORANGE: "rarity-orange",
}

RARITY_LABEL_MAP = {value: label for value, label in GuestRarity.choices}


def _normalize_rarity(value: str | GuestRarity | None) -> GuestRarity | None:
    if not value:
        return None
    if isinstance(value, GuestRarity):
        return value
    try:
        return GuestRarity(value)
    except ValueError:
        return None


@register.filter
def rarity_class(value: str | GuestRarity | None) -> str:
    normalized = _normalize_rarity(value)
    if not normalized:
        return "rarity-default"
    return RARITY_CLASS_MAP.get(normalized, "rarity-default")


@register.filter
def rarity_label(value: str | GuestRarity | None) -> str:
    normalized = _normalize_rarity(value)
    if not normalized:
        return "未知稀有度"
    return RARITY_LABEL_MAP.get(normalized.value, "未知稀有度")


@register.filter
def gear_summary(template) -> str:
    """
    Build a short tooltip for gear: description + stat bonuses + set info.
    """
    if not template:
        return ""
    stat_labels = {
        "hp": "生命",
        "force": "武力",
        "intellect": "智力",
        "defense": "防御",
        "agility": "敏捷",
        "luck": "运势",
        "attack": "攻击",
    }
    parts = []
    desc = getattr(template, "description", "")
    if desc:
        parts.append(str(desc))
    stats = []
    atk = getattr(template, "attack_bonus", 0)
    if atk:
        stats.append(f"{stat_labels['attack']}+{atk}")
    defense_bonus = getattr(template, "defense_bonus", 0)
    if defense_bonus:
        stats.append(f"{stat_labels['defense']}+{defense_bonus}")
    extra_stats = getattr(template, "extra_stats", {}) or {}
    for key, value in extra_stats.items():
        if value is None:
            continue
        label = stat_labels.get(key, key)
        stats.append(f"{label}+{value}")
    if stats:
        parts.append("、".join(stats))
    set_key = getattr(template, "set_key", "") or ""
    set_bonus = getattr(template, "set_bonus", {}) or {}
    if set_key or set_bonus:
        pieces = set_bonus.get("pieces") if isinstance(set_bonus, dict) else None
        bonus_map = set_bonus.get("bonus") if isinstance(set_bonus, dict) else None
        bonus_parts = []
        if isinstance(bonus_map, dict):
            for key, value in bonus_map.items():
                if value is None:
                    continue
                label = stat_labels.get(key, key)
                bonus_parts.append(f"{label}+{value}")
        piece_text = f"{pieces}件" if pieces else "套装"
        set_text = f"{set_key or '套装'}（{piece_text}）"
        if bonus_parts:
            set_text += "：" + "、".join(bonus_parts)
        parts.append(set_text)
    return "；".join(parts)


@register.filter
def gear_tooltip(template, set_map=None) -> str:
    """
    Tooltip with description、逐行属性、套装组成与套装属性。
    """
    if not template:
        return ""
    esc = conditional_escape
    stat_labels = {
        "hp": "生命",
        "force": "武力",
        "intellect": "智力",
        "defense": "防御",
        "agility": "敏捷",
        "luck": "运势",
        "attack": "攻击",
    }
    lines = []
    desc = getattr(template, "description", "") or ""
    if desc:
        lines.append(format_html("{}", esc(desc)))
    attrs = []
    atk = getattr(template, "attack_bonus", 0)
    if atk:
        attrs.append(format_html("{} +{}", esc(stat_labels["attack"]), atk))
    defense_bonus = getattr(template, "defense_bonus", 0)
    if defense_bonus:
        attrs.append(format_html("{} +{}", esc(stat_labels["defense"]), defense_bonus))
    extra_stats = getattr(template, "extra_stats", {}) or {}
    for key, value in extra_stats.items():
        if value is None:
            continue
        label = stat_labels.get(key, key)
        attrs.append(format_html("{} +{}", esc(label), value))
    lines.extend(attrs)

    tpl_set_key = getattr(template, "set_key", "") or ""
    if tpl_set_key and set_map:
        info = set_map.get(tpl_set_key) or {}
        members = info.get("members") or []
        bonus_map = info.get("bonus") or {}
        set_desc = info.get("description") or ""
        if members:
            if set_desc:
                lines.append(format_html("套装：{}", esc(set_desc)))
            else:
                lines.append("套装")
            member_texts = []
            for member in members:
                name = member.get("name") or ""
                slot = member.get("slot") or ""
                equipped = member.get("equipped")
                cls = "equipped" if equipped else "unequipped"
                member_texts.append((cls, esc(f"{slot}·{name}")))
            lines.append(
                format_html(
                    "成员：{}",
                    format_html_join(
                        "，",
                        '<span class="set-member {0}">{1}</span>',
                        member_texts,
                    ),
                )
            )
        if isinstance(bonus_map, dict) and bonus_map:
            bonus_parts = []
            for key, value in bonus_map.items():
                if value is None:
                    continue
                label = stat_labels.get(key, key)
                bonus_parts.append(format_html("{}+{}", esc(label), value))
            if bonus_parts:
                lines.append("套装属性：")
                lines.extend(bonus_parts)
    # Use format_html_join to return a SafeString without needing template `|safe`.
    return format_html_join("", "<div>{}</div>", ((line,) for line in lines))


@register.filter
def attribute_icons(value: int) -> str:
    """
    将属性值转换为图标HTML (Crown=64, Sun=16, Moon=4, Star=1)
    """
    if not value or value < 0:
        return ""

    icons = []
    remaining = int(value)

    for icon, divisor in [('crown', 64), ('sun', 16), ('moon', 4), ('star', 1)]:
        count = remaining // divisor
        remaining %= divisor
        icons.extend([icon] * count)

    return format_html_join(
        "",
        '<img src="/static/images/attri/{0}.png" class="attr-icon" alt="{0}">',
        ((icon,) for icon in icons),
    )
