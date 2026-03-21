from types import SimpleNamespace

import gameplay.services.battle_salvage as battle_salvage_service
import gameplay.services.missions_impl.execution as mission_execution


def test_mission_salvage_passes_player_side_to_equipment_recovery(monkeypatch):
    called = {}

    def _fake_salvage(report, *args, **kwargs):
        called["report"] = report
        called["kwargs"] = kwargs
        return 3, {"equip_duandao": 2}

    monkeypatch.setattr(battle_salvage_service, "calculate_battle_salvage", _fake_salvage)

    locked_run = SimpleNamespace(mission=SimpleNamespace(is_defense=False, drop_table={}), id=99)
    report = SimpleNamespace(drops={"silver": 10}, id=7)

    drops = mission_execution._build_mission_drops_with_salvage(locked_run, report, "defender")

    assert called["report"] is report
    assert called["kwargs"].get("equipment_casualty_side") == "defender"
    assert drops["silver"] == 10
    assert drops["experience_fruit"] == 3
    assert drops["equip_duandao"] == 2


def test_mission_salvage_programming_error_bubbles_up(monkeypatch):
    monkeypatch.setattr(
        battle_salvage_service,
        "calculate_battle_salvage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken salvage contract")),
    )

    locked_run = SimpleNamespace(mission=SimpleNamespace(is_defense=False, drop_table={}), id=100)
    report = SimpleNamespace(drops={"silver": 10}, id=8)

    with __import__("pytest").raises(AssertionError, match="broken salvage contract"):
        mission_execution._build_mission_drops_with_salvage(locked_run, report, "attacker")
