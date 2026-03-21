from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

import gameplay.services.raid.scout as scout_service
from battle.models import TroopTemplate
from core.exceptions import ScoutRetreatStateError, ScoutStartError
from gameplay.constants import PVPConstants
from gameplay.models import PlayerTroop, ScoutRecord
from gameplay.services.manor.core import ensure_manor


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_start_scout_concurrent_requests_allow_only_one_dispatch(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(username="scout_concurrent_attacker", password="pass123")
    defender_user = django_user_model.objects.create_user(username="scout_concurrent_defender", password="pass123")
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    scout_template, _ = TroopTemplate.objects.get_or_create(key=PVPConstants.SCOUT_TROOP_KEY, defaults={"name": "探子"})
    PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 1},
    )

    monkeypatch.setattr(scout_service, "can_attack_target", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(scout_service, "check_scout_cooldown", lambda *_args, **_kwargs: (False, None))
    monkeypatch.setattr(scout_service, "calculate_scout_success_rate", lambda *_args, **_kwargs: 0.5)
    monkeypatch.setattr(scout_service, "calculate_scout_travel_time", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(scout_service.scout_followups, "schedule_scout_completion", lambda *_args, **_kwargs: None)

    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            local_attacker = type(attacker).objects.get(pk=attacker.pk)
            local_defender = type(defender).objects.get(pk=defender.pk)
            barrier.wait(timeout=5)
            record = scout_service.start_scout(local_attacker, local_defender)
            results.append(record.pk)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    troop = PlayerTroop.objects.get(manor=attacker, troop_template=scout_template)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ScoutStartError)
    assert "探子不足" in str(errors[0])
    assert ScoutRecord.objects.filter(attacker=attacker, status=ScoutRecord.Status.SCOUTING).count() == 1
    assert troop.count == 0


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_request_scout_retreat_concurrent_requests_allow_only_one_transition(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(username="scout_retreat_attacker", password="pass123")
    defender_user = django_user_model.objects.create_user(username="scout_retreat_defender", password="pass123")
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    scout_template, _ = TroopTemplate.objects.get_or_create(key=PVPConstants.SCOUT_TROOP_KEY, defaults={"name": "探子"})
    troop, _ = PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 0},
    )

    now = timezone.now()
    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=1,
        success_rate=0.5,
        travel_time=60,
        started_at=now - timedelta(seconds=5),
        complete_at=now + timedelta(seconds=55),
    )

    monkeypatch.setattr(
        scout_service.scout_followups,
        "schedule_scout_return_completion_after_retreat",
        lambda *_args, **_kwargs: None,
    )

    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            local_record = ScoutRecord.objects.get(pk=record.pk)
            barrier.wait(timeout=5)
            scout_service.request_scout_retreat(local_record)
            results.append(local_record.pk)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    record.refresh_from_db()
    troop.refresh_from_db()

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ScoutRetreatStateError)
    assert record.status == ScoutRecord.Status.RETURNING
    assert record.was_retreated is True
    assert record.return_at is not None
    assert troop.count == 1


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_refresh_scout_records_concurrent_with_finalize_scout_transitions_only_once(monkeypatch, django_user_model):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(
        username="scout_refresh_outbound_attacker",
        password="pass123",
    )
    defender_user = django_user_model.objects.create_user(
        username="scout_refresh_outbound_defender",
        password="pass123",
    )
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    now = timezone.now()
    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.SCOUTING,
        scout_cost=1,
        success_rate=1.0,
        travel_time=60,
        started_at=now - timedelta(seconds=60),
        complete_at=now - timedelta(seconds=1),
    )

    gathered: list[int] = []
    gather_lock = threading.Lock()

    def _gather_intel(defender_manor):
        with gather_lock:
            gathered.append(defender_manor.pk)
        return {
            "troop_description": "少量",
            "guest_count": 1,
            "avg_guest_level": 1,
            "asset_level": "普通",
        }

    monkeypatch.setattr(scout_service, "_roll_scout_success", lambda: 0.0)
    monkeypatch.setattr(scout_service, "_gather_scout_intel", _gather_intel)
    monkeypatch.setattr(scout_service.scout_followups, "schedule_scout_followup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        scout_service.scout_followups,
        "schedule_scout_return_completion",
        lambda *_args, **_kwargs: None,
    )

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _finalize_worker() -> None:
        try:
            local_record = ScoutRecord.objects.get(pk=record.pk)
            barrier.wait(timeout=5)
            scout_service.finalize_scout(local_record, now=timezone.now())
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    def _refresh_worker() -> None:
        try:
            local_attacker = type(attacker).objects.get(pk=attacker.pk)
            barrier.wait(timeout=5)
            scout_service.refresh_scout_records(local_attacker, prefer_async=False)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [
        threading.Thread(target=_finalize_worker),
        threading.Thread(target=_refresh_worker),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    record.refresh_from_db()

    assert errors == []
    assert gathered == [defender.pk]
    assert record.status == ScoutRecord.Status.RETURNING
    assert record.is_success is True
    assert record.return_at is not None
    assert record.intel_data["asset_level"] == "普通"
    assert scout_service.ScoutCooldown.objects.filter(attacker=attacker, defender=defender).count() == 1


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_refresh_scout_records_concurrent_with_finalize_scout_return_completes_only_once(
    monkeypatch, django_user_model
):
    if connection.vendor == "sqlite":
        pytest.skip("SQLite does not provide row-level select_for_update semantics for this concurrency scenario")

    attacker_user = django_user_model.objects.create_user(
        username="scout_refresh_return_attacker",
        password="pass123",
    )
    defender_user = django_user_model.objects.create_user(
        username="scout_refresh_return_defender",
        password="pass123",
    )
    attacker = ensure_manor(attacker_user)
    defender = ensure_manor(defender_user)

    scout_template, _ = TroopTemplate.objects.get_or_create(key=PVPConstants.SCOUT_TROOP_KEY, defaults={"name": "探子"})
    troop, _ = PlayerTroop.objects.update_or_create(
        manor=attacker,
        troop_template=scout_template,
        defaults={"count": 0},
    )

    now = timezone.now()
    record = ScoutRecord.objects.create(
        attacker=attacker,
        defender=defender,
        status=ScoutRecord.Status.RETURNING,
        scout_cost=1,
        success_rate=1.0,
        travel_time=60,
        started_at=now - timedelta(seconds=120),
        complete_at=now - timedelta(seconds=60),
        return_at=now - timedelta(seconds=1),
        is_success=True,
        intel_data={
            "troop_description": "少量",
            "guest_count": 1,
            "avg_guest_level": 1,
            "asset_level": "普通",
        },
    )

    followups: list[tuple[str, int]] = []
    followup_lock = threading.Lock()

    def _record_followup(action, current_record, **_kwargs):
        with followup_lock:
            followups.append((action, current_record.pk))

    monkeypatch.setattr(
        scout_service.scout_followups,
        "schedule_scout_followup",
        _record_followup,
    )

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _finalize_worker() -> None:
        try:
            local_record = ScoutRecord.objects.get(pk=record.pk)
            barrier.wait(timeout=5)
            scout_service.finalize_scout_return(local_record, now=timezone.now())
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    def _refresh_worker() -> None:
        try:
            local_attacker = type(attacker).objects.get(pk=attacker.pk)
            barrier.wait(timeout=5)
            scout_service.refresh_scout_records(local_attacker, prefer_async=False)
        except Exception as exc:  # pragma: no cover - validated by assertions below
            errors.append(exc)

    threads = [
        threading.Thread(target=_finalize_worker),
        threading.Thread(target=_refresh_worker),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    record.refresh_from_db()
    troop.refresh_from_db()

    assert errors == []
    assert followups == [("success_result_message", record.pk)]
    assert record.status == ScoutRecord.Status.SUCCESS
    assert record.completed_at is not None
    assert troop.count == 1
