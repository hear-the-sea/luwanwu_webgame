from __future__ import annotations

import json
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from gameplay.services.utils.template_cache import clear_technology_template_cache


class Command(BaseCommand):
    help = "Load technology templates from a YAML/JSON file and clear caches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "technology_templates.yaml"),
            help="Path to YAML/JSON file containing technology templates.",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"])
        if not file_path.exists():
            raise CommandError(f"File {file_path} does not exist.")

        with file_path.open("r", encoding="utf-8") as fh:
            if file_path.suffix.lower() in {".yaml", ".yml"}:
                payload = yaml.safe_load(fh)
            elif file_path.suffix.lower() == ".json":
                payload = json.load(fh)
            else:
                raise CommandError("Unsupported file type. Use .yaml/.yml/.json")

        technologies = payload.get("technologies") if isinstance(payload, dict) else None
        if not technologies:
            self.stdout.write(self.style.WARNING("No technologies found; nothing to load."))
            return

        keys = [tech.get("key") for tech in technologies if isinstance(tech, dict)]
        duplicate_keys = {k for k in keys if k and keys.count(k) > 1}
        if duplicate_keys:
            self.stdout.write(self.style.WARNING(f"Duplicate technology keys found: {sorted(duplicate_keys)}"))

        clear_technology_template_cache()
        self.stdout.write(self.style.SUCCESS(f"Technology templates loaded. count={len(technologies)}"))
