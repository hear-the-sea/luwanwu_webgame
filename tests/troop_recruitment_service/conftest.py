import pytest

from gameplay.services.manor.core import ensure_manor


@pytest.fixture
def recruit_manor(django_user_model):
    user = django_user_model.objects.create_user(username="troop_recruit_user", password="pass123")
    manor = ensure_manor(user)
    manor.retainer_count = 20
    manor.save(update_fields=["retainer_count"])
    return manor
