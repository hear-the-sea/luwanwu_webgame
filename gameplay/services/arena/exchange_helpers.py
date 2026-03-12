from __future__ import annotations

from django.db.models import Sum


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


def ensure_exchange_daily_limit(
    *,
    arena_exchange_record_model,
    locked_manor,
    reward,
    normalized_quantity: int,
    day_start,
    day_end,
) -> None:
    if reward.daily_limit is None:
        return

    today_exchanged = (
        arena_exchange_record_model.objects.filter(
            manor=locked_manor,
            reward_key=reward.key,
            created_at__gte=day_start,
            created_at__lt=day_end,
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    if today_exchanged + normalized_quantity > reward.daily_limit:
        raise ValueError(f"{reward.name} 今日最多可兑换 {reward.daily_limit} 次")


def grant_exchange_items_locked(
    *,
    fixed_item_grants: dict[str, int],
    random_item_grants: dict[str, int],
    add_item_to_inventory_locked,
    locked_manor,
) -> dict[str, int]:
    for item_key, total_amount in fixed_item_grants.items():
        add_item_to_inventory_locked(locked_manor, item_key, total_amount)
    for item_key, amount in random_item_grants.items():
        add_item_to_inventory_locked(locked_manor, item_key, amount)
    return merge_item_grants(fixed_item_grants, random_item_grants)


def create_exchange_record(
    *,
    arena_exchange_record_model,
    locked_manor,
    reward,
    total_cost: int,
    normalized_quantity: int,
    payload: dict[str, dict[str, int]],
):
    return arena_exchange_record_model.objects.create(
        manor=locked_manor,
        reward_key=reward.key,
        reward_name=reward.name,
        cost_coins=total_cost,
        quantity=normalized_quantity,
        payload=payload,
    )


def send_exchange_success_message(
    *,
    create_message_func,
    message_kind,
    locked_manor,
    reward,
    total_cost: int,
    normalized_quantity: int,
    summary: str,
    logger,
) -> None:
    try:
        create_message_func(
            manor=locked_manor,
            kind=message_kind,
            title=f"竞技场兑换成功：{reward.name}",
            body=f"消耗角斗币 {total_cost}，兑换数量 {normalized_quantity}。{summary}。",
        )
    except Exception as exc:
        logger.warning(
            "arena exchange message failed: manor_id=%s reward_key=%s quantity=%s error=%s",
            locked_manor.id,
            reward.key,
            normalized_quantity,
            exc,
            exc_info=True,
        )
