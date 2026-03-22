import pytest
from django.db import transaction
from django.utils import timezone

from core.exceptions import InsufficientStockError, ItemNotFoundError, MessageError
from gameplay.models import (
    HorseProduction,
    InventoryItem,
    ItemTemplate,
    LivestockProduction,
    PlayerTechnology,
    SmeltingProduction,
)
from gameplay.services.buildings.ranch import finalize_livestock_production
from gameplay.services.buildings.smithy import finalize_smelting_production
from gameplay.services.buildings.stable import finalize_horse_production
from gameplay.services.inventory.core import (
    add_item_to_inventory,
    add_item_to_inventory_locked,
    consume_inventory_item,
    consume_inventory_item_locked,
)
from gameplay.services.manor.core import ensure_manor, finalize_building_upgrade
from gameplay.services.technology import finalize_technology_upgrade


@pytest.mark.django_db
def test_consume_inventory_item_is_safe_with_stale_instances(django_user_model):
    user = django_user_model.objects.create_user(username="inv_stale", password="pass12345")
    manor = ensure_manor(user)

    tpl = ItemTemplate.objects.create(
        key="inv_stale_item",
        name="并发测试道具",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
    )
    item = InventoryItem.objects.create(
        manor=manor,
        template=tpl,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    # Two separate ORM instances representing the same row.
    item_a = InventoryItem.objects.select_related("template").get(pk=item.pk)
    item_b = InventoryItem.objects.select_related("template").get(pk=item.pk)

    consume_inventory_item(item_a, 1)
    with pytest.raises(InsufficientStockError):
        consume_inventory_item(item_b, 1)

    assert not InventoryItem.objects.filter(pk=item.pk).exists()


@pytest.mark.django_db
def test_consume_inventory_item_by_key_is_safe_when_row_disappears(django_user_model):
    user = django_user_model.objects.create_user(username="inv_key_stale", password="pass12345")
    manor = ensure_manor(user)

    tpl = ItemTemplate.objects.create(
        key="inv_key_stale_item",
        name="键扣除道具",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
    )
    add_item_to_inventory(manor, tpl.key, 1)

    consume_inventory_item(manor, tpl.key, 1)
    with pytest.raises(InsufficientStockError):
        consume_inventory_item(manor, tpl.key, 1)


@pytest.mark.django_db
def test_consume_inventory_item_rejects_unsaved_item_instance(django_user_model):
    user = django_user_model.objects.create_user(username="inv_unsaved_item", password="pass12345")
    manor = ensure_manor(user)

    tpl = ItemTemplate.objects.create(
        key="inv_unsaved_item_tpl",
        name="未保存道具",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
    )
    unsaved = InventoryItem(
        manor=manor,
        template=tpl,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    with pytest.raises(ItemNotFoundError, match="物品不存在"):
        consume_inventory_item(unsaved, 1)


@pytest.mark.django_db(transaction=True)
def test_consume_inventory_item_locked_rejects_unsaved_item_instance(django_user_model):
    user = django_user_model.objects.create_user(username="inv_unsaved_locked", password="pass12345")
    manor = ensure_manor(user)

    tpl = ItemTemplate.objects.create(
        key="inv_unsaved_locked_tpl",
        name="未保存锁定道具",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
    )
    unsaved = InventoryItem(
        manor=manor,
        template=tpl,
        quantity=1,
        storage_location=InventoryItem.StorageLocation.WAREHOUSE,
    )

    with transaction.atomic():
        with pytest.raises(ItemNotFoundError, match="物品不存在"):
            consume_inventory_item_locked(unsaved, 1)


@pytest.mark.django_db(transaction=True)
def test_add_item_to_inventory_locked_requires_positive_quantity(django_user_model):
    user = django_user_model.objects.create_user(username="inv_add_positive_locked", password="pass12345")
    manor = ensure_manor(user)

    tpl = ItemTemplate.objects.create(
        key="inv_add_positive_locked_tpl",
        name="加库存校验道具",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
    )

    with transaction.atomic():
        with pytest.raises(AssertionError, match="requires positive quantity"):
            add_item_to_inventory_locked(manor, tpl.key, 0)


@pytest.mark.django_db
def test_add_item_to_inventory_requires_positive_quantity(django_user_model):
    user = django_user_model.objects.create_user(username="inv_add_positive", password="pass12345")
    manor = ensure_manor(user)

    tpl = ItemTemplate.objects.create(
        key="inv_add_positive_tpl",
        name="加库存包装校验道具",
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
    )

    with pytest.raises(AssertionError, match="requires positive quantity"):
        add_item_to_inventory(manor, tpl.key, 0)


@pytest.mark.django_db
def test_finalize_building_upgrade_is_safe_with_stale_instances(django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_stale", password="pass12345")
    manor = ensure_manor(user)

    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    before_level = building.level
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    b1 = building.__class__.objects.get(pk=building.pk)
    b2 = building.__class__.objects.get(pk=building.pk)

    assert finalize_building_upgrade(b1, now=now, send_notification=False) is True
    assert finalize_building_upgrade(b2, now=now, send_notification=False) is False

    building.refresh_from_db()
    assert building.level == before_level + 1
    assert building.is_upgrading is False
    assert building.upgrade_complete_at is None


@pytest.mark.django_db
def test_finalize_technology_upgrade_is_safe_with_stale_instances(django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_stale", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    t1 = PlayerTechnology.objects.get(pk=tech.pk)
    t2 = PlayerTechnology.objects.get(pk=tech.pk)

    assert finalize_technology_upgrade(t1, send_notification=False) is True
    assert finalize_technology_upgrade(t2, send_notification=False) is False

    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False
    assert tech.upgrade_complete_at is None


@pytest.mark.django_db
def test_finalize_building_upgrade_keeps_success_when_notification_fails(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_notify_fail", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    before_level = building.level
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MessageError("message backend down")),
    )
    monkeypatch.setattr(
        "gameplay.services.manor.core.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("ws backend down")),
    )

    assert finalize_building_upgrade(building, now=now, send_notification=True) is True
    building.refresh_from_db()
    assert building.level == before_level + 1
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_building_upgrade_message_runtime_marker_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_msg_runtime", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        finalize_building_upgrade(building, now=now, send_notification=True)

    building.refresh_from_db()
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_building_upgrade_message_programming_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_msg_programming", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken building message contract")),
    )

    with pytest.raises(AssertionError, match="broken building message contract"):
        finalize_building_upgrade(building, now=now, send_notification=True)

    building.refresh_from_db()
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_building_upgrade_notification_runtime_marker_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_ws_runtime", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.manor.core.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    with pytest.raises(RuntimeError, match="ws backend down"):
        finalize_building_upgrade(building, now=now, send_notification=True)

    building.refresh_from_db()
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_building_upgrade_notification_programming_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="building_finalize_ws_programming", password="pass12345")
    manor = ensure_manor(user)
    building = manor.buildings.select_related("building_type").first()
    assert building is not None

    now = timezone.now()
    building.is_upgrading = True
    building.upgrade_complete_at = now - timezone.timedelta(seconds=1)
    building.save(update_fields=["is_upgrading", "upgrade_complete_at"])

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.manor.core.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken building notify contract")),
    )

    with pytest.raises(AssertionError, match="broken building notify contract"):
        finalize_building_upgrade(building, now=now, send_notification=True)

    building.refresh_from_db()
    assert building.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_keeps_success_when_notification_message_fails(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_notify_fail", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    def _raise_create_message(*_args, **_kwargs):
        raise MessageError("message backend down")

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", _raise_create_message)

    assert finalize_technology_upgrade(tech, send_notification=True) is True
    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_message_runtime_marker_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_msg_runtime", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        finalize_technology_upgrade(tech, send_notification=True)

    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_message_programming_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_msg_programming", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken technology message contract")),
    )

    with pytest.raises(AssertionError, match="broken technology message contract"):
        finalize_technology_upgrade(tech, send_notification=True)

    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_keeps_success_when_notification_ws_fails(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_notify_ws_fail", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("ws backend down")),
    )

    assert finalize_technology_upgrade(tech, send_notification=True) is True
    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_notification_runtime_marker_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_ws_runtime", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    with pytest.raises(RuntimeError, match="ws backend down"):
        finalize_technology_upgrade(tech, send_notification=True)

    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


@pytest.mark.django_db
def test_finalize_technology_upgrade_notification_programming_error_bubbles_up(monkeypatch, django_user_model):
    user = django_user_model.objects.create_user(username="tech_finalize_ws_programming", password="pass12345")
    manor = ensure_manor(user)

    now = timezone.now()
    tech = PlayerTechnology.objects.create(
        manor=manor,
        tech_key="march_art",
        level=0,
        is_upgrading=True,
        upgrade_complete_at=now - timezone.timedelta(seconds=1),
    )

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "gameplay.services.utils.notifications.notify_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken technology notify contract")),
    )

    with pytest.raises(AssertionError, match="broken technology notify contract"):
        finalize_technology_upgrade(tech, send_notification=True)

    tech.refresh_from_db()
    assert tech.level == 1
    assert tech.is_upgrading is False


_PRODUCTION_NOTIFICATION_CASES = [
    (
        "horse",
        HorseProduction,
        finalize_horse_production,
        "gameplay.services.utils.notifications.notify_user",
        {
            "key_field": "horse_key",
            "name_field": "horse_name",
            "key": "horse_notify_item",
            "name": "测试马匹",
            "extra": {"grain_cost": 10},
        },
    ),
    (
        "livestock",
        LivestockProduction,
        finalize_livestock_production,
        "gameplay.services.buildings.ranch.notify_user",
        {
            "key_field": "livestock_key",
            "name_field": "livestock_name",
            "key": "livestock_notify_item",
            "name": "测试家畜",
            "extra": {"grain_cost": 12},
        },
    ),
    (
        "smelting",
        SmeltingProduction,
        finalize_smelting_production,
        "gameplay.services.buildings.smithy.notify_user",
        {
            "key_field": "metal_key",
            "name_field": "metal_name",
            "key": "smelting_notify_item",
            "name": "测试金属",
            "extra": {"cost_type": "silver", "cost_amount": 15},
        },
    ),
]


def _create_completed_notification_production(*, manor, model_cls, fields: dict):
    item_key = fields["key"]
    item_name = fields["name"]
    ItemTemplate.objects.create(
        key=item_key,
        name=item_name,
        effect_type=ItemTemplate.EffectType.TOOL,
        is_usable=False,
    )
    kwargs = {
        "manor": manor,
        fields["key_field"]: item_key,
        fields["name_field"]: item_name,
        "quantity": 2,
        "base_duration": 60,
        "actual_duration": 60,
        "complete_at": timezone.now() - timezone.timedelta(seconds=1),
        "status": model_cls.Status.PRODUCING,
        **fields["extra"],
    }
    return model_cls.objects.create(**kwargs)


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_func", "notify_user_path", "fields"),
    _PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_message_programming_error_bubbles_up(
    _label,
    model_cls,
    finalize_func,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_msg_programming", password="pass12345")
    manor = ensure_manor(user)
    production = _create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken production message contract")),
    )

    with pytest.raises(AssertionError, match="broken production message contract"):
        finalize_func(production, send_notification=True)

    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_func", "notify_user_path", "fields"),
    _PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_keeps_success_when_message_infra_fails(
    _label,
    model_cls,
    finalize_func,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_msg_fail", password="pass12345")
    manor = ensure_manor(user)
    production = _create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MessageError("message backend down")),
    )

    assert finalize_func(production, send_notification=True) is True
    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_func", "notify_user_path", "fields"),
    _PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_message_runtime_marker_error_bubbles_up(
    _label,
    model_cls,
    finalize_func,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_msg_runtime", password="pass12345")
    manor = ensure_manor(user)
    production = _create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr(
        "gameplay.services.utils.messages.create_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("message backend down")),
    )

    with pytest.raises(RuntimeError, match="message backend down"):
        finalize_func(production, send_notification=True)

    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_func", "notify_user_path", "fields"),
    _PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_notification_programming_error_bubbles_up(
    _label,
    model_cls,
    finalize_func,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_ws_programming", password="pass12345")
    manor = ensure_manor(user)
    production = _create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        notify_user_path,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broken production notify contract")),
    )

    with pytest.raises(AssertionError, match="broken production notify contract"):
        finalize_func(production, send_notification=True)

    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_func", "notify_user_path", "fields"),
    _PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_keeps_success_when_notification_infra_fails(
    _label,
    model_cls,
    finalize_func,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_ws_fail", password="pass12345")
    manor = ensure_manor(user)
    production = _create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        notify_user_path,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("ws backend down")),
    )

    assert finalize_func(production, send_notification=True) is True
    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED


@pytest.mark.parametrize(
    ("_label", "model_cls", "finalize_func", "notify_user_path", "fields"),
    _PRODUCTION_NOTIFICATION_CASES,
)
@pytest.mark.django_db
def test_production_finalize_notification_runtime_marker_error_bubbles_up(
    _label,
    model_cls,
    finalize_func,
    notify_user_path,
    fields,
    monkeypatch,
    django_user_model,
):
    user = django_user_model.objects.create_user(username=f"{_label}_ws_runtime", password="pass12345")
    manor = ensure_manor(user)
    production = _create_completed_notification_production(manor=manor, model_cls=model_cls, fields=fields)

    monkeypatch.setattr("gameplay.services.utils.messages.create_message", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        notify_user_path,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ws backend down")),
    )

    with pytest.raises(RuntimeError, match="ws backend down"):
        finalize_func(production, send_notification=True)

    production.refresh_from_db()
    assert production.status == model_cls.Status.COMPLETED
