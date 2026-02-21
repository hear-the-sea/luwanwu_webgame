from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


@dataclass(frozen=True)
class TableIssue:
    table: str
    message: str


def _expected_columns_for_model(model) -> set[str]:
    return {field.column for field in model._meta.concrete_fields if field.column}


def _actual_columns_for_table(table: str) -> set[str] | None:
    with connection.cursor() as cursor:
        try:
            description = connection.introspection.get_table_description(cursor, table)
        except Exception:
            return None
    return {col.name for col in description}


class Command(BaseCommand):
    help = "Checks guild-related DB tables for missing columns (useful for diagnosing 1054 Unknown column errors)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            default="guilds",
            help="App label to check (default: guilds).",
        )

    def handle(self, *args, **options):
        app_label: str = options["app"]
        app_config = apps.get_app_config(app_label)

        issues: list[TableIssue] = []
        checked_tables: set[str] = set()

        for model in app_config.get_models():
            table = model._meta.db_table
            if not table or table in checked_tables:
                continue
            checked_tables.add(table)

            expected_columns = _expected_columns_for_model(model)
            actual_columns = _actual_columns_for_table(table)
            if actual_columns is None:
                issues.append(TableIssue(table=table, message="table missing or not introspectable"))
                continue

            missing = sorted(expected_columns - actual_columns)
            if missing:
                issues.append(TableIssue(table=table, message=f"missing columns: {', '.join(missing)}"))

        if not issues:
            self.stdout.write(
                self.style.SUCCESS(f"OK: {app_label} schema looks consistent ({len(checked_tables)} tables checked).")
            )
            return

        self.stdout.write(self.style.ERROR(f"Found {len(issues)} schema issue(s) in app '{app_label}':"))
        for issue in issues:
            self.stdout.write(f"- {issue.table}: {issue.message}")

        self.stdout.write(
            "Suggested next step: run `python manage.py migrate` (or app-specific migrate) to sync schema."
        )
        raise SystemExit(1)
