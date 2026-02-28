from __future__ import annotations

import pytest

from gameplay.models import PlayerTechnology
from gameplay.services.manor.core import ensure_manor
from gameplay.services.recruitment import recruitment as recruitment_service
from gameplay.services.recruitment.recruitment import get_max_recruit_quantity, get_recruitment_options


@pytest.mark.django_db
def test_get_max_recruit_quantity_scales_with_recruit_tech_level(django_user_model):
    user = django_user_model.objects.create_user(username="recruit_limit_user", password="pass123")
    manor = ensure_manor(user)

    PlayerTechnology.objects.update_or_create(manor=manor, tech_key="dao_recruit", defaults={"level": 3})

    assert get_max_recruit_quantity(manor, "dao_ke") == 150
    assert get_max_recruit_quantity(manor, "scout") == 10


@pytest.mark.django_db
def test_get_recruitment_options_contains_dynamic_max_quantity(django_user_model):
    user = django_user_model.objects.create_user(username="recruit_options_user", password="pass123")
    manor = ensure_manor(user)
    PlayerTechnology.objects.update_or_create(manor=manor, tech_key="dao_recruit", defaults={"level": 2})

    options = get_recruitment_options(manor)
    dao_option = next(option for option in options if option["key"] == "dao_ke")

    assert dao_option["max_quantity"] == 100


@pytest.mark.django_db
def test_validate_start_recruitment_inputs_rejects_over_max_quantity(django_user_model, monkeypatch):
    user = django_user_model.objects.create_user(username="recruit_validate_user", password="pass123")
    manor = ensure_manor(user)

    monkeypatch.setattr(manor, "get_building_level", lambda _key: 1)
    monkeypatch.setattr(recruitment_service, "has_active_recruitment", lambda _manor: False)
    monkeypatch.setattr(
        recruitment_service,
        "get_troop_template",
        lambda _troop_key: {
            "name": "测试护院",
            "recruit": {"tech_key": "dao_recruit", "tech_level": 1, "equipment": [], "retainer_cost": 1},
        },
    )
    monkeypatch.setattr(recruitment_service, "get_max_recruit_quantity", lambda *_args, **_kwargs: 50)
    monkeypatch.setattr(
        recruitment_service,
        "check_recruitment_requirements",
        lambda *_args, **_kwargs: {"can_recruit": True, "errors": []},
    )

    with pytest.raises(ValueError, match="单次最多招募50人"):
        recruitment_service._validate_start_recruitment_inputs(manor, "dao_ke", quantity=51)
