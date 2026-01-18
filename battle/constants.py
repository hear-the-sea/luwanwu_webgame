from typing import Dict

MAX_SQUAD = 5
MAX_ROUNDS = 32
DEFAULT_BATTLE_TYPE = "skirmish"

BATTLE_TYPES: Dict[str, dict] = {
    DEFAULT_BATTLE_TYPE: {
        "name": "乱军试炼",
        "description": "与乱军短兵相接，侦察敌情并掠夺补给",
        "loot_pool": {
            # Use literal resource keys to avoid importing gameplay at import-time (reduces app coupling).
            "grain": 300,
            "silver": 200,
        },
    },
    "task1": {
        "name": "任务战斗",
        "description": "任务华山论剑",
        "loot_pool": {},
    },
}


def get_battle_config(battle_type: str) -> dict:
    return BATTLE_TYPES.get(battle_type, BATTLE_TYPES[DEFAULT_BATTLE_TYPE])

