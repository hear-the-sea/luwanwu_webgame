from __future__ import annotations

import logging
import random
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generator, List

from django.db import transaction
from django.utils import timezone

from guests.models import Guest, GuestStatus

from .combatants import (
    Combatant,
    assign_agility_based_priorities,
    build_ai_guests,
    build_guest_combatants,
    build_named_ai_guests,
    build_troop_combatants,
    generate_ai_loadout,
    normalize_troop_loadout,
    serialize_guest_for_report,
)
from .constants import DEFAULT_BATTLE_TYPE, MAX_SQUAD, get_battle_config
from .models import BattleReport
from .rewards import dispatch_battle_message, grant_battle_rewards
from .simulation_core import build_rng, simulate_battle

logger = logging.getLogger(__name__)


@dataclass
class BattleOptions:
    """
    Encapsulates configuration and optional parameters for battle execution.
    """

    battle_type: str = DEFAULT_BATTLE_TYPE
    seed: int | None = None
    troop_loadout: Dict[str, int] | None = None
    fill_default_troops: bool = True
    defender_setup: Dict[str, Any] | None = None
    defender_guests: List[Guest] | None = None
    defender_limit: int = MAX_SQUAD
    drop_table: Dict[str, Any] | None = None
    opponent_name: str | None = None
    travel_seconds: int | None = None
    auto_reward: bool = True
    drop_handler: Callable[[Dict[str, int]], None] | None = None
    rng_source: random.Random | None = None
    send_message: bool = True
    limit: int = MAX_SQUAD
    apply_damage: bool = True
    attacker_tech_levels: Dict[str, int] | None = None
    attacker_guest_bonuses: Dict[str, float] | None = None
    attacker_guest_skills: List[str] | None = None
    attacker_manor: Any | None = None
    validate_attacker_troop_capacity: bool = True


def _normalize_mapping(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_skill_keys(raw: Any) -> List[str] | None:
    if not isinstance(raw, (list, tuple, set)):
        return None
    keys = [str(item).strip() for item in raw if str(item).strip()]
    return keys or None


def _normalize_guest_configs(raw: Any) -> List[str | Dict[str, Any]]:
    if not isinstance(raw, (list, tuple, set)):
        return []
    normalized: List[str | Dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, str):
            key = entry.strip()
            if key:
                normalized.append(key)
        elif isinstance(entry, dict):
            normalized.append(entry)
    return normalized


def _normalize_troop_loadout_input(raw: Any) -> Dict[str, int] | None:
    if isinstance(raw, dict):
        return raw
    return None


def _collect_guest_ids(guests: List[Guest]) -> list[int]:
    return [int(guest.id) for guest in guests if guest.pk]


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


def _recover_guest_hp_batch(guests: List[Guest], now) -> None:
    from guests.services.health import recover_guest_hp

    for guest in guests:
        if getattr(guest, "pk", None):
            recover_guest_hp(guest, now=now)


def _resolve_battle_rng(seed: int | None, rng_source: random.Random | None) -> tuple[int, random.Random]:
    final_seed, rng_fallback = build_rng(seed)
    return final_seed, (rng_source or rng_fallback)


def _extract_defender_tech_profile(defender_setup: Dict[str, Any] | None) -> tuple[dict, int, dict, List[str] | None]:
    defender_tech_levels: dict[str, int] = {}
    defender_guest_level = 50
    defender_guest_bonuses: dict[str, float] = {}
    defender_guest_skills: List[str] | None = None

    normalized_setup = _normalize_mapping(defender_setup)
    if not normalized_setup:
        return defender_tech_levels, defender_guest_level, defender_guest_bonuses, defender_guest_skills

    tech_conf = _normalize_mapping(normalized_setup.get("technology"))
    if not tech_conf:
        return defender_tech_levels, defender_guest_level, defender_guest_bonuses, defender_guest_skills

    from core.game_data.technology import get_guest_stat_bonuses, resolve_enemy_tech_levels

    defender_tech_levels = resolve_enemy_tech_levels(tech_conf)
    if "guest_level" in tech_conf:
        defender_guest_level = max(1, _coerce_int(tech_conf.get("guest_level", 50), 50))
    defender_guest_bonuses = get_guest_stat_bonuses(tech_conf)
    defender_guest_skills = _normalize_skill_keys(tech_conf.get("guest_skills"))

    return defender_tech_levels, defender_guest_level, defender_guest_bonuses, defender_guest_skills


def _build_defender_guest_and_loadout(
    defender_guests: List[Guest] | None,
    defender_setup: Dict[str, Any] | None,
    defender_limit: int,
    fill_default_troops: bool,
    rng: random.Random,
    now,
    defender_guest_level: int,
    defender_guest_bonuses: Dict[str, float],
    defender_guest_skills: List[str] | None,
) -> tuple[list[Combatant], Dict[str, int]]:
    normalized_setup = _normalize_mapping(defender_setup)

    if defender_guests is not None:
        _recover_guest_hp_batch(defender_guests[:defender_limit], now)
        defender_guests_comb = build_guest_combatants(defender_guests, side="defender", limit=defender_limit)
        defender_loadout = normalize_troop_loadout(
            _normalize_troop_loadout_input(normalized_setup.get("troop_loadout")),
            default_if_empty=fill_default_troops,
        )
        return defender_guests_comb, defender_loadout

    if normalized_setup:
        defender_guest_keys = _normalize_guest_configs(normalized_setup.get("guest_keys"))
        defender_templates = build_named_ai_guests(defender_guest_keys, level=defender_guest_level)
        defender_guests_comb = build_guest_combatants(
            defender_templates,
            side="defender",
            limit=defender_limit,
            stat_bonuses=defender_guest_bonuses,
            override_skill_keys=defender_guest_skills,
        )
        defender_loadout = normalize_troop_loadout(
            _normalize_troop_loadout_input(normalized_setup.get("troop_loadout")),
            default_if_empty=fill_default_troops,
        )
        return defender_guests_comb, defender_loadout

    defender_loadout = generate_ai_loadout(rng)
    ai_guest_pool = build_ai_guests(rng)
    defender_guests_comb = build_guest_combatants(ai_guest_pool, side="defender", limit=defender_limit)
    return defender_guests_comb, defender_loadout


@contextmanager
def lock_guests_for_battle(guests: List[Guest], manor=None) -> Generator[List[Guest], None, None]:
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
    if not guests:
        yield []
        return

    guest_ids = _collect_guest_ids(guests)
    if not guest_ids:
        yield guests
        return

    with transaction.atomic():
        # 统一锁顺序为 Manor -> Guest，降低跨服务死锁风险
        if manor is not None and getattr(manor, "pk", None):
            from gameplay.models import Manor

            Manor.objects.select_for_update().get(pk=manor.pk)

        locked_guests = _lock_guest_rows(guest_ids)
        _validate_locked_guest_statuses(locked_guests)
        _mark_locked_guests_deployed(locked_guests)

        try:
            _refresh_guest_instances(guests)
            yield guests
        finally:
            _release_deployed_guests(guest_ids)


def validate_troop_capacity(guests: List[Guest], troop_loadout: Dict[str, int]) -> None:
    """
    验证总兵力是否超过门客带兵上限。

    规则：
    - 每名门客基础带兵数量：200
    - 满70级门客额外增加：50（总计250）

    Args:
        guests: 出征门客列表
        troop_loadout: 兵种配置 {troop_key: count}

    Raises:
        ValueError: 当总兵力超过带兵上限时
    """
    if not guests:
        return

    # 计算所有门客的总带兵上限
    total_capacity = sum(guest.troop_capacity for guest in guests)

    # 计算实际兵力总数
    total_troops = sum(troop_loadout.values())

    # 验证兵力是否超限
    if total_troops > total_capacity:
        guest_count = len(guests)
        raise ValueError(
            f"兵力超过带兵上限！当前出征{guest_count}名门客，"
            f"总带兵上限为{total_capacity}，实际兵力为{total_troops}。"
            f"请减少兵力或增派更多门客。"
        )


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
        with lock_guests_for_battle(active_guests, manor=manor):
            return _execute_battle(manor, guests, active_guests, options)
    else:
        # 不使用锁（用于测试或特殊场景）
        return _execute_battle(manor, guests, active_guests, options)


def _prepare_battle_environment(
    active_guests: List[Guest],
    options: BattleOptions,
) -> Dict[str, int]:
    """战前准备：HP恢复和兵力配置"""
    now = timezone.now()
    _recover_guest_hp_batch(active_guests, now)

    normalized_loadout = normalize_troop_loadout(options.troop_loadout, default_if_empty=options.fill_default_troops)
    if options.validate_attacker_troop_capacity:
        validate_troop_capacity(active_guests, normalized_loadout)
    return normalized_loadout


def _build_attacker_units(
    guests: List[Guest],
    normalized_loadout: Dict[str, int],
    options: BattleOptions,
    manor,
) -> tuple[List[Combatant], List[Combatant]]:
    """构建攻击方战斗单位（门客+小兵）"""
    attacker_guests_comb = build_guest_combatants(
        guests,
        side="attacker",
        limit=options.limit,
        stat_bonuses=options.attacker_guest_bonuses,
        override_skill_keys=options.attacker_guest_skills,
    )

    attacker_manor = manor if options.attacker_manor is None else options.attacker_manor
    attacker_troops = build_troop_combatants(
        normalized_loadout,
        side="attacker",
        manor=attacker_manor,
        tech_levels=options.attacker_tech_levels,
    )

    return attacker_guests_comb, attacker_troops


def _build_defender_units(
    options: BattleOptions,
    rng: random.Random,
    now,
) -> tuple[List[Combatant], List[Combatant], Dict[str, int]]:
    """构建防守方战斗单位（门客+小兵）"""
    defender_tech_levels, defender_guest_level, defender_guest_bonuses, defender_guest_skills = (
        _extract_defender_tech_profile(options.defender_setup)
    )

    defender_guests_comb, defender_loadout = _build_defender_guest_and_loadout(
        options.defender_guests,
        options.defender_setup,
        options.defender_limit,
        options.fill_default_troops,
        rng,
        now,
        defender_guest_level,
        defender_guest_bonuses,
        defender_guest_skills,
    )

    defender_troops = build_troop_combatants(
        defender_loadout, side="defender", tech_levels=defender_tech_levels or None
    )

    return defender_guests_comb, defender_troops, defender_loadout


def _execute_simulation(
    attacker_units: List[Combatant],
    defender_units: List[Combatant],
    options: BattleOptions,
    config: Dict,
    rng: random.Random,
    final_seed: int,
) -> tuple[Any, str]:
    """执行战斗模拟"""
    assign_agility_based_priorities(attacker_units, defender_units)

    opponent_label = options.opponent_name or config.get("name", "乱军试炼")
    simulation = simulate_battle(
        attacker_units=attacker_units,
        defender_units=defender_units,
        rng=rng,
        seed=final_seed,
        travel_seconds=options.travel_seconds,
        config=config,
        drop_table=options.drop_table,
    )
    return simulation, opponent_label


def _finalize_battle_results(
    manor,
    simulation: Any,
    guests: List[Guest],
    attacker_guests_comb: List[Combatant],
    defender_guests_comb: List[Combatant],
    normalized_loadout: Dict[str, int],
    defender_loadout: Dict[str, int],
    options: BattleOptions,
    opponent_label: str,
) -> BattleReport:
    """处理战斗结果：奖励、HP更新、战报创建、消息发送"""
    grant_battle_rewards(
        manor,
        simulation.drops,
        opponent_label,
        auto_reward=options.auto_reward,
        drop_handler=options.drop_handler,
    )

    hp_updates = apply_guest_hp_updates(guests, attacker_guests_comb, apply_damage=options.apply_damage)
    simulation.losses["attacker"]["hp_updates"] = hp_updates

    if options.defender_guests is not None:
        defender_hp_updates = apply_guest_hp_updates(
            options.defender_guests, defender_guests_comb, apply_damage=options.apply_damage
        )
        simulation.losses["defender"]["hp_updates"] = defender_hp_updates

    report = BattleReport.objects.create(
        manor=manor,
        opponent_name=opponent_label,
        battle_type=options.battle_type,
        attacker_team=[serialize_guest_for_report(c) for c in attacker_guests_comb],
        attacker_troops=normalized_loadout,
        defender_team=[serialize_guest_for_report(c) for c in defender_guests_comb],
        defender_troops=defender_loadout,
        rounds=simulation.rounds,
        losses=simulation.losses,
        drops=simulation.drops,
        winner=simulation.winner,
        starts_at=simulation.starts_at,
        completed_at=simulation.completed_at,
        seed=simulation.seed,
    )

    if options.send_message:
        dispatch_battle_message(manor, opponent_label, report)

    return report


def _execute_battle(
    manor,
    guests: List[Guest],
    active_guests: List[Guest],
    options: BattleOptions,
) -> BattleReport:
    """
    执行战斗的内部实现函数。

    此函数包含实际的战斗模拟逻辑，由 simulate_report 在获取锁后调用。
    """
    config = get_battle_config(options.battle_type)

    # 1. 战前准备
    normalized_loadout = _prepare_battle_environment(active_guests, options)

    # 2. 初始化随机数
    final_seed, rng = _resolve_battle_rng(options.seed, options.rng_source)

    # 3. 构建攻击方单位
    attacker_guests_comb, attacker_troops = _build_attacker_units(guests, normalized_loadout, options, manor)

    # 4. 构建防守方单位
    now = timezone.now()
    defender_guests_comb, defender_troops, defender_loadout = _build_defender_units(options, rng, now)

    # 5. 执行战斗模拟
    attacker_units = attacker_guests_comb + attacker_troops
    defender_units = defender_guests_comb + defender_troops
    simulation, opponent_label = _execute_simulation(attacker_units, defender_units, options, config, rng, final_seed)

    # 6. 处理战斗结果
    report = _finalize_battle_results(
        manor,
        simulation,
        guests,
        attacker_guests_comb,
        defender_guests_comb,
        normalized_loadout,
        defender_loadout,
        options,
        opponent_label,
    )

    return report


def apply_guest_hp_updates(
    guests: List[Guest],
    combatants: List[Combatant],
    apply_damage: bool,
) -> Dict[int, int]:
    """
    Compute and optionally persist HP updates for the guests based on simulated combatants.

    阵亡处理：
    - HP归零的门客设为重伤状态（INJURED）
    - 重伤门客HP设为1，无法自动恢复，但可出征
    - 需要使用药品治疗才能解除重伤状态
    """
    now = timezone.now()
    guest_map = {c.guest_id: c for c in combatants if c.guest_id}
    hp_updates: Dict[int, int] = {}
    dirty_guests: List[Guest] = []
    # 修复：遍历所有门客，使用guest.pk正确匹配combatant
    for guest in guests:
        comb = guest_map.get(guest.pk)
        if not comb:
            continue
        defeated = comb.hp <= 0
        remaining_hp = 1 if defeated else max(1, min(guest.max_hp, comb.hp))
        hp_updates[guest.pk] = remaining_hp
        if apply_damage and guest.pk:
            guest.current_hp = remaining_hp
            guest.last_hp_recovery_at = now
            if defeated:
                guest.status = GuestStatus.INJURED
            dirty_guests.append(guest)
    if apply_damage and dirty_guests:
        Guest.objects.bulk_update(dirty_guests, ["current_hp", "last_hp_recovery_at", "status"])
    return hp_updates
