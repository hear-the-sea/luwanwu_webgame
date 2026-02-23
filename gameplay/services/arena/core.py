from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, Iterable, cast

from django.db import transaction
from django.db.models import Count, F, Sum
from django.utils import timezone

from battle.services import simulate_report
from core.utils.cache_lock import acquire_best_effort_lock, release_best_effort_lock
from core.utils.time_scale import scale_duration
from gameplay.models import (
    ArenaEntry,
    ArenaEntryGuest,
    ArenaExchangeRecord,
    ArenaMatch,
    ArenaTournament,
    Manor,
    Message,
)
from gameplay.services.inventory import add_item_to_inventory_locked
from gameplay.services.resources import grant_resources_locked
from gameplay.services.utils.messages import create_message
from guests.models import Guest, GuestStatus

from .rewards import ArenaRewardDefinition, get_arena_reward_definition

logger = logging.getLogger(__name__)

ARENA_DAILY_PARTICIPATION_LIMIT = 3
ARENA_MAX_GUESTS_PER_ENTRY = 10
ARENA_TOURNAMENT_PLAYER_LIMIT = 10
ARENA_ROUND_INTERVAL_SECONDS = 600
ARENA_BASE_PARTICIPATION_COINS = 30
ARENA_RANK_BONUS_COINS = {
    1: 280,
    2: 170,
    3: 120,
    4: 90,
    5: 70,
    6: 60,
    7: 50,
    8: 40,
    9: 30,
    10: 20,
}
ARENA_RECRUITING_LOCK_KEY = "arena:recruiting_tournament:create"
ARENA_RECRUITING_LOCK_TIMEOUT = 5


class _EmptySkillSet:
    @staticmethod
    def all() -> list:
        return []


class ArenaGuestSnapshotProxy:
    """将报名快照转换为 battle.build_guest_combatants 可消费对象。"""

    def __init__(self, snapshot: dict[str, Any]):
        self.pk = None
        self.id = None
        self.template = SimpleNamespace(
            key=str(snapshot.get("template_key") or "arena_unknown"),
            initial_skills=_EmptySkillSet(),
        )
        self._display_name = str(snapshot.get("display_name") or "无名门客")
        self._rarity = str(snapshot.get("rarity") or "gray")
        self.level = max(1, int(snapshot.get("level") or 1))
        self.force = int(snapshot.get("force") or 0)
        self.intellect = int(snapshot.get("intellect") or 0)
        self.defense_stat = int(snapshot.get("defense_stat") or 0)
        self.agility = int(snapshot.get("agility") or 0)
        self.luck = int(snapshot.get("luck") or 0)
        self.current_hp = max(1, int(snapshot.get("current_hp") or 1))
        self._attack = max(1, int(snapshot.get("attack") or 1))
        self._defense = max(1, int(snapshot.get("defense") or 1))
        self._max_hp = max(1, int(snapshot.get("max_hp") or 1))
        skill_keys = [str(key).strip() for key in (snapshot.get("skill_keys") or []) if str(key).strip()]
        self._override_skills = skill_keys

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def rarity(self) -> str:
        return self._rarity

    def stat_block(self) -> dict[str, int]:
        return {
            "attack": self._attack,
            "defense": self._defense,
            "intellect": self.intellect,
            "hp": self._max_hp,
        }

    @property
    def troop_capacity(self) -> int:
        # 竞技场当前不带兵，容量仅用于通过 battle 服务的通用校验。
        return 0


@dataclass(frozen=True)
class ArenaRegistrationResult:
    entry: ArenaEntry
    tournament: ArenaTournament
    auto_started: bool
    entry_count: int


@dataclass(frozen=True)
class ArenaExchangeResult:
    reward: ArenaRewardDefinition
    quantity: int
    total_cost: int
    credited_resources: dict[str, int]
    overflow_resources: dict[str, int]
    granted_items: dict[str, int]


def _normalize_guest_ids(guest_ids: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    normalized: list[int] = []
    for raw in guest_ids:
        try:
            guest_id = int(raw)
        except (TypeError, ValueError):
            raise ValueError("门客选择有误")
        if guest_id <= 0:
            raise ValueError("门客选择有误")
        if guest_id in seen:
            continue
        seen.add(guest_id)
        normalized.append(guest_id)

    if not normalized:
        raise ValueError("请至少选择 1 名门客")
    if len(normalized) > ARENA_MAX_GUESTS_PER_ENTRY:
        raise ValueError(f"每次最多选择 {ARENA_MAX_GUESTS_PER_ENTRY} 名门客")
    return normalized


def _serialize_guest_skill_keys(guest: Guest) -> list[str]:
    return [str(key).strip() for key in guest.skills.values_list("key", flat=True) if str(key).strip()]


def _build_entry_guest_snapshot(guest: Guest) -> dict[str, Any]:
    stats = guest.stat_block()
    max_hp = max(1, int(stats.get("hp") or guest.max_hp or 1))
    current_hp = int(getattr(guest, "current_hp", 0) or 0)
    current_hp = min(max_hp, max(1, current_hp if current_hp > 0 else max_hp))
    return {
        "snapshot_version": 1,
        "display_name": guest.display_name,
        "rarity": guest.rarity,
        "template_key": guest.template.key,
        "level": int(guest.level),
        "force": int(guest.force),
        "intellect": int(guest.intellect),
        "defense_stat": int(guest.defense_stat),
        "agility": int(guest.agility),
        "luck": int(guest.luck),
        "attack": max(1, int(stats.get("attack") or 1)),
        "defense": max(1, int(stats.get("defense") or 1)),
        "max_hp": max_hp,
        "current_hp": current_hp,
        "skill_keys": _serialize_guest_skill_keys(guest),
    }


def _round_interval_seconds() -> int:
    return max(1, scale_duration(ARENA_ROUND_INTERVAL_SECONDS, minimum=1))


def _today_participation_count(manor: Manor) -> int:
    today = timezone.localdate()
    return ArenaEntry.objects.filter(manor=manor, joined_at__date=today).count()


def _get_or_create_recruiting_tournament_locked() -> ArenaTournament:
    tournament = (
        ArenaTournament.objects.select_for_update()
        .filter(status=ArenaTournament.Status.RECRUITING)
        .annotate(entry_count=Count("entries"))
        .filter(entry_count__lt=F("player_limit"))
        .order_by("created_at")
        .first()
    )
    if tournament:
        return tournament

    acquired, from_cache = acquire_best_effort_lock(
        ARENA_RECRUITING_LOCK_KEY,
        timeout_seconds=ARENA_RECRUITING_LOCK_TIMEOUT,
        logger=logger,
        log_context="arena recruiting tournament lock",
    )
    if not acquired:
        existing = (
            ArenaTournament.objects.filter(status=ArenaTournament.Status.RECRUITING)
            .annotate(entry_count=Count("entries"))
            .filter(entry_count__lt=F("player_limit"))
            .order_by("created_at")
            .first()
        )
        if existing:
            return existing
        raise ValueError("竞技场报名繁忙，请稍后重试")

    try:
        existing = (
            ArenaTournament.objects.select_for_update()
            .filter(status=ArenaTournament.Status.RECRUITING)
            .annotate(entry_count=Count("entries"))
            .filter(entry_count__lt=F("player_limit"))
            .order_by("created_at")
            .first()
        )
        if existing:
            return existing

        return ArenaTournament.objects.create(
            status=ArenaTournament.Status.RECRUITING,
            player_limit=ARENA_TOURNAMENT_PLAYER_LIMIT,
            round_interval_seconds=_round_interval_seconds(),
        )
    finally:
        release_best_effort_lock(
            ARENA_RECRUITING_LOCK_KEY,
            from_cache=from_cache,
            logger=logger,
            log_context="arena recruiting tournament lock",
        )


def _start_tournament_locked(tournament: ArenaTournament, *, now=None) -> bool:
    if tournament.status != ArenaTournament.Status.RECRUITING:
        return False
    entry_count = tournament.entries.count()
    if entry_count < tournament.player_limit:
        return False

    current_time = now or timezone.now()
    tournament.status = ArenaTournament.Status.RUNNING
    tournament.started_at = current_time
    tournament.next_round_at = current_time
    tournament.current_round = 0
    tournament.save(update_fields=["status", "started_at", "next_round_at", "current_round", "updated_at"])
    return True


@transaction.atomic
def register_arena_entry(manor: Manor, guest_ids: Iterable[int]) -> ArenaRegistrationResult:
    selected_guest_ids = _normalize_guest_ids(guest_ids)
    locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)

    if _today_participation_count(locked_manor) >= ARENA_DAILY_PARTICIPATION_LIMIT:
        raise ValueError(f"每日最多参加 {ARENA_DAILY_PARTICIPATION_LIMIT} 次竞技场")

    if ArenaEntry.objects.filter(
        manor=locked_manor,
        tournament__status__in=[ArenaTournament.Status.RECRUITING, ArenaTournament.Status.RUNNING],
    ).exists():
        raise ValueError("您已有进行中的竞技场报名，请等待本场结束")

    all_selected_guests = list(
        Guest.objects.select_for_update()
        .filter(manor=locked_manor, id__in=selected_guest_ids)
        .select_related("template")
        .prefetch_related("skills")
        .order_by("id")
    )
    if len(all_selected_guests) != len(selected_guest_ids):
        raise ValueError("所选门客不存在或不属于当前庄园")

    non_idle_guests = [guest for guest in all_selected_guests if guest.status != GuestStatus.IDLE]
    if non_idle_guests:
        raise ValueError("仅空闲门客可报名竞技场")

    selected_guest_order = {guest_id: index for index, guest_id in enumerate(selected_guest_ids)}
    selected_guests = sorted(all_selected_guests, key=lambda guest: selected_guest_order[guest.id])
    tournament = _get_or_create_recruiting_tournament_locked()
    entry = ArenaEntry.objects.create(tournament=tournament, manor=locked_manor)
    ArenaEntryGuest.objects.bulk_create(
        [
            ArenaEntryGuest(entry=entry, guest=guest, snapshot=_build_entry_guest_snapshot(guest))
            for guest in selected_guests
        ]
    )
    for guest in selected_guests:
        guest.status = GuestStatus.DEPLOYED
    Guest.objects.bulk_update(selected_guests, ["status"])

    entry_count = tournament.entries.count()
    auto_started = False
    if entry_count >= tournament.player_limit:
        auto_started = _start_tournament_locked(tournament)

    return ArenaRegistrationResult(
        entry=entry,
        tournament=tournament,
        auto_started=auto_started,
        entry_count=entry_count,
    )


@transaction.atomic
def start_tournament_if_ready(tournament: ArenaTournament, *, now=None) -> bool:
    locked = ArenaTournament.objects.select_for_update().filter(pk=tournament.pk).first()
    if not locked:
        return False
    return _start_tournament_locked(locked, now=now)


def start_ready_tournaments(limit: int = 20) -> int:
    candidate_ids = list(
        ArenaTournament.objects.filter(status=ArenaTournament.Status.RECRUITING)
        .annotate(entry_count=Count("entries"))
        .filter(entry_count__gte=F("player_limit"))
        .order_by("created_at")
        .values_list("id", flat=True)[: max(1, int(limit))]
    )
    started_count = 0
    for tournament_id in candidate_ids:
        try:
            if start_tournament_if_ready(ArenaTournament(id=tournament_id)):
                started_count += 1
        except Exception:
            logger.exception("failed to start ready tournament: tournament_id=%s", tournament_id)
    return started_count


def _load_entry_guests(entry: ArenaEntry) -> list[ArenaGuestSnapshotProxy]:
    proxies: list[ArenaGuestSnapshotProxy] = []
    links = list(entry.entry_guests.all()[:ARENA_MAX_GUESTS_PER_ENTRY])
    for link in links:
        snapshot = dict(link.snapshot or {})
        if not snapshot and getattr(link, "guest", None):
            # 兼容历史报名数据（未写入 snapshot 的旧记录）
            snapshot = _build_entry_guest_snapshot(link.guest)
        if not snapshot:
            continue
        proxies.append(ArenaGuestSnapshotProxy(snapshot))
    return proxies


def _send_arena_battle_messages(
    *,
    report,
    round_number: int,
    attacker_entry: ArenaEntry,
    defender_entry: ArenaEntry,
    winner_entry: ArenaEntry,
) -> None:
    title = f"竞技场第 {round_number} 轮战报"
    winner_name = winner_entry.manor.display_name
    body = (
        f"{attacker_entry.manor.display_name} 对阵 {defender_entry.manor.display_name}，" f"本场胜者：{winner_name}。"
    )

    try:
        create_message(
            manor=attacker_entry.manor,
            kind=Message.Kind.BATTLE,
            title=title,
            body=body,
            battle_report=report,
        )
        create_message(
            manor=defender_entry.manor,
            kind=Message.Kind.BATTLE,
            title=title,
            body=body,
            battle_report=report,
        )
    except Exception:
        logger.exception(
            "failed to send arena battle messages: report_id=%s attacker_entry=%s defender_entry=%s",
            getattr(report, "id", None),
            attacker_entry.id,
            defender_entry.id,
        )


def _create_forfeit_match(
    *,
    tournament: ArenaTournament,
    round_number: int,
    match_index: int,
    attacker_entry: ArenaEntry,
    defender_entry: ArenaEntry | None,
    winner_entry: ArenaEntry,
    status: str,
    note: str,
    now,
) -> ArenaMatch:
    return ArenaMatch.objects.create(
        tournament=tournament,
        round_number=round_number,
        match_index=match_index,
        attacker_entry=attacker_entry,
        defender_entry=defender_entry,
        winner_entry=winner_entry,
        status=status,
        notes=note[:255],
        resolved_at=now,
    )


def _resolve_match_locked(
    *,
    tournament: ArenaTournament,
    round_number: int,
    match_index: int,
    attacker_entry: ArenaEntry,
    defender_entry: ArenaEntry,
    now,
) -> ArenaEntry:
    attacker_guests = _load_entry_guests(attacker_entry)
    defender_guests = _load_entry_guests(defender_entry)

    if not attacker_guests and not defender_guests:
        winner_entry = random.choice([attacker_entry, defender_entry])
        _create_forfeit_match(
            tournament=tournament,
            round_number=round_number,
            match_index=match_index,
            attacker_entry=attacker_entry,
            defender_entry=defender_entry,
            winner_entry=winner_entry,
            status=ArenaMatch.Status.FORFEIT,
            note="双方均无可用门客，随机判定胜者",
            now=now,
        )
        return winner_entry

    if not attacker_guests:
        _create_forfeit_match(
            tournament=tournament,
            round_number=round_number,
            match_index=match_index,
            attacker_entry=attacker_entry,
            defender_entry=defender_entry,
            winner_entry=defender_entry,
            status=ArenaMatch.Status.FORFEIT,
            note="攻击方无可用门客，判负",
            now=now,
        )
        return defender_entry

    if not defender_guests:
        _create_forfeit_match(
            tournament=tournament,
            round_number=round_number,
            match_index=match_index,
            attacker_entry=attacker_entry,
            defender_entry=defender_entry,
            winner_entry=attacker_entry,
            status=ArenaMatch.Status.FORFEIT,
            note="防守方无可用门客，判负",
            now=now,
        )
        return attacker_entry

    attacker_battle_guests = cast(list[Guest], attacker_guests)
    defender_battle_guests = cast(list[Guest], defender_guests)
    try:
        report = simulate_report(
            manor=attacker_entry.manor,
            battle_type="arena",
            troop_loadout={},
            fill_default_troops=False,
            attacker_guests=attacker_battle_guests,
            defender_guests=defender_battle_guests,
            max_squad=ARENA_MAX_GUESTS_PER_ENTRY,
            auto_reward=False,
            send_message=False,
            apply_damage=False,
            use_lock=False,
            opponent_name=defender_entry.manor.display_name,
        )
    except Exception:
        logger.exception(
            "arena simulate_report failed; fallback to forfeit: tournament_id=%s round=%s attacker=%s defender=%s",
            tournament.id,
            round_number,
            attacker_entry.id,
            defender_entry.id,
        )
        winner_entry = random.choice([attacker_entry, defender_entry])
        _create_forfeit_match(
            tournament=tournament,
            round_number=round_number,
            match_index=match_index,
            attacker_entry=attacker_entry,
            defender_entry=defender_entry,
            winner_entry=winner_entry,
            status=ArenaMatch.Status.FORFEIT,
            note="战斗模拟异常，已随机判定胜者",
            now=now,
        )
        return winner_entry

    if report.winner == "attacker":
        winner_entry = attacker_entry
    elif report.winner == "defender":
        winner_entry = defender_entry
    else:
        winner_entry = random.choice([attacker_entry, defender_entry])

    ArenaMatch.objects.create(
        tournament=tournament,
        round_number=round_number,
        match_index=match_index,
        attacker_entry=attacker_entry,
        defender_entry=defender_entry,
        winner_entry=winner_entry,
        battle_report=report,
        status=ArenaMatch.Status.COMPLETED,
        resolved_at=now,
    )

    _send_arena_battle_messages(
        report=report,
        round_number=round_number,
        attacker_entry=attacker_entry,
        defender_entry=defender_entry,
        winner_entry=winner_entry,
    )
    return winner_entry


def _calculate_ranked_entries(entries: list[ArenaEntry], winner_entry: ArenaEntry | None) -> list[ArenaEntry]:
    winner = winner_entry
    if winner is None and entries:
        winner = sorted(entries, key=lambda item: (-item.matches_won, -(item.eliminated_round or 0), item.id))[0]

    ranked: list[ArenaEntry] = []
    if winner:
        ranked.append(winner)

    others = [entry for entry in entries if winner is None or entry.pk != winner.pk]
    others.sort(key=lambda item: (-(item.eliminated_round or 0), -item.matches_won, item.id))
    ranked.extend(others)
    return ranked


def _reward_for_rank(rank: int) -> int:
    return ARENA_BASE_PARTICIPATION_COINS + ARENA_RANK_BONUS_COINS.get(rank, 0)


def _finalize_tournament_locked(tournament: ArenaTournament, *, winner_entry: ArenaEntry | None, now) -> None:
    entries = list(tournament.entries.select_related("manor", "manor__user").select_for_update().order_by("id"))
    if not entries:
        tournament.status = ArenaTournament.Status.CANCELLED
        tournament.ended_at = now
        tournament.next_round_at = None
        tournament.save(update_fields=["status", "ended_at", "next_round_at", "updated_at"])
        return

    ranked_entries = _calculate_ranked_entries(entries, winner_entry)
    for idx, entry in enumerate(ranked_entries, start=1):
        entry.final_rank = idx
        entry.coin_reward = _reward_for_rank(idx)
        if idx == 1:
            entry.status = ArenaEntry.Status.WINNER
        elif entry.status != ArenaEntry.Status.ELIMINATED:
            entry.status = ArenaEntry.Status.ELIMINATED

    ArenaEntry.objects.bulk_update(ranked_entries, ["final_rank", "coin_reward", "status"])

    for entry in ranked_entries:
        Manor.objects.filter(pk=entry.manor_id).update(arena_coins=F("arena_coins") + entry.coin_reward)
        title = "竞技场结算奖励"
        body = f"本场排名第 {entry.final_rank}，获得角斗币 {entry.coin_reward}。"
        create_message(manor=entry.manor, kind=Message.Kind.REWARD, title=title, body=body)

    participating_guest_ids = list(
        ArenaEntryGuest.objects.filter(entry_id__in=[entry.id for entry in entries]).values_list("guest_id", flat=True)
    )
    if participating_guest_ids:
        Guest.objects.filter(id__in=participating_guest_ids, status=GuestStatus.DEPLOYED).update(
            status=GuestStatus.IDLE
        )

    winner = ranked_entries[0]
    tournament.status = ArenaTournament.Status.COMPLETED
    tournament.current_round = max(tournament.current_round, winner.eliminated_round or tournament.current_round)
    tournament.winner_entry = winner
    tournament.ended_at = now
    tournament.next_round_at = None
    tournament.save(
        update_fields=["status", "current_round", "winner_entry", "ended_at", "next_round_at", "updated_at"]
    )


def _run_tournament_round(tournament_id: int, *, now) -> bool:
    with transaction.atomic():
        tournament = ArenaTournament.objects.select_for_update().filter(pk=tournament_id).first()
        if not tournament:
            return False
        if tournament.status != ArenaTournament.Status.RUNNING:
            return False
        if not tournament.next_round_at or tournament.next_round_at > now:
            return False

        active_entry_ids = list(
            tournament.entries.filter(status=ArenaEntry.Status.REGISTERED).order_by("id").values_list("id", flat=True)
        )
        if len(active_entry_ids) <= 1:
            winner = None
            if active_entry_ids:
                winner = (
                    ArenaEntry.objects.select_related("manor", "manor__user")
                    .select_for_update()
                    .filter(pk=active_entry_ids[0])
                    .first()
                )
            _finalize_tournament_locked(tournament, winner_entry=winner, now=now)
            return True

        round_number = tournament.current_round + 1
        shuffled_ids = active_entry_ids[:]
        random.SystemRandom().shuffle(shuffled_ids)
        pairings: list[tuple[int, int | None]] = []
        iterator = iter(shuffled_ids)
        for attacker_id in iterator:
            defender_id = next(iterator, None)
            pairings.append((attacker_id, defender_id))

        # 先推进轮次时间戳，避免长耗时战斗期间重复被其他 worker 扫描。
        tournament.current_round = round_number
        tournament.next_round_at = now + timedelta(seconds=max(1, int(tournament.round_interval_seconds)))
        tournament.save(update_fields=["current_round", "next_round_at", "updated_at"])

    entry_ids = {entry_id for pairing in pairings for entry_id in pairing if entry_id is not None}
    round_tournament = ArenaTournament.objects.filter(pk=tournament_id).first()
    if not round_tournament:
        return False
    entries = (
        ArenaEntry.objects.select_related("manor", "manor__user")
        .prefetch_related("entry_guests__guest__template", "entry_guests__guest__skills")
        .filter(pk__in=entry_ids)
    )
    entry_map = {entry.id: entry for entry in entries}

    winner_ids: list[int] = []
    loser_ids: list[int] = []
    match_index = 0
    for attacker_id, defender_id in pairings:
        attacker_entry = entry_map.get(attacker_id)
        if not attacker_entry:
            match_index += 1
            continue

        if defender_id is None:
            winner_ids.append(attacker_entry.id)
            _create_forfeit_match(
                tournament=round_tournament,
                round_number=round_number,
                match_index=match_index,
                attacker_entry=attacker_entry,
                defender_entry=None,
                winner_entry=attacker_entry,
                status=ArenaMatch.Status.BYE,
                note="本轮轮空直接晋级",
                now=now,
            )
            match_index += 1
            continue

        defender_entry = entry_map.get(defender_id)
        if not defender_entry:
            winner_ids.append(attacker_entry.id)
            _create_forfeit_match(
                tournament=round_tournament,
                round_number=round_number,
                match_index=match_index,
                attacker_entry=attacker_entry,
                defender_entry=None,
                winner_entry=attacker_entry,
                status=ArenaMatch.Status.FORFEIT,
                note="对手报名数据缺失，自动晋级",
                now=now,
            )
            match_index += 1
            continue

        winner_entry = _resolve_match_locked(
            tournament=round_tournament,
            round_number=round_number,
            match_index=match_index,
            attacker_entry=attacker_entry,
            defender_entry=defender_entry,
            now=now,
        )
        winner_ids.append(winner_entry.id)
        loser_id = defender_entry.id if winner_entry.id == attacker_entry.id else attacker_entry.id
        loser_ids.append(loser_id)
        match_index += 1

    winner_ids = list(dict.fromkeys(winner_ids))
    loser_ids = list(dict.fromkeys(loser_ids))

    with transaction.atomic():
        tournament = ArenaTournament.objects.select_for_update().filter(pk=tournament_id).first()
        if not tournament or tournament.status != ArenaTournament.Status.RUNNING:
            return False

        if loser_ids:
            ArenaEntry.objects.filter(
                pk__in=loser_ids,
                status=ArenaEntry.Status.REGISTERED,
            ).update(
                status=ArenaEntry.Status.ELIMINATED,
                eliminated_round=round_number,
            )
        for winner_id in winner_ids:
            ArenaEntry.objects.filter(pk=winner_id).update(matches_won=F("matches_won") + 1)

        if len(winner_ids) <= 1:
            winner = None
            if winner_ids:
                winner = (
                    ArenaEntry.objects.select_related("manor", "manor__user")
                    .select_for_update()
                    .filter(pk=winner_ids[0])
                    .first()
                )
            _finalize_tournament_locked(tournament, winner_entry=winner, now=now)
    return True


def run_due_arena_rounds(*, now=None, limit: int = 20) -> int:
    current_time = now or timezone.now()
    due_ids = list(
        ArenaTournament.objects.filter(
            status=ArenaTournament.Status.RUNNING,
            next_round_at__isnull=False,
            next_round_at__lte=current_time,
        )
        .order_by("next_round_at")
        .values_list("id", flat=True)[: max(1, int(limit))]
    )

    processed = 0
    for tournament_id in due_ids:
        try:
            if _run_tournament_round(tournament_id, now=current_time):
                processed += 1
        except Exception:
            logger.exception("failed to process arena round: tournament_id=%s", tournament_id)
    return processed


@transaction.atomic
def exchange_arena_reward(manor: Manor, reward_key: str, quantity: int = 1) -> ArenaExchangeResult:
    reward = get_arena_reward_definition(reward_key)
    if not reward:
        raise ValueError("兑换项不存在")

    normalized_quantity = int(quantity or 0)
    if normalized_quantity <= 0:
        raise ValueError("兑换数量无效")

    locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
    total_cost = reward.cost_coins * normalized_quantity
    if locked_manor.arena_coins < total_cost:
        raise ValueError("角斗币不足")

    today = timezone.localdate()
    if reward.daily_limit is not None:
        today_exchanged = (
            ArenaExchangeRecord.objects.filter(
                manor=locked_manor,
                reward_key=reward.key,
                created_at__date=today,
            ).aggregate(total=Sum("quantity"))["total"]
            or 0
        )
        if today_exchanged + normalized_quantity > reward.daily_limit:
            raise ValueError(f"{reward.name} 今日最多可兑换 {reward.daily_limit} 次")

    locked_manor.arena_coins = F("arena_coins") - total_cost
    locked_manor.save(update_fields=["arena_coins"])

    reward_resources = {key: amount * normalized_quantity for key, amount in reward.resources.items()}
    credited_resources, overflow_resources = grant_resources_locked(
        locked_manor,
        reward_resources,
        note=f"竞技场兑换：{reward.name}",
    )

    granted_items: dict[str, int] = {}
    for item_key, amount in reward.items.items():
        total_amount = amount * normalized_quantity
        add_item_to_inventory_locked(locked_manor, item_key, total_amount)
        granted_items[item_key] = total_amount

    payload = {
        "resources": credited_resources,
        "resources_overflow": overflow_resources,
        "items": granted_items,
    }
    ArenaExchangeRecord.objects.create(
        manor=locked_manor,
        reward_key=reward.key,
        reward_name=reward.name,
        cost_coins=total_cost,
        quantity=normalized_quantity,
        payload=payload,
    )

    summary_parts: list[str] = []
    if credited_resources:
        summary_parts.append("资源已发放")
    if granted_items:
        summary_parts.append("道具已入库")
    if overflow_resources:
        summary_parts.append("部分资源因容量上限溢出")
    summary = "，".join(summary_parts) if summary_parts else "奖励已处理"

    create_message(
        manor=locked_manor,
        kind=Message.Kind.REWARD,
        title=f"竞技场兑换成功：{reward.name}",
        body=f"消耗角斗币 {total_cost}，兑换数量 {normalized_quantity}。{summary}。",
    )

    manor.refresh_from_db(fields=["arena_coins", "grain", "silver"])
    return ArenaExchangeResult(
        reward=reward,
        quantity=normalized_quantity,
        total_cost=total_cost,
        credited_resources=credited_resources,
        overflow_resources=overflow_resources,
        granted_items=granted_items,
    )
