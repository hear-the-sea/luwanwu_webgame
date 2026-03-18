from __future__ import annotations

from typing import Any


def _normalize_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def _normalize_guest_configs(raw: Any) -> list[str | dict[str, Any]]:
    if not isinstance(raw, (list, tuple, set)):
        return []
    normalized: list[str | dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, str):
            key = entry.strip()
            if key:
                normalized.append(key)
        elif isinstance(entry, dict):
            normalized.append(entry)
    return normalized


def _normalize_troop_loadout_input(raw: Any) -> dict[str, int] | None:
    if isinstance(raw, dict):
        return raw
    return None


def build_defender_guest_and_loadout(
    *,
    defender_guests,
    defender_setup,
    defender_limit: int,
    fill_default_troops: bool,
    rng,
    now,
    defender_guest_level: int,
    defender_guest_bonuses: dict[str, float],
    defender_guest_skills: list[str] | None,
    is_live_guest_model_fn,
    recover_guest_hp_fn,
    build_guest_combatants_fn,
    build_named_ai_guests_fn,
    generate_ai_loadout_fn,
    normalize_troop_loadout_fn,
    build_ai_guests_fn,
):
    normalized_setup = _normalize_mapping(defender_setup)

    if defender_guests is not None:
        for guest in defender_guests[:defender_limit]:
            if is_live_guest_model_fn(guest) and getattr(guest, "pk", None):
                recover_guest_hp_fn(guest, now=now)
        defender_guests_comb = build_guest_combatants_fn(defender_guests, side="defender", limit=defender_limit)
        defender_loadout = normalize_troop_loadout_fn(
            _normalize_troop_loadout_input(normalized_setup.get("troop_loadout")),
            default_if_empty=fill_default_troops,
        )
        return defender_guests_comb, defender_loadout

    if normalized_setup:
        defender_guest_keys = _normalize_guest_configs(normalized_setup.get("guest_keys"))
        defender_templates = build_named_ai_guests_fn(defender_guest_keys, level=defender_guest_level)
        defender_guests_comb = build_guest_combatants_fn(
            defender_templates,
            side="defender",
            limit=defender_limit,
            stat_bonuses=defender_guest_bonuses,
            override_skill_keys=defender_guest_skills,
        )
        defender_loadout = normalize_troop_loadout_fn(
            _normalize_troop_loadout_input(normalized_setup.get("troop_loadout")),
            default_if_empty=fill_default_troops,
        )
        return defender_guests_comb, defender_loadout

    defender_loadout = generate_ai_loadout_fn(rng)
    ai_guest_pool = build_ai_guests_fn(rng)
    defender_guests_comb = build_guest_combatants_fn(ai_guest_pool, side="defender", limit=defender_limit)
    return defender_guests_comb, defender_loadout
