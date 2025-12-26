"""
门客生命值管理服务
"""

from __future__ import annotations

from django.utils import timezone

from core.exceptions import GuestFullHpError, InvalidHealAmountError
from core.utils.time_scale import scale_value
from ..constants import TimeConstants
from ..models import Guest, GuestStatus

# 重伤恢复阈值：HP达到此比例时解除重伤状态
INJURY_RECOVERY_THRESHOLD = 0.20


def recover_guest_hp(guest: Guest, now: timezone.datetime | None = None) -> None:
    """
    恢复门客生命值。

    从1点到满血耗时24小时，每10分钟检查一次并线性恢复。
    澡堂建筑可提供生命恢复加成（满级200%）。

    重伤门客（INJURED状态）不会自动恢复，需要使用药品治疗。
    """
    now = now or timezone.now()

    # 重伤门客无法自动恢复
    if guest.status == GuestStatus.INJURED:
        return

    last = guest.last_hp_recovery_at or guest.created_at or now
    if guest.current_hp >= guest.max_hp:
        if last != now:
            guest.last_hp_recovery_at = now
            guest.save(update_fields=["last_hp_recovery_at"])
        return
    elapsed = (now - last).total_seconds()
    if elapsed < TimeConstants.HP_RECOVERY_INTERVAL:
        return
    intervals = int(elapsed // TimeConstants.HP_RECOVERY_INTERVAL)
    # 从1点到满血耗时24小时，线性恢复
    per_second = max(1, (guest.max_hp - 1) / TimeConstants.HP_FULL_RECOVERY_TIME)

    # 应用澡堂加成
    hp_multiplier = 1.0
    if hasattr(guest, 'manor') and guest.manor:
        hp_multiplier = guest.manor.hp_recovery_multiplier

    recovered = int(scale_value(per_second) * intervals * TimeConstants.HP_RECOVERY_INTERVAL * hp_multiplier)
    new_hp = min(guest.max_hp, guest.current_hp + recovered)
    guest.current_hp = max(1, new_hp)
    guest.last_hp_recovery_at = last + timezone.timedelta(seconds=intervals * TimeConstants.HP_RECOVERY_INTERVAL)
    guest.save(update_fields=["current_hp", "last_hp_recovery_at"])


def heal_guest(guest: Guest, heal_amount: int) -> dict:
    """
    为门客治疗，恢复生命值。

    如果门客处于重伤状态且治疗后HP达到30%以上，自动解除重伤状态。

    Args:
        guest: 门客实例
        heal_amount: 治疗量

    Returns:
        包含治疗结果的字典：
        - healed: 实际恢复的HP
        - new_hp: 治疗后的HP
        - injury_cured: 是否解除了重伤状态

    Raises:
        InvalidHealAmountError: 治疗量无效
        GuestFullHpError: 门客已满血
    """
    if heal_amount <= 0:
        raise InvalidHealAmountError()
    if guest.current_hp >= guest.max_hp:
        raise GuestFullHpError(guest)

    old_hp = guest.current_hp
    new_hp = min(guest.max_hp, guest.current_hp + heal_amount)
    healed = new_hp - old_hp

    guest.current_hp = new_hp
    guest.last_hp_recovery_at = timezone.now()

    update_fields = ["current_hp", "last_hp_recovery_at"]
    injury_cured = False

    # 检查是否解除重伤状态
    if guest.status == GuestStatus.INJURED:
        hp_ratio = new_hp / guest.max_hp
        if hp_ratio >= INJURY_RECOVERY_THRESHOLD:
            guest.status = GuestStatus.IDLE
            update_fields.append("status")
            injury_cured = True

    guest.save(update_fields=update_fields)

    return {
        "healed": healed,
        "new_hp": new_hp,
        "injury_cured": injury_cured,
    }
