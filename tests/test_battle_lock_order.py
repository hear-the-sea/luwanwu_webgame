from __future__ import annotations

from types import SimpleNamespace

import pytest

import battle.services as battle_services


@pytest.mark.django_db
def test_lock_guests_for_battle_locks_manor_before_guests(monkeypatch):
    events: list[str] = []

    guest = SimpleNamespace(id=1, pk=1)
    manor = SimpleNamespace(pk=99)

    class _ManorObjects:
        def select_for_update(self):
            events.append("manor_lock")
            return self

        def filter(self, pk__in):
            events.append(f"manor_filter:{sorted(pk__in)}")
            return self

        def order_by(self, *_args):
            return self

        def values_list(self, *_args, **_kwargs):
            events.append(f"manor_values:{manor.pk}")
            return [manor.pk]

    monkeypatch.setattr("gameplay.models.Manor", SimpleNamespace(objects=_ManorObjects()))
    monkeypatch.setattr(
        battle_services,
        "_lock_guest_rows",
        lambda guest_ids: events.append(f"guest_lock:{guest_ids}") or [guest],
    )
    monkeypatch.setattr(battle_services, "_validate_locked_guest_statuses", lambda _locked: None)
    monkeypatch.setattr(battle_services, "_mark_locked_guests_deployed", lambda _locked: events.append("mark"))
    monkeypatch.setattr(battle_services, "_refresh_guest_instances", lambda _guests: None)
    monkeypatch.setattr(battle_services, "_release_deployed_guests", lambda _ids: events.append("release"))

    with battle_services.lock_guests_for_battle([guest], manor=manor):
        events.append("inside")

    manor_lock_idx = events.index("manor_lock")
    guest_lock_idx = next(i for i, item in enumerate(events) if item.startswith("guest_lock:"))
    assert manor_lock_idx < guest_lock_idx
    assert "inside" in events
