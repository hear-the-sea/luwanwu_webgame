from django.db import migrations


def seed_inventory(apps, schema_editor):
    ItemTemplate = apps.get_model("gameplay", "ItemTemplate")
    InventoryItem = apps.get_model("gameplay", "InventoryItem")
    Manor = apps.get_model("gameplay", "Manor")

    templates_data = [
        (
            "supply_small",
            "基础补给箱",
            "使用后获得少量基础资源。",
            {"wood": 500, "grain": 500, "stone": 300},
        ),
        (
            "supply_large",
            "高级补给箱",
            "使用后获得大量资源。",
            {"wood": 1000, "grain": 1000, "iron": 600, "silver": 400},
        ),
    ]
    template_map = {}
    for key, name, desc, payload in templates_data:
        template, _ = ItemTemplate.objects.get_or_create(
            key=key,
            defaults={"name": name, "description": desc, "effect_payload": payload},
        )
        template_map[key] = template

    for manor in Manor.objects.all():
        InventoryItem.objects.get_or_create(
            manor=manor,
            template=template_map["supply_small"],
            defaults={"quantity": 2},
        )
        InventoryItem.objects.get_or_create(
            manor=manor,
            template=template_map["supply_large"],
            defaults={"quantity": 1},
        )


def remove_inventory(apps, schema_editor):
    ItemTemplate = apps.get_model("gameplay", "ItemTemplate")
    InventoryItem = apps.get_model("gameplay", "InventoryItem")
    InventoryItem.objects.all().delete()
    ItemTemplate.objects.filter(key__in=["supply_small", "supply_large"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0009_warehouse_items"),
    ]

    operations = [
        migrations.RunPython(seed_inventory, remove_inventory),
    ]
