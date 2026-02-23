from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable

from django.utils import timezone

from guests.models import Guest


class _EmptySkillSet:
    @staticmethod
    def all() -> list:
        return []


class BattleGuestSnapshotProxy:
    """将门客快照适配为 battle.build_guest_combatants 可消费对象。"""

    def __init__(self, snapshot: dict[str, Any], *, include_guest_identity: bool = False):
        now = timezone.now()
        guest_id = int(snapshot.get("guest_id") or 0) if include_guest_identity else 0
        self.pk = guest_id or None
        self.id = guest_id or None
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
        self._attack = max(1, int(snapshot.get("attack") or 1))
        self._defense = max(1, int(snapshot.get("defense") or 1))
        self._max_hp = max(1, int(snapshot.get("max_hp") or 1))
        self._troop_capacity = max(0, int(snapshot.get("troop_capacity") or 0))
        self.manor = None
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
        return self._troop_capacity

    @property
    def max_hp(self) -> int:
        return self._max_hp

    def save(self, **kwargs) -> None:
        """兼容 battle/services 中的血量恢复逻辑。"""
        return None


def _serialize_guest_skill_keys(guest: Guest) -> list[str]:
    return [str(key).strip() for key in guest.skills.values_list("key", flat=True) if str(key).strip()]


def build_guest_battle_snapshot(guest: Guest, *, include_identity: bool = True) -> dict[str, Any]:
    stats = guest.stat_block()
    max_hp = max(1, int(stats.get("hp") or guest.max_hp or 1))
    current_hp = int(getattr(guest, "current_hp", 0) or 0)
    current_hp = min(max_hp, max(1, current_hp if current_hp > 0 else max_hp))
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
        "attack": max(1, int(stats.get("attack") or 1)),
        "defense": max(1, int(stats.get("defense") or 1)),
        "max_hp": max_hp,
        "current_hp": current_hp,
        "troop_capacity": int(getattr(guest, "troop_capacity", 0) or 0),
        "skill_keys": _serialize_guest_skill_keys(guest),
    }
    if include_identity:
        payload["guest_id"] = int(guest.id)
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
