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
ARENA_COMPLETED_RETENTION_SECONDS = 600
ARENA_REGISTRATION_SILVER_COST = 5000
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


def _today_bounds(*, now=None):
    current_time = timezone.localtime(now or timezone.now())
    start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def _today_local_date(*, now=None):
    return timezone.localdate(now or timezone.now())


def _sync_daily_participation_counter_locked(locked_manor: Manor, *, now=None) -> int:
    """
    同步庄园侧的竞技场日计数。

    说明：
    - 计数以 Manor 字段为准，避免赛事记录被清理后次数“回收”。
    - 当天首次访问且字段未初始化时，回填为当日现存 ArenaEntry 数量，兼容历史数据。
    """
    today = _today_local_date(now=now)
    if locked_manor.arena_participation_date == today:
        return max(0, int(locked_manor.arena_participations_today or 0))

    day_start, day_end = _today_bounds(now=now)
    today_count = ArenaEntry.objects.filter(manor=locked_manor, joined_at__gte=day_start, joined_at__lt=day_end).count()
    locked_manor.arena_participation_date = today
    locked_manor.arena_participations_today = max(0, int(today_count))
    locked_manor.save(update_fields=["arena_participation_date", "arena_participations_today"])
    return locked_manor.arena_participations_today


def _update_daily_participation_counter_locked(locked_manor: Manor, *, delta: int, now=None) -> int:
    current = _sync_daily_participation_counter_locked(locked_manor, now=now)
    updated = max(0, int(current) + int(delta))
    locked_manor.arena_participation_date = _today_local_date(now=now)
    locked_manor.arena_participations_today = updated
    locked_manor.save(update_fields=["arena_participation_date", "arena_participations_today"])
    return updated


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
    tournament.current_round = 0
    tournament.save(update_fields=["status", "started_at", "current_round", "updated_at"])
    _schedule_round_locked(tournament, round_number=1, now=current_time)
    return True


def _round_interval_delta(tournament: ArenaTournament) -> timedelta:
    return timedelta(seconds=max(1, int(tournament.round_interval_seconds)))


def _build_round_pairings(entry_ids: list[int]) -> list[tuple[int, int | None]]:
    shuffled_ids = entry_ids[:]
    random.SystemRandom().shuffle(shuffled_ids)
    pairings: list[tuple[int, int | None]] = []
    iterator = iter(shuffled_ids)
    for attacker_id in iterator:
        defender_id = next(iterator, None)
        pairings.append((attacker_id, defender_id))
    return pairings


def _schedule_round_locked(tournament: ArenaTournament, *, round_number: int, now) -> bool:
    if tournament.status != ArenaTournament.Status.RUNNING:
        return False
    if round_number <= 0:
        return False
    if ArenaMatch.objects.filter(tournament=tournament, round_number=round_number).exists():
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
        return False

    pairings = _build_round_pairings(active_entry_ids)
    ArenaMatch.objects.bulk_create(
        [
            ArenaMatch(
                tournament=tournament,
                round_number=round_number,
                match_index=match_index,
                attacker_entry_id=attacker_id,
                defender_entry_id=defender_id,
                status=ArenaMatch.Status.SCHEDULED,
            )
            for match_index, (attacker_id, defender_id) in enumerate(pairings)
        ]
    )

    tournament.current_round = round_number
    tournament.next_round_at = now + _round_interval_delta(tournament)
    tournament.save(update_fields=["current_round", "next_round_at", "updated_at"])
    return True


@transaction.atomic
def register_arena_entry(manor: Manor, guest_ids: Iterable[int]) -> ArenaRegistrationResult:
    selected_guest_ids = _normalize_guest_ids(guest_ids)
    locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)

    if _sync_daily_participation_counter_locked(locked_manor) >= ARENA_DAILY_PARTICIPATION_LIMIT:
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

    if locked_manor.silver < ARENA_REGISTRATION_SILVER_COST:
        raise ValueError(f"银两不足，报名需要 {ARENA_REGISTRATION_SILVER_COST} 银两")

    Manor.objects.filter(pk=locked_manor.pk).update(silver=F("silver") - ARENA_REGISTRATION_SILVER_COST)
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
    _update_daily_participation_counter_locked(locked_manor, delta=1)

    return ArenaRegistrationResult(
        entry=entry,
        tournament=tournament,
        auto_started=auto_started,
        entry_count=entry_count,
    )


@transaction.atomic
def cancel_arena_entry(manor: Manor) -> int:
    locked_manor = Manor.objects.select_for_update().get(pk=manor.pk)
    recruiting_entries = list(
        ArenaEntry.objects.select_for_update()
        .select_related("tournament")
        .filter(
            manor=locked_manor,
            status=ArenaEntry.Status.REGISTERED,
            tournament__status=ArenaTournament.Status.RECRUITING,
        )
        .order_by("-joined_at", "-id")
    )
    if not recruiting_entries:
        raise ValueError("当前没有可撤销的报名")

    entry_ids = [entry.id for entry in recruiting_entries]
    tournament_ids = {entry.tournament_id for entry in recruiting_entries}
    locked_tournaments = list(ArenaTournament.objects.select_for_update().filter(id__in=tournament_ids))
    if any(tournament.status != ArenaTournament.Status.RECRUITING for tournament in locked_tournaments):
        raise ValueError("赛事已开赛，当前不可撤销报名")

    participant_guest_ids = list(
        ArenaEntryGuest.objects.filter(entry_id__in=entry_ids).values_list("guest_id", flat=True).distinct()
    )

    ArenaEntry.objects.filter(id__in=entry_ids).delete()
    if participant_guest_ids:
        Guest.objects.filter(id__in=participant_guest_ids, status=GuestStatus.DEPLOYED).update(status=GuestStatus.IDLE)

    _update_daily_participation_counter_locked(locked_manor, delta=-len(entry_ids))
    return len(entry_ids)


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
    links = list(entry.entry_guests.order_by("created_at", "id")[:ARENA_MAX_GUESTS_PER_ENTRY])
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


def _save_resolved_match(
    *,
    match: ArenaMatch,
    winner_entry: ArenaEntry,
    status: str,
    now,
    note: str = "",
    report=None,
) -> None:
    match.winner_entry = winner_entry
    match.status = status
    match.notes = note[:255]
    match.resolved_at = now
    if report is not None:
        match.battle_report = report
        match.save(update_fields=["winner_entry", "status", "notes", "battle_report", "resolved_at"])
        return
    match.save(update_fields=["winner_entry", "status", "notes", "resolved_at"])


def _resolve_match_locked(
    *,
    tournament: ArenaTournament,
    round_number: int,
    match_index: int,
    attacker_entry: ArenaEntry,
    defender_entry: ArenaEntry,
    now,
    match: ArenaMatch | None = None,
) -> ArenaEntry:
    attacker_guests = _load_entry_guests(attacker_entry)
    defender_guests = _load_entry_guests(defender_entry)

    if not attacker_guests and not defender_guests:
        winner_entry = random.choice([attacker_entry, defender_entry])
        if match:
            _save_resolved_match(
                match=match,
                winner_entry=winner_entry,
                status=ArenaMatch.Status.FORFEIT,
                note="双方均无可用门客，随机判定胜者",
                now=now,
            )
        else:
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
        if match:
            _save_resolved_match(
                match=match,
                winner_entry=defender_entry,
                status=ArenaMatch.Status.FORFEIT,
                note="攻击方无可用门客，判负",
                now=now,
            )
        else:
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
        if match:
            _save_resolved_match(
                match=match,
                winner_entry=attacker_entry,
                status=ArenaMatch.Status.FORFEIT,
                note="防守方无可用门客，判负",
                now=now,
            )
        else:
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
        if match:
            _save_resolved_match(
                match=match,
                winner_entry=winner_entry,
                status=ArenaMatch.Status.FORFEIT,
                note="战斗模拟异常，已随机判定胜者",
                now=now,
            )
        else:
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

    if match:
        _save_resolved_match(
            match=match,
            winner_entry=winner_entry,
            status=ArenaMatch.Status.COMPLETED,
            report=report,
            now=now,
        )
    else:
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
        pending_matches = list(
            ArenaMatch.objects.select_for_update()
            .filter(
                tournament=tournament,
                round_number=tournament.current_round,
                status=ArenaMatch.Status.SCHEDULED,
            )
            .order_by("match_index", "id")
        )

        if not pending_matches:
            next_round_number = max(1, tournament.current_round + 1)
            return _schedule_round_locked(tournament, round_number=next_round_number, now=now)

        round_number = tournament.current_round
        pending_match_ids = [match.id for match in pending_matches]
        # 避免并发 worker 重复处理本轮，先把下次扫描时间推后。
        tournament.next_round_at = now + _round_interval_delta(tournament)
        tournament.save(update_fields=["next_round_at", "updated_at"])

    pending_matches = list(
        ArenaMatch.objects.select_related(
            "attacker_entry__manor",
            "attacker_entry__manor__user",
            "defender_entry__manor",
            "defender_entry__manor__user",
        )
        .filter(id__in=pending_match_ids)
        .order_by("match_index", "id")
    )
    entry_ids = {
        entry_id
        for match in pending_matches
        for entry_id in [match.attacker_entry_id, match.defender_entry_id]
        if entry_id is not None
    }
    entries = (
        ArenaEntry.objects.select_related("manor", "manor__user")
        .prefetch_related("entry_guests__guest__template", "entry_guests__guest__skills")
        .filter(pk__in=entry_ids)
    )
    entry_map = {entry.id: entry for entry in entries}

    winner_ids: list[int] = []
    loser_ids: list[int] = []
    for pending in pending_matches:
        attacker_entry = entry_map.get(pending.attacker_entry_id)
        if not attacker_entry:
            continue

        if pending.defender_entry_id is None:
            winner_ids.append(attacker_entry.id)
            _save_resolved_match(
                match=pending,
                winner_entry=attacker_entry,
                status=ArenaMatch.Status.BYE,
                note="本轮轮空直接晋级",
                now=now,
            )
            continue

        defender_entry = entry_map.get(pending.defender_entry_id)
        if not defender_entry:
            winner_ids.append(attacker_entry.id)
            _save_resolved_match(
                match=pending,
                winner_entry=attacker_entry,
                status=ArenaMatch.Status.FORFEIT,
                note="对手报名数据缺失，自动晋级",
                now=now,
            )
            continue

        winner_entry = _resolve_match_locked(
            tournament=pending.tournament,
            round_number=round_number,
            match_index=pending.match_index,
            attacker_entry=attacker_entry,
            defender_entry=defender_entry,
            now=now,
            match=pending,
        )
        winner_ids.append(winner_entry.id)
        loser_id = defender_entry.id if winner_entry.id == attacker_entry.id else attacker_entry.id
        loser_ids.append(loser_id)

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

        _schedule_round_locked(tournament, round_number=round_number + 1, now=now)
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


def cleanup_expired_tournaments(
    *, now=None, grace_seconds: int = ARENA_COMPLETED_RETENTION_SECONDS, limit: int = 50
) -> int:
    current_time = now or timezone.now()
    retention_seconds = max(0, int(grace_seconds))
    cutoff_time = current_time - timedelta(seconds=retention_seconds)
    stale_ids = list(
        ArenaTournament.objects.filter(
            status__in=[ArenaTournament.Status.COMPLETED, ArenaTournament.Status.CANCELLED],
            ended_at__isnull=False,
            ended_at__lte=cutoff_time,
        )
        .order_by("ended_at", "id")
        .values_list("id", flat=True)[: max(1, int(limit))]
    )
    if not stale_ids:
        return 0

    ArenaTournament.objects.filter(id__in=stale_ids).delete()
    return len(stale_ids)


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

    day_start, day_end = _today_bounds()
    if reward.daily_limit is not None:
        today_exchanged = (
            ArenaExchangeRecord.objects.filter(
                manor=locked_manor,
                reward_key=reward.key,
                created_at__gte=day_start,
                created_at__lt=day_end,
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
