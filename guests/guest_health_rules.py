from __future__ import annotations

INJURY_RECOVERY_THRESHOLD = 0.20
INJURED_RECOVERY_RATE_FACTOR = 0.1


def compute_recovered_hp(
    *,
    current_hp: int,
    max_hp: int,
    elapsed_seconds: float,
    recovery_interval_seconds: int,
    scaled_recovery_per_second: float,
    hp_multiplier: float,
    is_injured: bool,
    injured_recovery_rate_factor: float = INJURED_RECOVERY_RATE_FACTOR,
) -> tuple[int, int]:
    if current_hp >= max_hp:
        return max_hp, 0

    intervals = int(elapsed_seconds // recovery_interval_seconds)
    if intervals <= 0:
        return max(1, current_hp), 0

    status_recovery_factor = injured_recovery_rate_factor if is_injured else 1.0
    recovered = int(
        scaled_recovery_per_second * intervals * recovery_interval_seconds * hp_multiplier * status_recovery_factor
    )
    new_hp = min(max_hp, current_hp + recovered)
    return max(1, new_hp), intervals


def should_clear_injured_status(
    *,
    current_hp: int,
    max_hp: int,
    threshold_ratio: float = INJURY_RECOVERY_THRESHOLD,
) -> bool:
    if max_hp <= 0:
        return False
    return (current_hp / max_hp) >= threshold_ratio
