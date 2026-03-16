from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.utils.yaml_schema import validate_all_configs


class Command(BaseCommand):
    help = "Validate all YAML game configuration files against their schemas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data"),
            help="Path to the data directory containing YAML config files.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run validation without side effects (same behavior, flag for CI clarity).",
        )

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"])
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write("Dry-run mode: validating configs without side effects.")

        if not data_dir.exists():
            self.stderr.write(self.style.ERROR(f"Data directory not found: {data_dir}"))
            raise SystemExit(1)

        result = validate_all_configs(data_dir)

        if result.is_valid:
            self.stdout.write(self.style.SUCCESS("All YAML configs passed validation."))
            return

        self.stderr.write(self.style.ERROR(f"Found {len(result.errors)} validation error(s):"))
        for error in result.errors:
            self.stderr.write(f"  {error}")

        raise SystemExit(1)
