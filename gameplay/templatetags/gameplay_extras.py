from django import template

register = template.Library()


@register.filter
def get_label(mapping, key):
    if isinstance(mapping, dict):
        return mapping.get(key, key)
    return key


@register.filter
def get_item(mapping, key):
    """Get item from dictionary by key"""
    if isinstance(mapping, dict):
        return mapping.get(key)
    return None


@register.filter
def drop_value(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number < 1:
        return f"{int(number * 100)}% 概率"
    if number.is_integer():
        return str(int(number))
    return str(number)


@register.filter
def guest_key(entry):
    """
    从 enemy_guests 条目中提取门客 key。

    支持两种格式：
    - 字符串: 直接返回
    - 字典: 返回 entry["key"]

    用法: {{ entry|guest_key }}
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("key", "")
    return ""


@register.filter
def guest_label(entry, labels):
    """
    从 enemy_guests 条目中提取展示名称。

    支持两种格式：
    - 字典: 优先使用 entry["label"]，否则回退到 entry["key"]
    - 字符串: 直接使用 key
    """
    key = ""
    if isinstance(entry, dict):
        label = entry.get("label")
        if label:
            return label
        key = entry.get("key", "")
    elif isinstance(entry, str):
        key = entry
    if isinstance(labels, dict):
        return labels.get(key, key)
    return key


@register.filter
def building_desc(building_key):
    """
    从 YAML 配置获取建筑描述。

    用法: {{ building.building_type.key|building_desc }}
    """
    from gameplay.services.building import get_building_description
    return get_building_description(building_key)
