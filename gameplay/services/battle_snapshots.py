from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable

from django.utils import timezone

from guests.guest_combat_stats import resolve_guest_combat_stats
from guests.guest_rules import compute_guest_troop_capacity
from guests.models import Guest


class _EmptySkillSet:
    @staticmethod
    def all() -> list:
        return []


class BattleGuestSnapshotProxy:
    """门客战斗快照，只保留 battle 构建链路需要的显式字段。"""

    def __init__(self, snapshot: dict[str, Any], *, include_guest_identity: bool = False):
        now = timezone.now()
        guest_id = int(snapshot.get("guest_id") or 0) if include_guest_identity else 0
        guest_manor_id = int(snapshot.get("manor_id") or 0) if include_guest_identity else 0
        self.pk = guest_id or None
        self.id = guest_id or None
        self.manor_id = guest_manor_id or None
        self.is_battle_snapshot_proxy = True
        self.template = SimpleNamespace(
            key=str(snapshot.get("template_key") or "snapshot_unknown"),
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
        self.status = str(snapshot.get("status") or "idle")
        self.last_hp_recovery_at = now
        self.created_at = now
        self.attack = max(1, int(snapshot.get("attack") or 1))
        self.defense = max(1, int(snapshot.get("defense") or 1))
        self.max_hp = max(1, int(snapshot.get("max_hp") or 1))
        self.troop_capacity = max(0, int(snapshot.get("troop_capacity") or 0))
        self.manor = None
        skill_keys = [str(key).strip() for key in (snapshot.get("skill_keys") or []) if str(key).strip()]
        self._override_skills = skill_keys

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def rarity(self) -> str:
        return self._rarity


def _serialize_guest_skill_keys(guest: Any) -> list[str]:
    skills = getattr(guest, "skills", None)
    values_list = getattr(skills, "values_list", None)
    if callable(values_list):
        return [str(key).strip() for key in values_list("key", flat=True) if str(key).strip()]
    return [str(key).strip() for key in (getattr(guest, "_override_skills", None) or []) if str(key).strip()]


def build_guest_battle_snapshot(guest: Any, *, include_identity: bool = True) -> dict[str, Any]:
    stats = resolve_guest_combat_stats(guest)
    troop_capacity = compute_guest_troop_capacity(guest) if isinstance(guest, Guest) else stats.troop_capacity
    current_hp = int(getattr(guest, "current_hp", 0) or 0)
    current_hp = min(stats.max_hp, max(1, current_hp if current_hp > 0 else stats.max_hp))
    payload: dict[str, Any] = {
        "snapshot_version": 1,
        "display_name": guest.display_name,
        "rarity": guest.rarity,
        "status": guest.status,
        "template_key": guest.template.key,
        "level": int(guest.level),
        "force": int(guest.force),
        "intellect": int(guest.intellect),
        "defense_stat": int(guest.defense_stat),
        "agility": int(guest.agility),
        "luck": int(guest.luck),
        "attack": stats.attack,
        "defense": stats.defense,
        "max_hp": stats.max_hp,
        "current_hp": current_hp,
        "troop_capacity": troop_capacity,
        "skill_keys": _serialize_guest_skill_keys(guest),
    }
    if include_identity:
        payload["guest_id"] = int(guest.id)
        payload["manor_id"] = int(guest.manor_id)
    return payload


def build_guest_battle_snapshots(
    guests: Iterable[Guest],
    *,
    include_identity: bool = True,
) -> list[dict[str, Any]]:
    return [build_guest_battle_snapshot(guest, include_identity=include_identity) for guest in guests]


def build_guest_snapshot_proxies(
    snapshots: Iterable[dict[str, Any]],
    *,
    include_guest_identity: bool = False,
) -> list[BattleGuestSnapshotProxy]:
    proxies: list[BattleGuestSnapshotProxy] = []
    for snapshot in snapshots:
        payload = dict(snapshot or {})
        if not payload:
            continue
        proxies.append(BattleGuestSnapshotProxy(payload, include_guest_identity=include_guest_identity))
    return proxies
