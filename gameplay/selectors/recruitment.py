from __future__ import annotations

from django.core.cache import cache

from common.constants.resources import ResourceType
from guests.services import (
    get_active_guest_recruitment,
    get_pool_recruitment_duration_seconds,
    list_candidates,
    list_pools,
    refresh_guest_recruitments,
)

from ..models import InventoryItem
from ..services import refresh_manor_state
from ..services.utils.cache import CACHE_TIMEOUT_SHORT, CacheKeys, invalidate_recruitment_hall_cache

RECRUITMENT_HALL_CACHE_VERSION = 1


def _recruitment_hall_cache_key(manor_id: int) -> str:
    return f"{CacheKeys.recruitment_hall_context(manor_id)}:v{RECRUITMENT_HALL_CACHE_VERSION}"


def _format_duration_cn(seconds: int) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, sec = divmod(rem, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分钟")
    if sec or not parts:
        parts.append(f"{sec}秒")
    return "".join(parts)


def _serialize_recruit_records(records) -> list[dict]:
    payload: list[dict] = []
    for record in records:
        if not record.guest_id:
            continue
        payload.append(
            {
                "created_at": record.created_at,
                "guest_display_name": record.guest.display_name,
                "guest_rarity": record.guest.rarity,
            }
        )
    return payload


def _build_cached_payload(manor, records_limit: int) -> dict:
    candidates_payload = list(
        list_candidates(manor).values(
            "id",
            "display_name",
            "rarity",
            "rarity_revealed",
        )
    )
    records = list(manor.recruit_records.select_related("guest__template").order_by("-created_at")[:records_limit])
    records_payload = _serialize_recruit_records(records)

    magnifying_glass_items = (
        manor.inventory_items.filter(
            template__key="fangdajing",
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        .select_related("template")
        .order_by("id")
    )
    magnifying_payload = [
        {
            "id": item.id,
            "quantity": item.quantity,
            "template_name": item.template.name,
        }
        for item in magnifying_glass_items
    ]

    return {
        "candidates_payload": candidates_payload,
        "candidate_count": len(candidates_payload),
        "records_payload": records_payload,
        "magnifying_glass_items": magnifying_payload,
    }


def get_recruitment_hall_context(manor, records_limit: int) -> dict:
    refresh_manor_state(manor)
    completed = refresh_guest_recruitments(manor)
    if completed > 0:
        invalidate_recruitment_hall_cache(int(manor.id))

    pools = list(list_pools(core_only=True, include_entries=False))
    for pool in pools:
        duration_seconds = get_pool_recruitment_duration_seconds(pool)
        setattr(pool, "recruit_duration_seconds", duration_seconds)
        setattr(pool, "recruit_duration_display", _format_duration_cn(duration_seconds))
    active_recruitment = get_active_guest_recruitment(manor)

    cache_key = _recruitment_hall_cache_key(int(manor.id))
    cached_payload = cache.get(cache_key)
    if cached_payload is None:
        cached_payload = _build_cached_payload(manor, records_limit)
        cache.set(cache_key, cached_payload, timeout=CACHE_TIMEOUT_SHORT)

    return {
        "manor": manor,
        "resource_labels": dict(ResourceType.choices),
        "pools": pools,
        "candidates": cached_payload["candidates_payload"],
        "candidates_payload": cached_payload["candidates_payload"],
        "candidate_count": cached_payload["candidate_count"],
        "active_recruitment": active_recruitment,
        "records": cached_payload["records_payload"],
        "magnifying_glass_items": cached_payload["magnifying_glass_items"],
    }
