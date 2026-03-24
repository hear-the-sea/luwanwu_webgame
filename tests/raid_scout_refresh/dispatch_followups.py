from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.db import DatabaseError

from gameplay.services.raid import scout as scout_service


def test_run_scout_followup_programming_error_bubbles_up(monkeypatch):
    record = SimpleNamespace(
        attacker=SimpleNamespace(display_name="进攻方", location_display="A-1"),
        defender=SimpleNamespace(display_name="防守方"),
    )

    monkeypatch.setattr(
        scout_service.scout_followups,
        "send_scout_detected_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken scout message contract")),
    )

    with pytest.raises(AssertionError, match="broken scout message contract"):
        scout_service.scout_followups.run_scout_followup("detected_message", record)


def test_run_scout_followup_database_error_is_best_effort(monkeypatch):
    record = SimpleNamespace(
        attacker=SimpleNamespace(display_name="进攻方", location_display="A-1"),
        defender=SimpleNamespace(display_name="防守方"),
    )

    monkeypatch.setattr(
        scout_service.scout_followups,
        "send_scout_detected_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(DatabaseError("message table unavailable")),
    )

    scout_service.scout_followups.run_scout_followup("detected_message", record)


def test_run_scout_followup_runtime_marker_error_bubbles_up(monkeypatch):
    record = SimpleNamespace(
        attacker=SimpleNamespace(display_name="进攻方", location_display="A-1"),
        defender=SimpleNamespace(display_name="防守方"),
    )

    monkeypatch.setattr(
        scout_service.scout_followups,
        "send_scout_detected_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        scout_service.scout_followups.run_scout_followup("detected_message", record)


def test_dispatch_scout_task_nested_import_error_bubbles_up(monkeypatch):
    record = SimpleNamespace(id=17, attacker_id=3, defender_id=5)

    def _raise_import(_task_name):
        exc = ModuleNotFoundError("No module named 'redis'")
        exc.name = "redis"
        raise exc

    monkeypatch.setattr(scout_service.scout_followups.scout_refresh_command, "resolve_scout_task", _raise_import)

    with pytest.raises(ModuleNotFoundError, match="redis"):
        scout_service.scout_followups.dispatch_scout_task(
            "complete_scout_task",
            countdown=30,
            record=record,
            log_message="complete_scout_task dispatch failed",
            false_log_message="complete_scout_task dispatch returned False; scout may remain in outbound state",
        )


def test_dispatch_scout_task_missing_target_module_degrades(monkeypatch):
    record = SimpleNamespace(id=18, attacker_id=3, defender_id=5)

    def _raise_import(_task_name):
        exc = ModuleNotFoundError("No module named 'gameplay.tasks.pvp'")
        exc.name = "gameplay.tasks.pvp"
        raise exc

    monkeypatch.setattr(scout_service.scout_followups.scout_refresh_command, "resolve_scout_task", _raise_import)

    scout_service.scout_followups.dispatch_scout_task(
        "complete_scout_task",
        countdown=30,
        record=record,
        log_message="complete_scout_task dispatch failed",
        false_log_message="complete_scout_task dispatch returned False; scout may remain in outbound state",
    )


def test_dispatch_scout_task_programming_error_bubbles_up(monkeypatch):
    record = SimpleNamespace(id=19, attacker_id=3, defender_id=5)

    monkeypatch.setattr(
        scout_service.scout_followups.scout_refresh_command,
        "resolve_scout_task",
        lambda _task_name: (_ for _ in ()).throw(AssertionError("broken scout task import contract")),
    )

    with pytest.raises(AssertionError, match="broken scout task import contract"):
        scout_service.scout_followups.dispatch_scout_task(
            "complete_scout_task",
            countdown=30,
            record=record,
            log_message="complete_scout_task dispatch failed",
            false_log_message="complete_scout_task dispatch returned False; scout may remain in outbound state",
        )
