from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.utils.yaml_schema import get_supported_yaml_configs, validate_all_configs


class Command(BaseCommand):
    help = "Validate the YAML game configuration files currently covered by schema checks."

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
        parser.add_argument(
            "--strict-coverage",
            action="store_true",
            help="Fail when the data directory contains YAML files without schema coverage.",
        )

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"])
        dry_run = options["dry_run"]
        strict_coverage = options["strict_coverage"]

        if dry_run:
            self.stdout.write("Dry-run mode: validating configs without side effects.")

        if not data_dir.exists():
            self.stderr.write(self.style.ERROR(f"Data directory not found: {data_dir}"))
            raise SystemExit(1)

        supported_files = set(get_supported_yaml_configs())
        discovered_yaml_files = {path.name for path in data_dir.glob("*.yaml")}
        unsupported_files = sorted(discovered_yaml_files - supported_files)

        result = validate_all_configs(data_dir)

        if result.is_valid and not (strict_coverage and unsupported_files):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Validated {len(discovered_yaml_files & supported_files)} supported YAML config file(s)."
                )
            )
            if unsupported_files:
                warning = "Skipped YAML files without schema coverage: " + ", ".join(unsupported_files)
                self.stdout.write(self.style.WARNING(warning))
            return

        if result.errors:
            self.stderr.write(self.style.ERROR(f"Found {len(result.errors)} validation error(s):"))
            for error in result.errors:
                self.stderr.write(f"  {error}")
        if strict_coverage and unsupported_files:
            self.stderr.write(
                self.style.ERROR("Found YAML files without schema coverage: " + ", ".join(unsupported_files))
            )

        raise SystemExit(1)
