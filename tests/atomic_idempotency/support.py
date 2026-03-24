from django.utils import timezone

from gameplay.models import HorseProduction, ItemTemplate, LivestockProduction, SmeltingProduction

PRODUCTION_NOTIFICATION_CASES = [
    (
        "horse",
        HorseProduction,
        "gameplay.services.buildings.stable.finalize_horse_production",
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
        "gameplay.services.buildings.ranch.finalize_livestock_production",
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
        "gameplay.services.buildings.smithy.finalize_smelting_production",
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


def create_completed_notification_production(*, manor, model_cls, fields: dict):
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
