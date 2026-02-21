"""
Pytest 配置和共享 fixtures
"""

import os
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import transaction

from battle.models import TroopTemplate
from gameplay.models import PlayerTroop

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


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
