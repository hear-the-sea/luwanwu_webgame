"""
Pytest 配置和共享 fixtures
"""
import pytest
from django.core.management import call_command
from django.db import transaction

from battle.models import TroopTemplate
from gameplay.models import PlayerTroop


@pytest.fixture(scope="session", autouse=True)
def loadGameData(django_db_setup, django_db_blocker):
    """
    在测试会话开始时加载游戏数据
    autouse=True 确保所有测试自动使用此 fixture
    """
    # 需要解除数据库阻塞才能访问数据库
    with django_db_blocker.unblock():
        # 加载护院模板数据
        call_command("load_troop_templates", verbosity=0)


@pytest.fixture(scope="function")
def manor_with_troops(django_user_model):
    """
    创建拥有基础护院的庄园和用户
    用于测试需要护院的场景（如出征）
    """
    from gameplay.services.manor import ensure_manor

    user = django_user_model.objects.create_user(username="troop_player", password="pass123")
    manor = ensure_manor(user)

    # 在事务外创建护院（使用 transaction.atomic 确保提交）
    common_troop_types = ["archer", "dao_jie", "qiang_ling", "jian_shi", "fist_master"]

    with transaction.atomic():
        for troop_key in common_troop_types:
            troop_template = TroopTemplate.objects.filter(key=troop_key).first()
            if troop_template:
                PlayerTroop.objects.get_or_create(
                    manor=manor,
                    troop_template=troop_template,
                    defaults={"count": 1000}
                )

    return manor
