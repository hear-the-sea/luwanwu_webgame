from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gameplay", "0013_alter_resourceevent_reason"),
    ]

    def _ensure_is_read(apps, schema_editor):
        Message = apps.get_model("gameplay", "Message")
        connection = schema_editor.connection
        table = Message._meta.db_table
        column = "is_read"
        with connection.cursor() as cursor:
            columns = [col.name for col in connection.introspection.get_table_description(cursor, table)]
            if column in columns:
                return
        # Column missing, add it with default False
        field = models.BooleanField(default=False)
        field.set_attributes_from_name(column)
        schema_editor.add_field(Message, field)

    operations = [
        migrations.RunPython(_ensure_is_read, migrations.RunPython.noop),
    ]
