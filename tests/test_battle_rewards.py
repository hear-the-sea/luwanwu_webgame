from battle.rewards import dispatch_battle_message, grant_battle_rewards


class DummyManor:
    def __init__(self):
        self.log = []


def test_grant_battle_rewards_uses_locked_path_in_atomic(monkeypatch):
    manor = type("M", (), {"pk": 1})()
    drops = {"silver": 100}
    captured = {}

    monkeypatch.setattr("battle.rewards._in_atomic_block", lambda: True)
    monkeypatch.setattr(
        "battle.rewards._grant_resources_locked",
        lambda manor_arg, drops_arg, label: captured.setdefault("args", (manor_arg, drops_arg, label)),
    )
    monkeypatch.setattr(
        "battle.rewards._grant_resources",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("should not call non-locked path")),
    )

    grant_battle_rewards(manor, drops, "test opponent")

    assert captured["args"] == (manor, drops, "test opponent")


def test_grant_battle_rewards_uses_normal_path_outside_atomic(monkeypatch):
    manor = DummyManor()
    drops = {"grain": 10}
    captured = {}

    monkeypatch.setattr("battle.rewards._in_atomic_block", lambda: False)
    monkeypatch.setattr(
        "battle.rewards._grant_resources",
        lambda manor_arg, drops_arg, label: captured.setdefault("args", (manor_arg, drops_arg, label)),
    )
    monkeypatch.setattr(
        "battle.rewards._grant_resources_locked",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("should not call locked path")),
    )

    grant_battle_rewards(manor, drops, "normal path")

    assert captured["args"] == (manor, drops, "normal path")


def test_grant_battle_rewards_uses_handler(monkeypatch):
    manor = DummyManor()
    drops = {"silver": 100}
    called = {}

    def handler(payload):
        called["drops"] = payload

    # Patch the default grant to ensure it would fail if invoked
    monkeypatch.setattr(
        "battle.rewards._grant_resources",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not grant")),
    )

    grant_battle_rewards(manor, drops, "test opponent", drop_handler=handler)

    assert called["drops"] == drops


def test_grant_battle_rewards_defaults_to_auto(monkeypatch):
    manor = DummyManor()
    drops = {"grain": 50}
    recorded = {}

    def fake_grant(manor_arg, drops_arg, opponent_label):
        recorded["args"] = (manor_arg, drops_arg, opponent_label)

    monkeypatch.setattr("battle.rewards._grant_resources", fake_grant)

    grant_battle_rewards(manor, drops, "Mountain Bandits", auto_reward=True, drop_handler=None)

    assert recorded["args"] == (manor, drops, "Mountain Bandits")


def test_dispatch_battle_message_calls_service(monkeypatch):
    manor = DummyManor()
    report = object()
    captured = {}

    def fake_create(manor_arg, opponent_label, report_arg):
        captured["values"] = (manor_arg, opponent_label, report_arg)

    monkeypatch.setattr("battle.rewards._create_message", fake_create)

    dispatch_battle_message(manor, "Border Clash", report)

    assert captured["values"] == (manor, "Border Clash", report)
