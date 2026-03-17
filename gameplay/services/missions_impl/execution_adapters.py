from __future__ import annotations

from typing import Any, Dict, List


def normalize_mapping(raw: Any) -> Dict[str, object]:
    if isinstance(raw, dict):
        return raw
    return {}


def normalize_guest_configs(raw: Any) -> List[Any]:
    if not isinstance(raw, (list, tuple, set)):
        return []
    normalized: List[Any] = []
    for entry in raw:
        if isinstance(entry, str):
            key = entry.strip()
            if key:
                normalized.append(key)
        elif isinstance(entry, dict):
            normalized.append(entry)
    return normalized


def load_locked_mission_run(*, mission_run_model: Any, run_pk: int):
    return (
        mission_run_model.objects.select_for_update()
        .select_related("mission", "manor", "battle_report")
        .prefetch_related("guests")
        .filter(pk=run_pk)
        .first()
    )


def mark_run_completed(locked_run: Any, now: Any) -> None:
    locked_run.status = locked_run.Status.COMPLETED
    locked_run.completed_at = now
    locked_run.save(update_fields=["status", "completed_at"])


def build_mission_drops_with_salvage_adapter(
    locked_run: Any,
    report: Any,
    player_side: str,
    *,
    logger: Any,
    build_mission_drops_with_salvage,
    resolve_defense_drops_if_missing,
) -> Dict[str, int]:
    return build_mission_drops_with_salvage(
        locked_run,
        report,
        player_side,
        logger=logger,
        resolve_defense_drops_if_missing=resolve_defense_drops_if_missing,
    )
