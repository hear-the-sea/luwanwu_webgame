from __future__ import annotations

from battle.tasks import generate_report_task


def assert_no_retry(monkeypatch, *, message: str = "retry should not be called") -> None:
    monkeypatch.setattr(
        generate_report_task,
        "retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError(message)),
    )
