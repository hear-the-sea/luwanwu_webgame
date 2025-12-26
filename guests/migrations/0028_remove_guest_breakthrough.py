from django.db import migrations


def clamp_hp(apps, schema_editor):
    Guest = apps.get_model("guests", "Guest")
    GuestTemplate = apps.get_model("guests", "GuestTemplate")
    template_map = {tpl.pk: tpl for tpl in GuestTemplate.objects.all()}
    for guest in Guest.objects.all():
        tpl = template_map.get(getattr(guest, "template_id", None))
        if tpl:
            levels = max(0, (guest.level or 1) - 1)
            base_hp = (tpl.base_hp or 0) + (tpl.hp_growth or 0) * levels + (guest.hp_bonus or 0)
            max_hp = max(200, base_hp)
        else:
            max_hp = max(200, guest.hp_bonus or 0)
        if guest.current_hp > max_hp:
            guest.current_hp = max_hp
            guest.save(update_fields=["current_hp"])


def _drop_breakthrough_column_if_exists(apps, schema_editor):
    """
    Drop the legacy `breakthrough` column only on backends that support it.

    SQLite lacks INFORMATION_SCHEMA and ALTER TABLE DROP COLUMN support, so we
    skip it there to keep tests runnable. Other backends use introspection to
    verify the column exists before attempting to drop it.
    """
    connection = schema_editor.connection
    if connection.vendor == "sqlite":
        return
    table_name = "guests_guest"
    column_name = "breakthrough"
    quote_name = connection.ops.quote_name
    with connection.cursor() as cursor:
        columns = [col.name for col in connection.introspection.get_table_description(cursor, table_name)]
        if column_name not in columns:
            return
        if connection.vendor == "postgresql":
            drop_sql = f"ALTER TABLE {quote_name(table_name)} DROP COLUMN IF EXISTS {quote_name(column_name)};"
        else:
            drop_sql = f"ALTER TABLE {quote_name(table_name)} DROP COLUMN {quote_name(column_name)};"
        cursor.execute(drop_sql)


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0027_remove_guest_morale"),
    ]

    operations = [
        migrations.RunPython(_drop_breakthrough_column_if_exists, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="guest",
                    name="breakthrough",
                )
            ]
        ),
        migrations.RunPython(clamp_hp, migrations.RunPython.noop),
    ]
