"""
Pytest 配置和共享 fixtures
"""

import os
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.management import call_command
from django.db import transaction
from django.test import Client

from battle.models import TroopTemplate
from gameplay.models import PlayerTroop
from gameplay.services.manor.core import ensure_manor

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


def _require_non_sqlite_database(settings) -> None:
    db_engine = str(settings.DATABASES["default"].get("ENGINE", ""))
    if "sqlite" in db_engine:
        pytest.skip("integration tests require non-sqlite database backend")


def _require_external_cache_backend(settings, cache) -> None:
    cache_backend = str(settings.CACHES["default"].get("BACKEND", "")).lower()
    if "locmem" in cache_backend:
        pytest.skip("integration tests require external cache backend")

    probe_key = "integration:services:probe"
    try:
        cache.set(probe_key, "1", timeout=5)
        if cache.get(probe_key) != "1":
            pytest.skip("integration tests require a writable external cache backend")
        cache.delete(probe_key)
    except Exception as exc:
        pytest.skip(f"integration tests require reachable external cache backend: {exc}")


def _require_external_channel_layer(settings, channel_layer) -> None:
    default_layer = settings.CHANNEL_LAYERS.get("default", {})
    backend = str(default_layer.get("BACKEND", "")).lower()
    if "inmemory" in backend:
        pytest.skip("integration tests require external channel layer backend")
    if channel_layer is None:
        pytest.skip("integration tests require configured channel layer")

    try:
        channel_name = async_to_sync(channel_layer.new_channel)("integration.probe.")
        payload = {"type": "integration.probe", "value": "ok"}
        async_to_sync(channel_layer.send)(channel_name, payload)
        received = async_to_sync(channel_layer.receive)(channel_name)
        if received != payload:
            pytest.skip("integration tests require reliable external channel layer backend")
    except Exception as exc:
        pytest.skip(f"integration tests require reachable external channel layer backend: {exc}")


def _require_external_celery_broker(celery_app) -> None:
    broker_url = str(getattr(celery_app.conf, "broker_url", "") or "")
    result_backend = str(getattr(celery_app.conf, "result_backend", "") or "")
    if not broker_url or broker_url.startswith("memory://"):
        pytest.skip("integration tests require external Celery broker")
    if result_backend.startswith("cache+memory://"):
        pytest.skip("integration tests require external Celery result backend")

    try:
        with celery_app.connection() as connection:
            connection.ensure_connection(max_retries=1)
    except Exception as exc:
        pytest.skip(f"integration tests require reachable Celery broker: {exc}")


@pytest.fixture(scope="session")
def game_data(django_db_setup, django_db_blocker):
    """Load shared game templates used by integration-style tests.

    Notes:
    - Not autouse: avoids slowing down unit-like tests.
    - Uses `skip_images=True` to keep tests fast and hermetic.
    """
    with django_db_blocker.unblock():
        original_cwd = os.getcwd()
        os.chdir(PROJECT_ROOT)
        try:
            # Ensure schema exists when running a narrow subset of tests.
            from django.db import connection

            if "django_migrations" not in connection.introspection.table_names():
                call_command("migrate", verbosity=0, interactive=False)

            call_command("load_troop_templates", verbosity=0, skip_images=True)
            call_command("load_guest_templates", verbosity=0, skip_images=True)
        finally:
            os.chdir(original_cwd)


@pytest.fixture(scope="function")
def mission_templates(django_db_setup, django_db_blocker):
    """
    在每个测试中加载任务模板（需要事务支持）
    """
    with django_db_blocker.unblock():
        original_cwd = os.getcwd()
        os.chdir(PROJECT_ROOT)
        try:
            call_command("load_mission_templates", file="data/mission_templates.yaml", verbosity=0)
        finally:
            os.chdir(original_cwd)


@pytest.fixture(scope="function")
def manor_with_troops(django_user_model, django_db_blocker):
    """
    创建拥有基础护院的庄园和用户
    用于测试需要护院的场景（如出征）
    """
    from gameplay.services.manor.core import ensure_manor
    from guests.models import GuestTemplate

    user = django_user_model.objects.create_user(username="troop_player", password="pass123")
    manor = ensure_manor(user)

    # 需要解除数据库阻塞才能访问数据库
    with django_db_blocker.unblock():
        if not TroopTemplate.objects.exists():
            call_command("load_troop_templates", verbosity=0, skip_images=True)

        # 在事务外创建护院（使用 transaction.atomic 确保提交）
        common_troop_types = ["archer", "dao_jie", "qiang_ling", "jian_shi", "fist_master"]

        with transaction.atomic():
            for troop_key in common_troop_types:
                troop_template = TroopTemplate.objects.filter(key=troop_key).first()
                if troop_template:
                    PlayerTroop.objects.get_or_create(
                        manor=manor, troop_template=troop_template, defaults={"count": 1000}
                    )

        # 确保至少有一个门客模板（用于测试）
        if not GuestTemplate.objects.exists():
            call_command("load_guest_templates", verbosity=0, skip_images=True)

    return manor


@pytest.fixture
def authenticated_client(django_user_model):
    """返回已登录的测试客户端。"""
    user = django_user_model.objects.create_user(username="testplayer", password="testpass123")
    client = Client()
    client.login(username="testplayer", password="testpass123")
    client.user = user
    return client


@pytest.fixture
def manor_with_user(authenticated_client):
    """返回带庄园的用户。"""
    manor = ensure_manor(authenticated_client.user)
    return manor, authenticated_client


@pytest.fixture(scope="session")
def require_env_services():
    """Skip integration tests unless external DB/cache/channel/celery services are enabled."""
    if os.environ.get("DJANGO_TEST_USE_ENV_SERVICES", "0") != "1":
        pytest.skip("integration tests require DJANGO_TEST_USE_ENV_SERVICES=1")

    from django.conf import settings
    from django.core.cache import cache

    from config.celery import app as celery_app

    _require_non_sqlite_database(settings)
    _require_external_cache_backend(settings, cache)
    _require_external_channel_layer(settings, get_channel_layer())
    _require_external_celery_broker(celery_app)
