import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0009_guesttemplate_defaults"),
    ]

    operations = [
        migrations.CreateModel(
            name="Skill",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(unique=True)),
                ("name", models.CharField(max_length=64)),
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
                        default="gray",
                        max_length=16,
                    ),
                ),
                ("description", models.TextField(blank=True)),
                ("base_power", models.PositiveIntegerField(default=100)),
                ("base_probability", models.FloatField(default=0.1)),
            ],
            options={
                "verbose_name": "门客技能",
                "verbose_name_plural": "门客技能",
            },
        ),
        migrations.CreateModel(
            name="SkillBook",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(unique=True)),
                ("name", models.CharField(max_length=64)),
                ("description", models.TextField(blank=True)),
                (
                    "skill",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="books", to="guests.skill"),
                ),
            ],
            options={
                "verbose_name": "技能书",
                "verbose_name_plural": "技能书",
            },
        ),
        migrations.CreateModel(
            name="GuestSkill",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "source",
                    models.CharField(
                        choices=[("template", "模板"), ("book", "技能书")], default="template", max_length=16
                    ),
                ),
                ("learned_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "guest",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE, related_name="guest_skills", to="guests.guest"
                    ),
                ),
                ("skill", models.ForeignKey(on_delete=models.deletion.CASCADE, to="guests.skill")),
            ],
            options={
                "verbose_name": "门客技能",
                "verbose_name_plural": "门客技能",
            },
        ),
        migrations.AlterField(
            model_name="guesttemplate",
            name="default_gender",
            field=models.CharField(
                choices=[("male", "男"), ("female", "女"), ("unknown", "未知")], default="unknown", max_length=16
            ),
        ),
        migrations.AlterField(
            model_name="guest",
            name="gender",
            field=models.CharField(
                choices=[("male", "男"), ("female", "女"), ("unknown", "未知")], default="unknown", max_length=16
            ),
        ),
        migrations.AddField(
            model_name="guest",
            name="skills",
            field=models.ManyToManyField(blank=True, through="guests.GuestSkill", to="guests.skill"),
        ),
    ]
