"""
回合顺序决定
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, List, Tuple

from .utils import alive

if TYPE_CHECKING:
    from ..combatants import Combatant


def determine_turn_order(
    attacker_team: List["Combatant"],
    defender_team: List["Combatant"],
    rng: random.Random,
) -> List["Combatant"]:
    participants = alive(attacker_team) + alive(defender_team)
    if not participants:
        return []
    weighted: List[Tuple[float, float, "Combatant"]] = []
    for combatant in participants:
        initiative = combatant.agility + rng.uniform(0, 5)
        weighted.append((initiative, rng.random(), combatant))
    weighted.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in weighted]
