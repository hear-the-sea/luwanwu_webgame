from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0096_manor_arena_participation_date_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="workassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "working")),
                fields=("manor", "work_template"),
                name="uniq_working_assignment_per_work",
            ),
        ),
    ]
