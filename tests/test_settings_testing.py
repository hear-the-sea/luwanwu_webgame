from __future__ import annotations

import importlib

import pytest

from config.settings import testing as testing_settings


def _reload_testing_settings(monkeypatch: pytest.MonkeyPatch, eager: str | None):
    if eager is None:
        monkeypatch.delenv("DJANGO_TEST_CELERY_EAGER", raising=False)
    else:
        monkeypatch.setenv("DJANGO_TEST_CELERY_EAGER", eager)
    return importlib.reload(testing_settings)


@pytest.fixture(autouse=True)
def _restore_testing_settings(monkeypatch: pytest.MonkeyPatch):
    yield
    monkeypatch.delenv("DJANGO_TEST_CELERY_EAGER", raising=False)
    importlib.reload(testing_settings)


def test_testing_settings_default_celery_not_eager(monkeypatch: pytest.MonkeyPatch):
    module = _reload_testing_settings(monkeypatch, eager=None)

    assert module.CELERY_TASK_ALWAYS_EAGER is False
    assert module.CELERY_TASK_EAGER_PROPAGATES is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_testing_settings_celery_eager_can_be_enabled(monkeypatch: pytest.MonkeyPatch, value: str):
    module = _reload_testing_settings(monkeypatch, eager=value)

    assert module.CELERY_TASK_ALWAYS_EAGER is True
    assert module.CELERY_TASK_EAGER_PROPAGATES is True
