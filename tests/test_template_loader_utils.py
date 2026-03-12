import pytest

from battle.models import TroopTemplate
from gameplay.models import BuildingType, ItemTemplate
from gameplay.models.manor import BuildingCategory, ResourceType
from gameplay.utils.template_loader import (
    clear_building_types_cache,
    get_all_building_types,
    get_guest_templates_by_keys,
    get_item_template_names_by_keys,
    get_item_templates_by_keys,
    get_skills_by_keys,
    get_troop_templates_by_keys,
)
from guests.models import GuestTemplate, Skill


@pytest.mark.django_db
def test_item_template_loaders_normalize_keys_and_preserve_mapping():
    alpha = ItemTemplate.objects.create(key="loader_item_alpha", name="Alpha", effect_type=ItemTemplate.EffectType.TOOL)
    beta = ItemTemplate.objects.create(key="loader_item_beta", name="Beta", effect_type=ItemTemplate.EffectType.TOOL)

    templates = get_item_templates_by_keys(
        [" loader_item_alpha ", "", "loader_item_alpha", "missing", "loader_item_beta"]
    )
    names = get_item_template_names_by_keys(["loader_item_beta", " loader_item_alpha ", "loader_item_beta"])

    assert templates == {
        alpha.key: alpha,
        beta.key: beta,
    }
    assert names == {
        alpha.key: alpha.name,
        beta.key: beta.name,
    }


@pytest.mark.django_db
def test_guest_skill_and_troop_loaders_share_common_template_lookup():
    guest_template = GuestTemplate.objects.create(
        key="loader_guest_alpha",
        name="Guest Alpha",
        rarity="gray",
        archetype="civil",
    )
    skill = Skill.objects.create(key="loader_skill_alpha", name="Skill Alpha")
    troop = TroopTemplate.objects.create(key="loader_troop_alpha", name="Troop Alpha")

    guest_templates = get_guest_templates_by_keys([" loader_guest_alpha ", "loader_guest_alpha"])
    skills = get_skills_by_keys(["loader_skill_alpha", "", "loader_skill_alpha"])
    troops = get_troop_templates_by_keys(["loader_troop_alpha", "missing"])

    assert guest_templates == {guest_template.key: guest_template}
    assert skills == {skill.key: skill}
    assert troops == {troop.key: troop}


@pytest.mark.django_db
def test_get_all_building_types_cache_clear_refreshes_snapshot():
    first = BuildingType.objects.create(
        key="loader_building_alpha",
        name="Building Alpha",
        category=BuildingCategory.RESOURCE,
        resource_type=ResourceType.GRAIN,
    )

    clear_building_types_cache()
    initial_snapshot = get_all_building_types()
    initial_keys = {item.key for item in initial_snapshot}
    assert first.key in initial_keys

    BuildingType.objects.create(
        key="loader_building_beta",
        name="Building Beta",
        category=BuildingCategory.RESOURCE,
        resource_type=ResourceType.SILVER,
    )

    cached_snapshot = get_all_building_types()
    assert {item.key for item in cached_snapshot} == initial_keys

    clear_building_types_cache()
    refreshed_snapshot = get_all_building_types()
    refreshed_keys = {item.key for item in refreshed_snapshot}
    assert refreshed_keys == initial_keys | {"loader_building_beta"}
