from __future__ import annotations

import logging
from collections.abc import Callable

from gameplay.models import ArenaEntry, ArenaMatch, ArenaTournament, Message
from gameplay.services.utils.messages import create_message

from .snapshots import ArenaGuestSnapshotProxy


def send_arena_battle_messages(
    *,
    report,
    round_number: int,
    attacker_entry: ArenaEntry,
    defender_entry: ArenaEntry,
    winner_entry: ArenaEntry,
    logger: logging.Logger,
) -> None:
    title = f"竞技场第 {round_number} 轮战报"
    winner_name = winner_entry.manor.display_name
    body = f"{attacker_entry.manor.display_name} 对阵 {defender_entry.manor.display_name}，本场胜者：{winner_name}。"

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


def create_forfeit_match(
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


def save_resolved_match(
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


def persist_forfeit_match_resolution(
    *,
    tournament: ArenaTournament,
    round_number: int,
    match_index: int,
    attacker_entry: ArenaEntry,
    defender_entry: ArenaEntry,
    winner_entry: ArenaEntry,
    note: str,
    now,
    match: ArenaMatch | None,
) -> None:
    if match is not None:
        save_resolved_match(
            match=match,
            winner_entry=winner_entry,
            status=ArenaMatch.Status.FORFEIT,
            note=note,
            now=now,
        )
        return
    create_forfeit_match(
        tournament=tournament,
        round_number=round_number,
        match_index=match_index,
        attacker_entry=attacker_entry,
        defender_entry=defender_entry,
        winner_entry=winner_entry,
        status=ArenaMatch.Status.FORFEIT,
        note=note,
        now=now,
    )


def resolve_forfeit_winner(
    *,
    tournament: ArenaTournament,
    round_number: int,
    match_index: int,
    attacker_entry: ArenaEntry,
    defender_entry: ArenaEntry,
    attacker_guests: list[ArenaGuestSnapshotProxy],
    defender_guests: list[ArenaGuestSnapshotProxy],
    now,
    match: ArenaMatch | None,
    random_choice: Callable[[list[ArenaEntry]], ArenaEntry],
) -> ArenaEntry | None:
    if not attacker_guests and not defender_guests:
        winner_entry = random_choice([attacker_entry, defender_entry])
        note = "双方均无可用门客，随机判定胜者"
    elif not attacker_guests:
        winner_entry = defender_entry
        note = "攻击方无可用门客，判负"
    elif not defender_guests:
        winner_entry = attacker_entry
        note = "防守方无可用门客，判负"
    else:
        return None

    persist_forfeit_match_resolution(
        tournament=tournament,
        round_number=round_number,
        match_index=match_index,
        attacker_entry=attacker_entry,
        defender_entry=defender_entry,
        winner_entry=winner_entry,
        note=note,
        now=now,
        match=match,
    )
    return winner_entry
