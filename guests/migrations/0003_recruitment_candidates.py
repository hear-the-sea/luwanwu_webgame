from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0005_seed_silver_content"),
        ("guests", "0002_seed_initial_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="guest",
            name="custom_name",
            field=models.CharField(blank=True, max_length=64, verbose_name="自定义称号"),
        ),
        migrations.AddField(
            model_name="recruitmentpool",
            name="tier",
            field=models.CharField(
                choices=[
                    ("tongshi", "童试"),
                    ("xiangshi", "乡试"),
                    ("huishi", "会试"),
                    ("dianshi", "殿试"),
                ],
                default="tongshi",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="recruitmentpool",
            name="draw_count",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.CreateModel(
            name="RecruitmentCandidate",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("display_name", models.CharField(max_length=64)),
                (
                    "rarity",
                    models.CharField(
                        choices=[
                            ("black", "黑"),
                            ("gray", "灰"),
                            ("green", "绿"),
                            ("blue", "蓝"),
                            ("red", "红"),
                            ("purple", "紫"),
                            ("orange", "橙"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "archetype",
                    models.CharField(
                        choices=[("civil", "文"), ("military", "武")],
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "manor",
                    models.ForeignKey(on_delete=models.CASCADE, related_name="candidates", to="gameplay.manor"),
                ),
                (
                    "pool",
                    models.ForeignKey(on_delete=models.CASCADE, to="guests.recruitmentpool"),
                ),
                (
                    "template",
                    models.ForeignKey(on_delete=models.CASCADE, to="guests.guesttemplate"),
                ),
            ],
            options={
                "verbose_name": "招募候选",
                "verbose_name_plural": "招募候选",
                "ordering": ("created_at",),
            },
        ),
    ]
