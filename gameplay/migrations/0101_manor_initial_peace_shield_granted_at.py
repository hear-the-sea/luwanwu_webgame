from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0100_remove_test_temporary_skills_mission"),
    ]

    operations = [
        migrations.AddField(
            model_name="manor",
            name="initial_peace_shield_granted_at",
            field=models.DateTimeField(
                blank=True,
                help_text="记录新手初始免战牌的发放时间，确保初始化失败后可安全重试且不会重复补发。",
                null=True,
                verbose_name="初始免战牌发放时间",
            ),
        ),
    ]
