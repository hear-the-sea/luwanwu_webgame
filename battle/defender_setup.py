from __future__ import annotations

from typing import Any


def _normalize_optional_mapping(raw: Any, *, contract_name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    raise AssertionError(f"invalid {contract_name}: {raw!r}")


def _normalize_guest_configs(raw: Any) -> list[str | dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple, set)):
        raise AssertionError(f"invalid battle defender guest_keys payload: {raw!r}")
    normalized: list[str | dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, str):
            key = entry.strip()
            if not key:
                raise AssertionError(f"invalid battle defender guest_keys entry: {entry!r}")
            normalized.append(key)
        elif isinstance(entry, dict):
            normalized.append(entry)
        else:
            raise AssertionError(f"invalid battle defender guest_keys entry: {entry!r}")
    return normalized


def _normalize_troop_loadout_input(raw: Any) -> dict[str, int] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    raise AssertionError(f"invalid battle defender troop_loadout payload: {raw!r}")


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
    normalized_setup = _normalize_optional_mapping(
        defender_setup,
        contract_name="battle defender setup payload",
    )

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
