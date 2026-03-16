from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gameplay", "0101_manor_initial_peace_shield_granted_at"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="trooprecruitment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "recruiting")),
                fields=("manor",),
                name="uniq_active_troop_recruitment_per_manor",
            ),
        ),
    ]
