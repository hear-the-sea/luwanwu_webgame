import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.selectors.warehouse import _distinct_effect_types, get_warehouse_context
from gameplay.services.manor.core import ensure_manor
from guests.models import Guest, GuestStatus, GuestTemplate

User = get_user_model()


@pytest.mark.django_db
def test_get_warehouse_context_guest_lists_filter_and_order():
    user = User.objects.create_user(username="warehouse_selector_user", password="pass123")
    manor = ensure_manor(user)

    tpl_alpha = GuestTemplate.objects.create(key="ws_alpha", name="Alpha", rarity="gray", archetype="civil")
    tpl_beta = GuestTemplate.objects.create(key="ws_beta", name="Beta", rarity="gray", archetype="civil")
    tpl_gamma = GuestTemplate.objects.create(key="ws_gamma", name="Gamma", rarity="gray", archetype="civil")
    tpl_zeta = GuestTemplate.objects.create(key="ws_zeta", name="Zeta", rarity="gray", archetype="civil")
    tpl_delta = GuestTemplate.objects.create(key="ws_delta", name="Delta", rarity="gray", archetype="civil")

    g_idle_low = Guest.objects.create(manor=manor, template=tpl_zeta, status=GuestStatus.IDLE, level=50)
    g_injured_100 = Guest.objects.create(
        manor=manor,
        template=tpl_alpha,
        status=GuestStatus.INJURED,
        level=100,
        xisuidan_used=3,
    )
    g_idle_100_xisui_ok = Guest.objects.create(
        manor=manor,
        template=tpl_beta,
        status=GuestStatus.IDLE,
        level=100,
        xisuidan_used=1,
        allocated_intellect=2,
    )
    g_idle_100_xisui_limit = Guest.objects.create(
        manor=manor,
        template=tpl_gamma,
        status=GuestStatus.IDLE,
        level=100,
        xisuidan_used=10,
        allocated_force=1,
    )
    Guest.objects.create(
        manor=manor,
        template=tpl_delta,
        status=GuestStatus.WORKING,
        level=100,
        xisuidan_used=0,
        allocated_force=5,
    )

    context = get_warehouse_context(manor, current_tab="warehouse", selected_category="all", page=1)

    assert [guest.id for guest in context["guests_for_rebirth"]] == [
        g_injured_100.id,
        g_idle_100_xisui_ok.id,
        g_idle_100_xisui_limit.id,
        g_idle_low.id,
    ]
    assert [guest.id for guest in context["guests_for_xisuidan"]] == [
        g_idle_100_xisui_ok.id,
        g_injured_100.id,
    ]
    assert [guest.id for guest in context["guests_for_xidianka"]] == [
        g_idle_100_xisui_ok.id,
        g_idle_100_xisui_limit.id,
    ]


@pytest.mark.django_db
def test_distinct_effect_types_clears_order_by_for_distinct():
    user = User.objects.create_user(username="warehouse_effect_types_user", password="pass123")
    manor = ensure_manor(user)
    tpl_a = ItemTemplate.objects.create(key="ws_item_a", name="A", effect_type="tool")
    tpl_b = ItemTemplate.objects.create(key="ws_item_b", name="B", effect_type="skill_book")
    InventoryItem.objects.create(manor=manor, template=tpl_a, quantity=1)
    InventoryItem.objects.create(manor=manor, template=tpl_b, quantity=1)

    ordered_items = manor.inventory_items.select_related("template").order_by("template__name")
    effect_types_qs = _distinct_effect_types(ordered_items)
    sql = str(effect_types_qs.query).upper()

    assert "ORDER BY" not in sql
    assert set(effect_types_qs) == {"tool", "skill_book"}


@pytest.mark.django_db
def test_get_warehouse_context_queries_guest_table_once():
    user = User.objects.create_user(username="warehouse_query_user", password="pass123")
    manor = ensure_manor(user)
    template = GuestTemplate.objects.create(key="ws_query_tpl", name="QueryGuest", rarity="gray", archetype="civil")
    Guest.objects.create(manor=manor, template=template, status=GuestStatus.IDLE, level=10)
    Guest.objects.create(manor=manor, template=template, status=GuestStatus.INJURED, level=20)

    with CaptureQueriesContext(connection) as captured:
        get_warehouse_context(manor, current_tab="warehouse", selected_category="all", page=1)

    guest_queries = [q for q in captured.captured_queries if 'from "guests_guest"' in q["sql"].lower()]
    assert len(guest_queries) == 1


@pytest.mark.django_db
def test_get_warehouse_context_rarity_upgrade_list_only_contains_supported_idle_guests():
    user = User.objects.create_user(username="warehouse_rarity_upgrade_user", password="pass123")
    manor = ensure_manor(user)

    supported_a, _ = GuestTemplate.objects.get_or_create(
        key="hist_sljnbc_0589",
        defaults={
            "name": "邢道荣",
            "rarity": "green",
            "archetype": "military",
        },
    )
    supported_b, _ = GuestTemplate.objects.get_or_create(
        key="hist_sljnbc_0590",
        defaults={
            "name": "潘凤",
            "rarity": "green",
            "archetype": "military",
        },
    )
    unsupported = GuestTemplate.objects.create(
        key="warehouse_other_guest_tpl",
        name="其他门客",
        rarity="green",
        archetype="civil",
    )

    guest_idle_supported_a = Guest.objects.create(manor=manor, template=supported_a, status=GuestStatus.IDLE, level=30)
    guest_idle_supported_b = Guest.objects.create(manor=manor, template=supported_b, status=GuestStatus.IDLE, level=40)
    Guest.objects.create(manor=manor, template=supported_a, status=GuestStatus.INJURED, level=50)
    Guest.objects.create(manor=manor, template=unsupported, status=GuestStatus.IDLE, level=60)

    context = get_warehouse_context(manor, current_tab="warehouse", selected_category="all", page=1)
    assert [guest.id for guest in context["guests_for_rarity_upgrade"]] == [
        guest_idle_supported_b.id,
        guest_idle_supported_a.id,
    ]


@pytest.mark.django_db
def test_get_warehouse_context_rarity_upgrade_reads_source_keys_from_item_templates():
    user = User.objects.create_user(username="warehouse_rarity_payload_user", password="pass123")
    manor = ensure_manor(user)

    supported = GuestTemplate.objects.create(
        key="warehouse_rarity_payload_src",
        name="升阶测试门客",
        rarity="green",
        archetype="military",
    )
    unsupported = GuestTemplate.objects.create(
        key="warehouse_rarity_payload_other",
        name="普通门客",
        rarity="green",
        archetype="civil",
    )

    supported_guest = Guest.objects.create(manor=manor, template=supported, status=GuestStatus.IDLE, level=30)
    Guest.objects.create(manor=manor, template=supported, status=GuestStatus.INJURED, level=20)
    Guest.objects.create(manor=manor, template=unsupported, status=GuestStatus.IDLE, level=40)

    upgrade_token = ItemTemplate.objects.create(
        key="warehouse_rarity_upgrade_token_test",
        name="升阶残卷测试",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
        effect_payload={
            "action": "upgrade_guest_rarity",
            "source_template_keys": ["warehouse_rarity_payload_src"],
            "target_template_map": {
                "warehouse_rarity_payload_src": "warehouse_rarity_payload_target",
            },
        },
    )
    InventoryItem.objects.create(manor=manor, template=upgrade_token, quantity=1)

    context = get_warehouse_context(manor, current_tab="warehouse", selected_category="all", page=1)
    assert [guest.id for guest in context["guests_for_rarity_upgrade"]] == [supported_guest.id]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("current_tab", "storage_location"),
    [
        ("warehouse", InventoryItem.StorageLocation.WAREHOUSE),
        ("treasury", InventoryItem.StorageLocation.TREASURY),
    ],
)
def test_get_warehouse_context_paginates_items_to_twenty(current_tab, storage_location):
    user = User.objects.create_user(username=f"warehouse_page_{current_tab}", password="pass123")
    manor = ensure_manor(user)

    for idx in range(21):
        template = ItemTemplate.objects.create(
            key=f"warehouse_page_{current_tab}_{idx}",
            name=f"分页物品{idx:02d}",
        )
        InventoryItem.objects.create(manor=manor, template=template, quantity=1, storage_location=storage_location)

    first_page = get_warehouse_context(manor, current_tab=current_tab, selected_category="all", page=1)
    second_page = get_warehouse_context(manor, current_tab=current_tab, selected_category="all", page=2)

    assert len(first_page["inventory_items"]) == 20
    assert first_page["pagination"]["total_count"] == 21
    assert first_page["pagination"]["total_pages"] == 2
    assert first_page["pagination"]["has_next"] is True
    assert len(second_page["inventory_items"]) == 1


@pytest.mark.django_db
def test_get_warehouse_context_groups_loot_box_under_tool_category():
    user = User.objects.create_user(username="warehouse_loot_box_tool_category", password="pass123")
    manor = ensure_manor(user)

    loot_box = ItemTemplate.objects.create(
        key="warehouse_work_chest",
        name="打工宝箱",
        effect_type=ItemTemplate.EffectType.LOOT_BOX,
        is_usable=True,
    )
    InventoryItem.objects.create(manor=manor, template=loot_box, quantity=1)

    context = get_warehouse_context(manor, current_tab="warehouse", selected_category="tool", page=1)

    assert [item.template.key for item in context["inventory_items"]] == ["warehouse_work_chest"]
    assert context["inventory_items"][0].category_display == "道具"
    assert any(category["key"] == "tool" for category in context["categories"])
    assert all(category["key"] != ItemTemplate.EffectType.LOOT_BOX for category in context["categories"])
