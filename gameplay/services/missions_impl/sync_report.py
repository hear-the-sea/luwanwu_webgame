from __future__ import annotations

from typing import Dict

from ...models import Manor, MissionTemplate


def generate_sync_battle_report(
    *,
    manor: Manor,
    mission: MissionTemplate,
    guests,
    loadout: Dict[str, int],
    defender_setup: Dict[str, object],
    travel_seconds: int,
    seed=None,
):
    """Sync battle report helper used when Celery is unavailable."""

    from battle.services import simulate_report

    if mission.is_defense:
        from battle.combatants import build_named_ai_guests
        from gameplay.services.technology import get_guest_stat_bonuses, resolve_enemy_tech_levels

        tech_conf = mission.enemy_technology or {}
        attacker_guest_level = int(tech_conf.get("guest_level", 50)) if tech_conf else 50
        attacker_guests = build_named_ai_guests(mission.enemy_guests or [], level=attacker_guest_level)
        attacker_tech_levels = resolve_enemy_tech_levels(tech_conf) if tech_conf else {}
        attacker_guest_bonuses = get_guest_stat_bonuses(tech_conf) if tech_conf else {}
        attacker_guest_skills = tech_conf.get("guest_skills") or None

        return simulate_report(
            manor=manor,
            battle_type=mission.battle_type or "task",
            seed=seed,
            troop_loadout=mission.enemy_troops or {},
            fill_default_troops=False,
            attacker_guests=attacker_guests,
            defender_setup={"troop_loadout": loadout},
            defender_guests=guests,
            defender_max_squad=len(guests) if guests else None,
            drop_table={},
            opponent_name=mission.name,
            travel_seconds=travel_seconds,
            send_message=False,
            auto_reward=False,
            drop_handler=None,
            max_squad=len(attacker_guests) if attacker_guests else None,
            apply_damage=False,
            use_lock=False,
            attacker_tech_levels=attacker_tech_levels,
            attacker_guest_bonuses=attacker_guest_bonuses or None,
            attacker_guest_skills=attacker_guest_skills,
            attacker_manor=None,
        )

    return simulate_report(
        manor=manor,
        battle_type=mission.battle_type or "task",
        seed=seed,
        troop_loadout=loadout,
        fill_default_troops=False,
        attacker_guests=guests,
        defender_setup=defender_setup,
        drop_table=mission.drop_table or {},
        opponent_name=mission.name,
        travel_seconds=travel_seconds,
        send_message=False,
        auto_reward=False,
        drop_handler=None,
        max_squad=getattr(manor, "max_squad_size", None),
        apply_damage=False,
        use_lock=False,
    )
