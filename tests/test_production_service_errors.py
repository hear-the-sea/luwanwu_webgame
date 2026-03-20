from __future__ import annotations

import pytest

from core.exceptions import ProductionStartError
from gameplay.services.buildings.ranch import start_livestock_production
from gameplay.services.buildings.smithy import start_smelting_production
from gameplay.services.buildings.stable import start_horse_production
from gameplay.services.manor.core import ensure_manor


def _create_manor(username: str, django_user_model):
    user = django_user_model.objects.create_user(username=username, password="pass123")
    manor = ensure_manor(user)
    manor.grain = 500000
    manor.silver = 500000
    manor.save(update_fields=["grain", "silver"])
    return manor


@pytest.mark.django_db
def test_start_horse_production_rejects_invalid_type_with_explicit_error(django_user_model):
    manor = _create_manor("production_horse_invalid", django_user_model)

    with pytest.raises(ProductionStartError, match="无效的马匹类型"):
        start_horse_production(manor, "not_exists", 1)


@pytest.mark.django_db
def test_start_livestock_production_rejects_invalid_type_with_explicit_error(django_user_model):
    manor = _create_manor("production_livestock_invalid", django_user_model)

    with pytest.raises(ProductionStartError, match="无效的家畜类型"):
        start_livestock_production(manor, "not_exists", 1)


@pytest.mark.django_db
def test_start_smelting_production_rejects_invalid_type_with_explicit_error(django_user_model):
    manor = _create_manor("production_smelting_invalid", django_user_model)

    with pytest.raises(ProductionStartError, match="无效的制作类型"):
        start_smelting_production(manor, "not_exists", 1)
