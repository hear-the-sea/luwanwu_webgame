from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from gameplay.services.raid import scout as scout_service


def test_refresh_scout_records_prefers_async_dispatch(monkeypatch):
    class _Status:
        SCOUTING = "scouting"
        RETURNING = "returning"

    class _ScoutObjects:
        def __init__(self):
            self._status = None

        def filter(self, **kwargs):
            self._status = kwargs.get("status")
            return self

        def values_list(self, *_args, **_kwargs):
            mapping = {
                _Status.SCOUTING: [11, 12],
                _Status.RETURNING: [13],
            }
            return list(mapping.get(self._status, []))

    dummy_cls = type("_ScoutRecord", (), {"Status": _Status, "objects": _ScoutObjects()})
    monkeypatch.setattr(scout_service, "ScoutRecord", dummy_cls)

    dispatched = []

    def _dispatch(_task, record_id, phase):
        dispatched.append((record_id, phase))
        return True

    monkeypatch.setattr(scout_service, "_try_dispatch_scout_refresh_task", _dispatch)

    called = {"scout": 0, "return": 0}
    monkeypatch.setattr(
        scout_service,
        "finalize_scout",
        lambda *_args, **_kwargs: called.__setitem__("scout", called["scout"] + 1),
    )
    monkeypatch.setattr(
        scout_service,
        "finalize_scout_return",
        lambda *_args, **_kwargs: called.__setitem__("return", called["return"] + 1),
    )

    scout_service.refresh_scout_records(SimpleNamespace(id=7), prefer_async=True)

    assert set(dispatched) == {(11, "outbound"), (12, "outbound"), (13, "return")}
    assert called == {"scout": 0, "return": 0}


def test_send_scout_success_message_tolerates_invalid_intel_shape(monkeypatch):
    sent = {}

    def _create_message(*, manor, kind, title, body):
        sent.update({"manor": manor, "kind": kind, "title": title, "body": body})

    monkeypatch.setattr(scout_service, "create_message", _create_message)

    record = SimpleNamespace(
        intel_data=["bad-shape"],
        attacker=SimpleNamespace(id=1),
        defender=SimpleNamespace(display_name="目标庄园"),
    )

    scout_service._send_scout_success_message(record)

    assert sent["manor"].id == 1
    assert sent["kind"] == "system"
    assert "侦察报告" in sent["title"]
    assert "未知" in sent["body"]


def test_start_scout_rechecks_attack_constraints_inside_transaction(monkeypatch):
    attacker = SimpleNamespace(pk=1, id=1)
    defender = SimpleNamespace(pk=2, id=2)
    calls = {"can_attack": 0}

    def _fake_can_attack(*_args, **_kwargs):
        calls["can_attack"] += 1
        if calls["can_attack"] == 1:
            return True, ""
        return False, "对方处于免战牌保护期"

    monkeypatch.setattr(scout_service.transaction, "atomic", contextlib.nullcontext)
    monkeypatch.setattr(scout_service, "can_attack_target", _fake_can_attack)
    monkeypatch.setattr(scout_service, "check_scout_cooldown", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(scout_service, "get_scout_count", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(scout_service, "_lock_manor_pair", lambda *_args, **_kwargs: (attacker, defender))

    with pytest.raises(ValueError, match="免战牌保护期"):
        scout_service.start_scout(attacker, defender)

    assert calls["can_attack"] == 2


def test_start_scout_precheck_uses_uncached_attack_check(monkeypatch):
    attacker = SimpleNamespace(pk=1, id=1)
    defender = SimpleNamespace(pk=2, id=2)
    seen = {"use_cached_recent_attacks": None, "check_defeat_protection": None}

    def _fake_can_attack(*_args, **kwargs):
        seen["use_cached_recent_attacks"] = kwargs.get("use_cached_recent_attacks")
        seen["check_defeat_protection"] = kwargs.get("check_defeat_protection")
        return False, "blocked"

    monkeypatch.setattr(scout_service, "can_attack_target", _fake_can_attack)

    with pytest.raises(ValueError, match="blocked"):
        scout_service.start_scout(attacker, defender)

    assert seen["use_cached_recent_attacks"] is False
    assert seen["check_defeat_protection"] is False
