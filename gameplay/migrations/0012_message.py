from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("battle", "0001_initial"),
        ("gameplay", "0011_seed_skill_books"),
    ]

    operations = [
        migrations.CreateModel(
            name="Message",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[("battle", "战报"), ("system", "系统")],
                        default="system",
                        max_length=16,
                    ),
                ),
                ("title", models.CharField(max_length=128)),
                ("body", models.TextField(blank=True)),
                ("is_read", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "battle_report",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="messages",
                        to="battle.battlereport",
                    ),
                ),
                (
                    "manor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="gameplay.manor",
                    ),
                ),
            ],
            options={
                "verbose_name": "消息",
                "verbose_name_plural": "消息",
                "ordering": ("-created_at",),
            },
        ),
    ]
