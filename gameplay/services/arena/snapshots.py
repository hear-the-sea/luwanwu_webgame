from __future__ import annotations

from types import SimpleNamespace
from typing import Any


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
        self._override_skills = [str(key).strip() for key in (snapshot.get("skill_keys") or []) if str(key).strip()]

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
        return 0


def serialize_guest_skill_keys(guest) -> list[str]:
    return [str(key).strip() for key in guest.skills.values_list("key", flat=True) if str(key).strip()]


def build_entry_guest_snapshot(guest) -> dict[str, Any]:
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
        "skill_keys": serialize_guest_skill_keys(guest),
    }


def load_entry_guests(entry, *, max_guests_per_entry: int = 10) -> list[ArenaGuestSnapshotProxy]:
    proxies: list[ArenaGuestSnapshotProxy] = []
    links = list(entry.entry_guests.order_by("created_at", "id")[: max(1, int(max_guests_per_entry))])
    for link in links:
        snapshot = dict(link.snapshot or {})
        if not snapshot and getattr(link, "guest", None):
            snapshot = build_entry_guest_snapshot(link.guest)
        if not snapshot:
            continue
        proxies.append(ArenaGuestSnapshotProxy(snapshot))
    return proxies
