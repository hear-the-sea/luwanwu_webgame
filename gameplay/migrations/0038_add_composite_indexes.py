from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gameplay', '0037_add_probability_drop_table'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='workassignment',
            index=models.Index(
                fields=['manor', 'status', 'complete_at'],
                name='work_manor_sts_comp_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='inventoryitem',
            index=models.Index(
                fields=['manor', 'storage_location', 'quantity'],
                name='inventory_manor_loc_qty_idx',
            ),
        ),
    ]
