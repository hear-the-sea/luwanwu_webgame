from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0055_add_loyalty_processed_for_date"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="salarypayment",
            index=models.Index(fields=["for_date"], name="guests_salar_for_date_idx"),
        ),
    ]

