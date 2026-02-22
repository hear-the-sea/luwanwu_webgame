from __future__ import annotations

from gameplay.views.missions import TaskBoardView


def test_build_troop_config_tolerates_invalid_priority(monkeypatch):
    monkeypatch.setattr(
        "battle.troops.load_troop_templates",
        lambda: {
            "invalid_priority": {"label": "无效优先级", "priority": "oops"},
            "normal_priority": {"label": "正常优先级", "priority": 2},
        },
    )

    _templates, config_items = TaskBoardView()._build_troop_config()

    assert [entry["key"] for entry in config_items] == ["invalid_priority", "normal_priority"]
