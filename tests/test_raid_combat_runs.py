from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

import pytest

from gameplay.services.raid.combat import runs as combat_runs


def test_send_raid_incoming_message_builds_body(monkeypatch):
    sent = {}

    def _create_message(*, manor, kind, title, body):
        sent.update({"manor": manor, "kind": kind, "title": title, "body": body})

    monkeypatch.setattr(combat_runs, "create_message", _create_message)

    run = SimpleNamespace(
        attacker=SimpleNamespace(location_display="江南", display_name="张三"),
        defender=SimpleNamespace(id=2),
        battle_at=datetime(2026, 2, 7, 12, 0, tzinfo=dt_timezone.utc),
    )

    combat_runs._send_raid_incoming_message(run)

    assert sent["manor"].id == 2
    assert sent["kind"] == "system"
    assert "敌军来袭" in sent["title"]
    assert "江南" in sent["body"]
    assert "张三" in sent["body"]


def test_can_raid_retreat_requires_marching(monkeypatch):
    class _Status:
        MARCHING = "marching"

    monkeypatch.setattr(combat_runs, "RaidRun", type("_RaidRun", (), {"Status": _Status}))

    run = SimpleNamespace(status="other", is_retreating=False)
    assert combat_runs.can_raid_retreat(run) is False

    run.status = _Status.MARCHING
    assert combat_runs.can_raid_retreat(run) is True

    run.is_retreating = True
    assert combat_runs.can_raid_retreat(run) is False


def test_return_surviving_troops_returns_all_when_no_report(monkeypatch):
    called = {}

    def _add_batch(_manor, payload):
        called["payload"] = payload

    monkeypatch.setattr(combat_runs, "_add_troops_batch", _add_batch)

    run = SimpleNamespace(attacker=object(), troop_loadout={"inf": 5}, battle_report=None)
    combat_runs._return_surviving_troops(run)

    assert called["payload"] == {"inf": 5}


def test_return_surviving_troops_filters_casualties(monkeypatch):
    monkeypatch.setattr("battle.troops.load_troop_templates", lambda: {"inf": {"label": "步兵"}})

    called = {}

    def _add_batch(_manor, payload):
        called["payload"] = payload

    monkeypatch.setattr(combat_runs, "_add_troops_batch", _add_batch)

    report = SimpleNamespace(
        losses={
            "attacker": {
                "casualties": [
                    {"key": "inf", "lost": 2},
                    {"key": "unknown", "lost": 99},
                    {"key": "inf", "lost": "bad"},
                ]
            }
        }
    )
    run = SimpleNamespace(attacker=object(), troop_loadout={"inf": 5}, battle_report=report)

    combat_runs._return_surviving_troops(run)

    assert called["payload"] == {"inf": 3}


def test_deduct_troops_raises_when_missing(monkeypatch):
    class _PlayerTroop:
        objects = SimpleNamespace(
            select_for_update=lambda: SimpleNamespace(
                filter=lambda **_kwargs: SimpleNamespace(select_related=lambda *_a, **_k: [])
            )
        )

    monkeypatch.setattr(combat_runs, "PlayerTroop", _PlayerTroop)

    with pytest.raises(ValueError, match="没有该类型的护院"):
        combat_runs._deduct_troops(SimpleNamespace(), {"inf": 1})


def test_refresh_raid_runs_prefers_async_dispatch(monkeypatch):
    class _Status:
        MARCHING = "marching"
        RETURNING = "returning"
        RETREATED = "retreated"

    class _RaidObjects:
        def __init__(self):
            self._status = None

        def filter(self, **kwargs):
            self._status = kwargs.get("status")
            return self

        def values_list(self, *_args, **_kwargs):
            mapping = {
                _Status.MARCHING: [1, 2],
                _Status.RETURNING: [3],
                _Status.RETREATED: [4],
            }
            return list(mapping.get(self._status, []))

    dummy_cls = type("_RaidRun", (), {"Status": _Status, "objects": _RaidObjects()})
    monkeypatch.setattr(combat_runs, "RaidRun", dummy_cls)

    dispatched = []

    def _dispatch(_task, run_id, stage):
        dispatched.append((run_id, stage))
        return True

    monkeypatch.setattr(combat_runs, "_try_dispatch_raid_refresh_task", _dispatch)

    called = {"battle": 0, "finalize": 0}
    monkeypatch.setattr(
        "gameplay.services.raid.combat.battle.process_raid_battle",
        lambda *_args, **_kwargs: called.__setitem__("battle", called["battle"] + 1),
    )
    monkeypatch.setattr(
        combat_runs,
        "finalize_raid",
        lambda *_args, **_kwargs: called.__setitem__("finalize", called["finalize"] + 1),
    )

    combat_runs.refresh_raid_runs(SimpleNamespace(id=9), prefer_async=True)

    assert set(dispatched) == {(1, "battle"), (2, "battle"), (3, "return"), (4, "return")}
    assert called == {"battle": 0, "finalize": 0}
