import pytest
from django.contrib.auth import get_user_model

from gameplay.models import InventoryItem, ItemTemplate
from gameplay.services.manor.core import ensure_manor
from gameplay.services.raid import combat as raid_combat


@pytest.mark.django_db
def test_calculate_loot_uses_sampling_path_for_large_inventories(monkeypatch):
    """
    覆盖大库存抽样路径（A+B）：避免遍历全部库存。
    这里通过降低阈值来触发抽样逻辑，并用确定性随机数避免测试抖动。
    """
    monkeypatch.setattr(raid_combat, "LOOT_ITEM_SMALL_INVENTORY_THRESHOLD", 10)
    monkeypatch.setattr(raid_combat, "LOOT_ITEM_SAMPLE_BATCH_SIZE", 6)
    monkeypatch.setattr(raid_combat, "LOOT_ITEM_SAMPLE_MAX_BATCHES", 3)

    # 固定随机：确保每个候选都命中掠夺、数量取最小值
    monkeypatch.setattr(raid_combat.random, "random", lambda: 0.0)
    monkeypatch.setattr(raid_combat.random, "uniform", lambda a, b: 0.2)
    monkeypatch.setattr(raid_combat.random, "randint", lambda a, b: a)

    User = get_user_model()
    defender_user = User.objects.create_user(username="loot_defender", password="pass123")
    defender = ensure_manor(defender_user)
    defender.grain = 0
    defender.silver = 0
    defender.save(update_fields=["grain", "silver"])

    # 生成足够多的可交易物品（>阈值），确保进入抽样路径
    for idx in range(20):
        template = ItemTemplate.objects.create(
            key=f"loot_item_{idx}",
            name=f"Loot Item {idx}",
            rarity="black",
            tradeable=True,
        )
        InventoryItem.objects.create(
            manor=defender,
            template=template,
            quantity=10,
            storage_location=InventoryItem.StorageLocation.WAREHOUSE,
        )

    loot_resources, loot_items = raid_combat._calculate_loot(defender)
    assert loot_resources == {}
    assert len(loot_items) == raid_combat.PVPConstants.LOOT_ITEM_MAX_COUNT
    assert all(isinstance(k, str) and k for k in loot_items.keys())
    assert all(1 <= v <= raid_combat.PVPConstants.LOOT_ITEM_MAX_QUANTITY for v in loot_items.values())
