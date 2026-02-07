from __future__ import annotations


def test_import_core_config_constants():
    # core.config is currently otherwise uncovered; ensure importing and using
    # constants doesn't break.
    from core import config as core_config

    assert core_config.GUEST.MAX_LEVEL >= 1
    assert core_config.RARITY.SALARY["gray"] == 1000


def test_import_config_entrypoints_and_throttling():
    from config import asgi as config_asgi
    from config import throttling
    from config import wsgi as config_wsgi

    assert config_wsgi.application is not None
    assert config_asgi.application is not None
    assert throttling.RecruitThrottle.scope == "recruit"
    assert throttling.BattleThrottle.scope == "battle"
    assert throttling.ClaimThrottle.scope == "claim"


def test_import_tasks_compat_modules():
    from tasks import celery as tasks_celery

    assert tasks_celery.celery_app is not None
