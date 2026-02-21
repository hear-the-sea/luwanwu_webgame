from __future__ import annotations

from django.db import migrations, models


def normalize_and_dedupe_emails(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    db_alias = schema_editor.connection.alias

    seen: set[str] = set()
    for user in User.objects.using(db_alias).order_by("id"):
        raw_email = getattr(user, "email", None)
        normalized = (raw_email or "").strip().lower()
        new_value = normalized or None

        if new_value is not None:
            if new_value in seen:
                # Keep first occurrence and null-out duplicates to satisfy unique index.
                new_value = None
            else:
                seen.add(new_value)

        if raw_email != new_value:
            User.objects.using(db_alias).filter(pk=user.pk).update(email=new_value)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(normalize_and_dedupe_emails, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(blank=True, max_length=254, null=True, unique=True, verbose_name="email address"),
        ),
    ]
