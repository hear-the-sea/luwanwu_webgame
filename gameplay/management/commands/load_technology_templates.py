from __future__ import annotations

import json
import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.utils.yaml_loader import ensure_mapping, load_yaml_data
from gameplay.services.utils.template_cache import clear_technology_template_cache

logger = logging.getLogger(__name__)


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

        if file_path.suffix.lower() in {".yaml", ".yml"}:
            raw = load_yaml_data(
                file_path,
                logger=logger,
                context="technology templates import file",
                default={},
            )
            payload = ensure_mapping(raw, logger=logger, context="technology templates import root")
        elif file_path.suffix.lower() == ".json":
            with file_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if not isinstance(payload, dict):
                raise CommandError("JSON payload root must be an object.")
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
