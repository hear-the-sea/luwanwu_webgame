from __future__ import annotations


def normalize_exchange_quantity(quantity: int) -> int:
    normalized_quantity = int(quantity or 0)
    if normalized_quantity <= 0:
        raise ValueError("兑换数量无效")
    return normalized_quantity


def scale_reward_resources(resources: dict[str, int], quantity: int) -> dict[str, int]:
    return {key: amount * quantity for key, amount in resources.items()}


def scale_reward_items(items: dict[str, int], quantity: int) -> dict[str, int]:
    return {key: amount * quantity for key, amount in items.items()}


def merge_item_grants(*grant_maps: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for grant_map in grant_maps:
        for item_key, amount in grant_map.items():
            merged[item_key] = merged.get(item_key, 0) + int(amount)
    return merged


def build_exchange_payload(
    *,
    credited_resources: dict[str, int],
    overflow_resources: dict[str, int],
    granted_items: dict[str, int],
) -> dict[str, dict[str, int]]:
    return {
        "resources": credited_resources,
        "resources_overflow": overflow_resources,
        "items": granted_items,
    }


def build_exchange_summary(
    *,
    credited_resources: dict[str, int],
    overflow_resources: dict[str, int],
    granted_items: dict[str, int],
) -> str:
    summary_parts: list[str] = []
    if credited_resources:
        summary_parts.append("资源已发放")
    if granted_items:
        summary_parts.append("道具已入库")
    if overflow_resources:
        summary_parts.append("部分资源因容量上限溢出")
    return "，".join(summary_parts) if summary_parts else "奖励已处理"
