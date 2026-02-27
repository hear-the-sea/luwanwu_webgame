from __future__ import annotations

from types import SimpleNamespace

from django.utils import timezone

from gameplay.services.raid import utils as raid_utils


def test_get_recent_attacks_24h_uses_cache_when_enabled(monkeypatch):
    defender = SimpleNamespace(id=9)
    calls = {"count": 0}
    cache_store: dict[str, int] = {}

    class _QS:
        @staticmethod
        def count():
            calls["count"] += 1
            return 3

    class _Objects:
        @staticmethod
        def filter(**_kwargs):
            return _QS()

    monkeypatch.setattr(raid_utils, "RaidRun", type("_RaidRun", (), {"objects": _Objects()}))
    monkeypatch.setattr(raid_utils, "_safe_cache_get", lambda key: cache_store.get(key))
    monkeypatch.setattr(raid_utils, "_safe_cache_set", lambda key, value, timeout: cache_store.__setitem__(key, value))

    now = timezone.now()
    assert raid_utils.get_recent_attacks_24h(defender, now=now, use_cache=True) == 3
    assert raid_utils.get_recent_attacks_24h(defender, now=now, use_cache=True) == 3
    assert calls["count"] == 1


def test_get_recent_attacks_24h_skips_cache_when_disabled(monkeypatch):
    defender = SimpleNamespace(id=11)
    calls = {"count": 0}

    class _QS:
        @staticmethod
        def count():
            calls["count"] += 1
            return 2

    class _Objects:
        @staticmethod
        def filter(**_kwargs):
            return _QS()

    monkeypatch.setattr(raid_utils, "RaidRun", type("_RaidRun", (), {"objects": _Objects()}))
    monkeypatch.setattr(
        raid_utils,
        "_safe_cache_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache should not be used")),
    )
    monkeypatch.setattr(
        raid_utils,
        "_safe_cache_set",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache should not be used")),
    )

    now = timezone.now()
    assert raid_utils.get_recent_attacks_24h(defender, now=now, use_cache=False) == 2
    assert raid_utils.get_recent_attacks_24h(defender, now=now, use_cache=False) == 2
    assert calls["count"] == 2


def test_invalidate_recent_attacks_cache_deletes_expected_key(monkeypatch):
    deleted = {"key": None}
    monkeypatch.setattr(raid_utils, "_safe_cache_delete", lambda key: deleted.__setitem__("key", key))

    raid_utils.invalidate_recent_attacks_cache(15)

    assert deleted["key"] == "raid:recent_attacks_24h:15"


def test_can_attack_target_can_bypass_cached_recent_attacks(monkeypatch):
    attacker = SimpleNamespace(
        id=1,
        is_under_newbie_protection=False,
        is_under_defeat_protection=False,
        is_under_peace_shield=False,
        prestige=1000,
    )
    defender = SimpleNamespace(
        id=2,
        is_under_newbie_protection=False,
        is_under_defeat_protection=False,
        is_under_peace_shield=False,
        prestige=1000,
    )

    limit = raid_utils.PVPConstants.RAID_MAX_DAILY_ATTACKS_RECEIVED

    def _fake_recent_attacks(_defender, now=None, *, use_cache=True):
        return limit if use_cache else 0

    monkeypatch.setattr(raid_utils, "get_recent_attacks_24h", _fake_recent_attacks)

    blocked, blocked_reason = raid_utils.can_attack_target(attacker, defender, use_cached_recent_attacks=True)
    allowed, allowed_reason = raid_utils.can_attack_target(attacker, defender, use_cached_recent_attacks=False)

    assert blocked is False
    assert "多次攻击" in blocked_reason
    assert allowed is True
    assert allowed_reason == ""


def test_can_attack_target_blocks_defender_defeat_protection():
    attacker = SimpleNamespace(
        id=1,
        is_under_newbie_protection=False,
        is_under_defeat_protection=False,
        is_under_peace_shield=False,
        prestige=1000,
    )
    defender = SimpleNamespace(
        id=2,
        is_under_newbie_protection=False,
        is_under_defeat_protection=True,
        is_under_peace_shield=False,
        prestige=1000,
    )

    allowed, reason = raid_utils.can_attack_target(attacker, defender)
    assert allowed is False
    assert "战败保护期" in reason
