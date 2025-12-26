from django.db import migrations


def set_default_troops(apps, schema_editor):
    GuestTemplate = apps.get_model("guests", "GuestTemplate")
    mapping = {
        "black_civil_proto": "archer",
        "black_military_proto": "spearman",
        "li_qing": "archer",
        "hong_fu": "cavalry",
        "sun_bin": "archer",
        "mo_zi": "archer",
        "wu_qi": "cavalry",
        "bai_qi": "spearman",
        "liu_bei": "spearman",
    }
    for key, troop in mapping.items():
        GuestTemplate.objects.filter(key=key).update(default_troop=troop)


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0013_guesttemplate_default_troop"),
    ]

    operations = [
        migrations.RunPython(set_default_troops, migrations.RunPython.noop),
    ]
