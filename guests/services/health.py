"""
门客生命值管理服务
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from django.db import transaction
from django.utils import timezone

from core.exceptions import GuestFullHpError, GuestNotIdleError, InsufficientStockError, InvalidHealAmountError
from core.utils import safe_int
from core.utils.time_scale import scale_value

from ..constants import TimeConstants
from ..models import Guest, GuestStatus

if TYPE_CHECKING:
    from gameplay.models import Manor

# 重伤恢复阈值：HP达到此比例时解除重伤状态
INJURY_RECOVERY_THRESHOLD = 0.20
# 重伤自动回血速率（相对普通状态）
INJURED_RECOVERY_RATE_FACTOR = 0.1


def recover_guest_hp(guest: Guest, now: timezone.datetime | None = None) -> None:
    """
    恢复门客生命值。

    从1点到满血耗时24小时，每10分钟检查一次并线性恢复。
    澡堂建筑可提供生命恢复加成（满级200%）。

    重伤门客（INJURED状态）会自动恢复，但速率仅为普通状态的 1/10。
    全局时间流速（GAME_TIME_MULTIPLIER）同样作用于重伤回血。
    """
    now = now or timezone.now()

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
    if hasattr(guest, "manor") and guest.manor:
        hp_multiplier = guest.manor.hp_recovery_multiplier
    status_recovery_factor = INJURED_RECOVERY_RATE_FACTOR if guest.status == GuestStatus.INJURED else 1.0

    recovered = int(
        scale_value(per_second)
        * intervals
        * TimeConstants.HP_RECOVERY_INTERVAL
        * hp_multiplier
        * status_recovery_factor
    )
    new_hp = min(guest.max_hp, guest.current_hp + recovered)
    guest.current_hp = max(1, new_hp)
    guest.last_hp_recovery_at = last + timezone.timedelta(seconds=intervals * TimeConstants.HP_RECOVERY_INTERVAL)
    guest.save(update_fields=["current_hp", "last_hp_recovery_at"])


def heal_guest(guest: Guest, heal_amount: int) -> dict:
    """
    为门客治疗，恢复生命值。

    如果门客处于重伤状态且治疗后HP达到阈值（当前为20%）以上，自动解除重伤状态。

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
    if guest.status not in {GuestStatus.IDLE, GuestStatus.INJURED}:
        raise GuestNotIdleError(guest)
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


def _load_locked_medicine_item(manor: Manor, item_id: int):
    from gameplay.models import InventoryItem, ItemTemplate

    locked_item = (
        InventoryItem.objects.select_for_update()
        .select_related("template")
        .filter(
            pk=item_id,
            manor=manor,
            template__effect_type=ItemTemplate.EffectType.MEDICINE,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )
        .first()
    )
    if not locked_item:
        raise ValueError("道具不存在或不属于您的庄园")
    if locked_item.quantity <= 0:
        raise InsufficientStockError(locked_item.template.name, 1, locked_item.quantity)
    return locked_item


@transaction.atomic
def use_medicine_item_for_guest(manor: Manor, guest: Guest, item_id: int, heal_amount: int) -> Dict[str, Any]:
    """
    对单个门客使用药品（原子化版本）。

    关键保证：
    - 治疗效果与道具扣减在同一事务中完成
    - 任一步失败都会整体回滚，避免“先生效后扣失败”导致状态不一致
    - 锁顺序统一为 Manor -> InventoryItem -> Guest
    """
    from gameplay.models import Manor as ManorModel
    from gameplay.services.inventory.core import consume_inventory_item_locked

    ManorModel.objects.select_for_update().get(pk=manor.pk)
    locked_item = _load_locked_medicine_item(manor, item_id)

    locked_guest = Guest.objects.select_for_update().select_related("template").filter(pk=guest.pk, manor=manor).first()
    if not locked_guest:
        raise ValueError("门客不存在或不属于您的庄园")

    result = heal_guest(locked_guest, heal_amount)
    consume_inventory_item_locked(locked_item, 1)

    remaining_quantity = 0
    if locked_item.pk:
        remaining_quantity = safe_int(locked_item.quantity, default=0, min_val=0) or 0

    return {
        "healed": safe_int(result.get("healed"), default=0, min_val=0) or 0,
        "new_hp": safe_int(locked_guest.current_hp, default=0, min_val=0) or 0,
        "max_hp": safe_int(locked_guest.max_hp, default=1, min_val=1) or 1,
        "status": locked_guest.status,
        "status_display": locked_guest.get_status_display(),
        "injury_cured": bool(result.get("injury_cured", False)),
        "remaining_item_quantity": remaining_quantity,
    }
