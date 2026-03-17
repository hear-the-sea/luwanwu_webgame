from __future__ import annotations

GUEST_SALARY_BY_RARITY: dict[str, int] = {
    "black": 500,
    "gray": 1000,
    "green": 2000,
    "red": 3000,
    "blue": 4000,
    "purple": 15000,
    "orange": 30000,
}
DEFAULT_GUEST_SALARY = GUEST_SALARY_BY_RARITY.get("gray", 1000)


def get_guest_salary_for_rarity(rarity: str | None) -> int:
    normalized_rarity = str(rarity or "").strip()
    return GUEST_SALARY_BY_RARITY.get(normalized_rarity, DEFAULT_GUEST_SALARY)
