from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_CONFTST_PATH = Path(__file__).with_name("conftest.py")
_SPEC = importlib.util.spec_from_file_location("_repo_conftest", _CONFTST_PATH)
assert _SPEC is not None and _SPEC.loader is not None
conftest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(conftest)


def test_require_external_cache_backend_skips_locmem():
    settings = SimpleNamespace(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})

    with pytest.raises(pytest.skip.Exception, match="external cache backend"):
        conftest._require_external_cache_backend(settings, cache=SimpleNamespace())


def test_require_external_channel_layer_skips_inmemory_backend():
    settings = SimpleNamespace(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})

    with pytest.raises(pytest.skip.Exception, match="external channel layer backend"):
        conftest._require_external_channel_layer(settings, channel_layer=SimpleNamespace())


def test_require_external_celery_broker_skips_memory_broker():
    celery_app = SimpleNamespace(conf=SimpleNamespace(broker_url="memory://", result_backend="cache+memory://"))

    with pytest.raises(pytest.skip.Exception, match="external Celery broker"):
        conftest._require_external_celery_broker(celery_app)


def test_require_external_celery_broker_accepts_reachable_connection():
    ensured = {"count": 0}

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ensure_connection(self, max_retries: int = 1):
            ensured["count"] += 1
            assert max_retries == 1

    class _CeleryApp:
        conf = SimpleNamespace(
            broker_url="redis://127.0.0.1:6379/0",
            result_backend="redis://127.0.0.1:6379/1",
        )

        def connection(self):
            return _Connection()

    conftest._require_external_celery_broker(_CeleryApp())

    assert ensured["count"] == 1
