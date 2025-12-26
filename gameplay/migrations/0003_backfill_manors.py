from django.conf import settings
from django.db import migrations


def create_manors_for_existing_users(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    Manor = apps.get_model("gameplay", "Manor")
    BuildingType = apps.get_model("gameplay", "BuildingType")
    Building = apps.get_model("gameplay", "Building")

    for user in User.objects.all():
        manor, created = Manor.objects.get_or_create(user=user)
        if not created:
            continue
        for building_type in BuildingType.objects.all():
            Building.objects.get_or_create(manor=manor, building_type=building_type)


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0002_seed_core_data"),
    ]

    operations = [
        migrations.RunPython(create_manors_for_existing_users, reverse_code=migrations.RunPython.noop),
    ]
