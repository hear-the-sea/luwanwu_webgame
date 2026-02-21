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
