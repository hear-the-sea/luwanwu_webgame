import pytest

from core.exceptions import GuildWarehouseError
from gameplay.models import ItemTemplate
from gameplay.services.manor.core import ensure_manor
from guilds.models import Guild, GuildMember, GuildWarehouse
from guilds.services.warehouse import add_item_to_warehouse, exchange_item


@pytest.fixture
def guild_member_with_warehouse_item(django_user_model):
    leader = django_user_model.objects.create_user(username="guild_wh_leader", password="pass123")
    ensure_manor(leader)
    guild = Guild.objects.create(name="仓库帮", founder=leader, is_active=True)
    member = GuildMember.objects.create(guild=guild, user=leader, position="leader", current_contribution=100)
    ItemTemplate.objects.create(
        key="guild_wh_item",
        name="帮会仓库道具",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=True,
    )
    GuildWarehouse.objects.create(guild=guild, item_key="guild_wh_item", quantity=10, contribution_cost=5)
    return guild, member


@pytest.mark.django_db
def test_add_item_to_warehouse_rejects_non_positive_quantity(guild_member_with_warehouse_item):
    guild, _member = guild_member_with_warehouse_item

    with pytest.raises(GuildWarehouseError, match="产出数量必须为正整数"):
        add_item_to_warehouse(guild, "guild_wh_item", 0, 5)

    with pytest.raises(GuildWarehouseError, match="产出数量必须为正整数"):
        add_item_to_warehouse(guild, "guild_wh_item", -1, 5)


@pytest.mark.django_db
def test_add_item_to_warehouse_rejects_negative_cost(guild_member_with_warehouse_item):
    guild, _member = guild_member_with_warehouse_item

    with pytest.raises(GuildWarehouseError, match="兑换成本不能为负数"):
        add_item_to_warehouse(guild, "guild_wh_item", 1, -1)


@pytest.mark.django_db
def test_exchange_item_rejects_non_positive_quantity(guild_member_with_warehouse_item):
    _guild, member = guild_member_with_warehouse_item

    with pytest.raises(GuildWarehouseError, match="兑换数量必须为正整数"):
        exchange_item(member, "guild_wh_item", 0)

    with pytest.raises(GuildWarehouseError, match="兑换数量必须为正整数"):
        exchange_item(member, "guild_wh_item", -3)
