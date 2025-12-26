from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0008_alter_resourceevent_reason"),
    ]

    operations = [
        migrations.CreateModel(
            name="ItemTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(unique=True)),
                ("name", models.CharField(max_length=64)),
                ("description", models.TextField(blank=True)),
                (
                    "effect_type",
                    models.CharField(
                        choices=[("resource_pack", "资源补给"), ("skill_book", "技能书")],
                        default="resource_pack",
                        max_length=32,
                    ),
                ),
                ("effect_payload", models.JSONField(blank=True, default=dict)),
                ("icon", models.CharField(blank=True, max_length=32)),
            ],
            options={
                "verbose_name": "物品模板",
                "verbose_name_plural": "物品模板",
            },
        ),
        migrations.CreateModel(
            name="InventoryItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "manor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_items",
                        to="gameplay.manor",
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_entries",
                        to="gameplay.itemtemplate",
                    ),
                ),
            ],
            options={
                "verbose_name": "仓库物品",
                "verbose_name_plural": "仓库物品",
                "unique_together": {("manor", "template")},
            },
        ),
    ]
