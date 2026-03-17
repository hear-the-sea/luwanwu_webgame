from __future__ import annotations

import logging
import random
from contextlib import contextmanager
from typing import Any, Callable, Dict, Generator, List

from django.db import transaction

from guests.guest_combat_stats import is_live_guest_model
from guests.models import Guest, GuestStatus

from . import execution as _execution
from .combatants_pkg import (
    build_ai_guests,
    build_guest_combatants,
    build_named_ai_guests,
    generate_ai_loadout,
    normalize_troop_loadout,
)
from .constants import DEFAULT_BATTLE_TYPE, MAX_SQUAD
from .execution import BattleOptions
from .execution import execute_battle as _execute_battle
from .models import BattleReport

logger = logging.getLogger(__name__)

_extract_defender_tech_profile = _execution._extract_defender_tech_profile
validate_troop_capacity = _execution.validate_troop_capacity


def _collect_guest_ids(guests: List[Guest]) -> list[int]:
    return [int(guest.id) for guest in guests if guest.pk]


def _collect_manor_ids(manor, *guest_groups: List[Guest] | None) -> list[int]:
    manor_ids: set[int] = set()
    if getattr(manor, "pk", None):
        manor_ids.add(int(manor.pk))

    for guests in guest_groups:
        for guest in guests or []:
            guest_manor_id = getattr(guest, "manor_id", None)
            if guest_manor_id is None:
                guest_manor = getattr(guest, "manor", None)
                guest_manor_id = getattr(guest_manor, "pk", None)
            if guest_manor_id is None:
                continue
            try:
                parsed_id = int(guest_manor_id)
            except (TypeError, ValueError):
                continue
            if parsed_id > 0:
                manor_ids.add(parsed_id)
    return sorted(manor_ids)


def _lock_manor_rows(manor_ids: list[int]) -> None:
    if not manor_ids:
        return

    from gameplay.models import Manor

    locked_ids = set(
        Manor.objects.select_for_update().filter(pk__in=manor_ids).order_by("id").values_list("id", flat=True)
    )
    missing_ids = [manor_id for manor_id in manor_ids if manor_id not in locked_ids]
    if missing_ids:
        raise ValueError("部分庄园不存在，无法执行战斗")


def _lock_guest_rows(guest_ids: list[int]) -> list[Guest]:
    # Enforce ordering to prevent deadlocks
    return list(Guest.objects.select_for_update().filter(id__in=guest_ids).order_by("id"))


def _validate_locked_guest_statuses(locked_guests: list[Guest]) -> None:
    for guest in locked_guests:
        if guest.status == GuestStatus.DEPLOYED:
            raise ValueError(f"门客 {guest.display_name} 正在战斗中，请稍后再试")
        if guest.status == GuestStatus.WORKING:
            raise ValueError(f"门客 {guest.display_name} 正在打工中，无法出征")
        if guest.status == GuestStatus.INJURED:
            raise ValueError(f"门客 {guest.display_name} 处于重伤状态，请先治疗")


def _mark_locked_guests_deployed(locked_guests: list[Guest]) -> None:
    for guest in locked_guests:
        guest.status = GuestStatus.DEPLOYED
    if locked_guests:
        Guest.objects.bulk_update(locked_guests, ["status"])


def _refresh_guest_instances(guests: List[Guest]) -> None:
    for guest in guests:
        if guest.pk:
            guest.refresh_from_db()


def _release_deployed_guests(guest_ids: list[int]) -> None:
    Guest.objects.filter(id__in=guest_ids, status=GuestStatus.DEPLOYED).update(status=GuestStatus.IDLE)


def _validate_attacker_guest_ownership(manor, guests: List[Guest]) -> None:
    manor_pk = getattr(manor, "pk", None)
    if not manor_pk:
        return

    unresolved_ids: list[int] = []
    for guest in guests:
        guest_pk = getattr(guest, "pk", None)
        if not guest_pk:
            continue
        is_snapshot_proxy = bool(getattr(guest, "is_battle_snapshot_proxy", False))

        guest_manor_id = getattr(guest, "manor_id", None)
        if guest_manor_id is None:
            guest_manor = getattr(guest, "manor", None)
            guest_manor_id = getattr(guest_manor, "pk", None)

        if guest_manor_id is None:
            if is_snapshot_proxy:
                # Historical snapshot replay should not depend on current DB ownership.
                continue
            unresolved_ids.append(int(guest_pk))
            continue

        try:
            parsed_manor_id = int(guest_manor_id)
        except (TypeError, ValueError):
            if is_snapshot_proxy:
                continue
            unresolved_ids.append(int(guest_pk))
            continue

        if parsed_manor_id != int(manor_pk):
            raise ValueError("攻击方门客必须属于当前庄园")

    if not unresolved_ids:
        return

    owned_ids = set(Guest.objects.filter(id__in=unresolved_ids, manor_id=manor_pk).values_list("id", flat=True))
    if len(owned_ids) != len(set(unresolved_ids)):
        raise ValueError("攻击方门客必须属于当前庄园")


def _build_defender_guest_and_loadout(
    defender_guests: List[Guest] | None,
    defender_setup: Dict[str, Any] | None,
    defender_limit: int,
    fill_default_troops: bool,
    rng,
    now,
    defender_guest_level: int,
    defender_guest_bonuses: Dict[str, float],
    defender_guest_skills: List[str] | None,
):
    if defender_guests is not None:
        from guests.services.health import recover_guest_hp

        for guest in defender_guests[:defender_limit]:
            if is_live_guest_model(guest) and guest.pk:
                recover_guest_hp(guest, now=now)
        defender_guests_comb = build_guest_combatants(defender_guests, side="defender", limit=defender_limit)
        loadout_raw = defender_setup.get("troop_loadout") if isinstance(defender_setup, dict) else None
        defender_loadout = normalize_troop_loadout(
            loadout_raw if isinstance(loadout_raw, dict) else None,
            default_if_empty=fill_default_troops,
        )
        return defender_guests_comb, defender_loadout

    if isinstance(defender_setup, dict):
        guest_keys_raw = defender_setup.get("guest_keys")
        loadout_raw = defender_setup.get("troop_loadout")
        guest_keys: list[str | Dict[str, Any]] = []
        if isinstance(guest_keys_raw, (list, tuple, set)):
            for entry in guest_keys_raw:
                if isinstance(entry, str) and entry.strip():
                    guest_keys.append(entry.strip())
                elif isinstance(entry, dict):
                    guest_keys.append(entry)
        defender_templates = build_named_ai_guests(guest_keys, level=defender_guest_level)
        defender_guests_comb = build_guest_combatants(
            defender_templates,
            side="defender",
            limit=defender_limit,
            stat_bonuses=defender_guest_bonuses,
            override_skill_keys=defender_guest_skills,
        )
        defender_loadout = normalize_troop_loadout(
            loadout_raw if isinstance(loadout_raw, dict) else None,
            default_if_empty=fill_default_troops,
        )
        return defender_guests_comb, defender_loadout

    defender_loadout = generate_ai_loadout(rng)
    ai_guest_pool = build_ai_guests(rng)
    defender_guests_comb = build_guest_combatants(ai_guest_pool, side="defender", limit=defender_limit)
    return defender_guests_comb, defender_loadout


@contextmanager
def lock_guests_for_battle(
    guests: List[Guest],
    manor=None,
    *,
    other_guests: List[Guest] | None = None,
) -> Generator[List[Guest], None, None]:
    """
    获取门客的战斗锁，防止并发战斗。

    使用 select_for_update 实现行级锁，确保同一门客不会同时参与多场战斗。
    战斗期间门客状态设为 DEPLOYED，战斗结束后恢复。

    Args:
        guests: 要锁定的门客列表
        manor: 可选庄园对象。提供时会先锁定庄园行，统一锁顺序为 Manor -> Guest

    Yields:
        锁定后的门客列表

    Raises:
        ValueError: 如果门客已在战斗中或状态不是空闲
    """
    other_guests = other_guests or []
    if not guests and not other_guests:
        yield []
        return

    primary_guest_ids = _collect_guest_ids(guests)
    secondary_guest_ids = _collect_guest_ids(other_guests)
    guest_ids = sorted(set(primary_guest_ids + secondary_guest_ids))
    if not guest_ids:
        yield guests
        return

    locked = False
    try:
        with transaction.atomic():
            # Keep the DB transaction limited to lock acquisition + state transition.
            _lock_manor_rows(_collect_manor_ids(manor, guests, other_guests))
            locked_guests = _lock_guest_rows(guest_ids)
            locked_guest_map = {guest.id: guest for guest in locked_guests}
            missing_guest_ids = [guest_id for guest_id in guest_ids if guest_id not in locked_guest_map]
            if missing_guest_ids:
                raise ValueError("部分门客不存在，无法执行战斗")

            locked_primary = [locked_guest_map[guest_id] for guest_id in primary_guest_ids]
            locked_secondary = [locked_guest_map[guest_id] for guest_id in secondary_guest_ids]
            locked_participants = list({guest.id: guest for guest in locked_primary + locked_secondary}.values())

            _validate_locked_guest_statuses(locked_participants)
            _mark_locked_guests_deployed(locked_participants)
            locked = True

        _refresh_guest_instances(guests)
        _refresh_guest_instances(other_guests)
        yield guests
    finally:
        if locked:
            with transaction.atomic():
                _release_deployed_guests(guest_ids)


def simulate_report(
    manor,
    battle_type: str = DEFAULT_BATTLE_TYPE,
    seed: int | None = None,
    troop_loadout: Dict[str, int] | None = None,
    fill_default_troops: bool = True,
    attacker_guests: List[Guest] | None = None,
    defender_setup: Dict[str, Any] | None = None,
    defender_guests: List[Guest] | None = None,
    defender_max_squad: int | None = None,
    drop_table: Dict[str, Any] | None = None,
    opponent_name: str | None = None,
    travel_seconds: int | None = None,
    auto_reward: bool = True,
    drop_handler: Callable[[Dict[str, int]], None] | None = None,
    rng_source: random.Random | None = None,
    send_message: bool = True,
    max_squad: int | None = None,
    apply_damage: bool = True,
    use_lock: bool = True,
    attacker_tech_levels: Dict[str, int] | None = None,
    attacker_guest_bonuses: Dict[str, float] | None = None,
    attacker_guest_skills: List[str] | None = None,
    attacker_manor=None,
    validate_attacker_troop_capacity: bool = True,
) -> BattleReport:
    """
    Top-level entry point for simulating a battle and producing reports/messages.

    Args:
        manor: 庄园实例
        battle_type: 战斗类型
        seed: 随机种子
        troop_loadout: 兵种配置
        fill_default_troops: troop_loadout 为空/全0时是否填充默认兵力
        attacker_guests: 攻击方门客列表
        defender_setup: 防守方配置
        defender_guests: 防守方门客列表（真实门客，用于PVP等场景）
        defender_max_squad: 防守方最大出战人数（如PVP防守方的游侠宝塔上限）
        drop_table: 掉落表
        opponent_name: 对手名称
        travel_seconds: 行军时间（秒）
        auto_reward: 是否自动发放奖励
        drop_handler: 自定义掉落处理函数
        rng_source: 自定义随机数生成器
        send_message: 是否发送战报消息
        max_squad: 最大出战人数
        apply_damage: 是否应用伤害到门客
        use_lock: 是否使用并发锁（防止门客同时参与多场战斗）
        attacker_tech_levels: 攻击方科技等级字典（可选，供敌方使用）
        attacker_guest_bonuses: 攻击方门客属性加成（可选）
        attacker_guest_skills: 攻击方门客临时技能覆盖（可选）
        attacker_manor: 攻击方科技来源庄园（可选，默认为 manor）
        validate_attacker_troop_capacity: 是否校验攻击方带兵上限（默认开启）

    Returns:
        BattleReport: 战斗报告实例
    """
    # 确定本场上阵人数（默认遵循庄园可上阵上限）
    limit = max_squad or (getattr(manor, "max_squad_size", None) or MAX_SQUAD)

    # 获取出战门客
    if attacker_guests is None:
        guest_qs = manor.guests.select_related("template").prefetch_related("skills")
        total_guests = guest_qs.count()
        # 仅空闲门客可出征，重伤门客无法出征
        guests = list(guest_qs.filter(status=GuestStatus.IDLE).order_by("-template__rarity", "-level")[:limit])
        if not guests:
            if total_guests > 0:
                injured_count = guest_qs.filter(status=GuestStatus.INJURED).count()
                if injured_count > 0:
                    raise ValueError(f"有{injured_count}名门客处于重伤状态，请使用药品治疗后再出征")
                raise ValueError("仅空闲门客可出征，请先让门客空闲后再尝试战斗")
            raise ValueError("请先招募门客后再尝试战斗")
    else:
        guests = attacker_guests
        if not guests:
            raise ValueError("请选择可出征的门客")
        _validate_attacker_guest_ownership(manor, guests)

    defender_limit = defender_max_squad or limit
    active_guests = guests[:limit]

    # 使用并发锁执行战斗（防止同一门客同时参与多场战斗）
    options = BattleOptions(
        battle_type=battle_type,
        seed=seed,
        troop_loadout=troop_loadout,
        fill_default_troops=fill_default_troops,
        defender_setup=defender_setup,
        defender_guests=defender_guests,
        defender_limit=defender_limit,
        drop_table=drop_table,
        opponent_name=opponent_name,
        travel_seconds=travel_seconds,
        auto_reward=auto_reward,
        drop_handler=drop_handler,
        rng_source=rng_source,
        send_message=send_message,
        limit=limit,
        apply_damage=apply_damage,
        attacker_tech_levels=attacker_tech_levels,
        attacker_guest_bonuses=attacker_guest_bonuses,
        attacker_guest_skills=attacker_guest_skills,
        attacker_manor=attacker_manor,
        validate_attacker_troop_capacity=validate_attacker_troop_capacity,
    )

    if use_lock:
        with lock_guests_for_battle(active_guests, manor=manor, other_guests=options.defender_guests):
            return _execute_battle(manor, guests, active_guests, options)
    else:
        # 不使用锁（用于测试或特殊场景）
        return _execute_battle(manor, guests, active_guests, options)
