from __future__ import annotations

import json
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from gameplay.models import BuildingType
from gameplay.services.template_cache import clear_building_template_cache


class Command(BaseCommand):
    help = "Load BuildingType definitions from a YAML/JSON file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "building_templates.yaml"),
            help="Path to YAML/JSON file containing building templates.",
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

        buildings = payload.get("buildings") if isinstance(payload, dict) else None
        if not buildings:
            self.stdout.write(self.style.WARNING("No buildings found; nothing to import."))
            return

        updated = 0
        created = 0
        skipped = 0
        for entry in buildings:
            key = entry.get("key")
            name = entry.get("name")
            resource_type = entry.get("resource_type")
            if not key or not name or not resource_type:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"Skip entry {entry}: missing key/name/resource_type."))
                continue
            defaults = {
                "name": name,
                "description": entry.get("description", ""),
                "category": entry.get("category", BuildingType._meta.get_field("category").default),
                "resource_type": resource_type,
                "base_rate_per_hour": int(entry.get("base_rate_per_hour", 0)),
                "rate_growth": float(entry.get("rate_growth", 0.0)),
                "base_upgrade_time": int(entry.get("base_upgrade_time", 60)),
                "time_growth": float(entry.get("time_growth", 1.25)),
                "base_cost": entry.get("base_cost") or {},
                "cost_growth": float(entry.get("cost_growth", 1.35)),
                "icon": entry.get("icon", ""),
            }
            obj, was_created = BuildingType.objects.update_or_create(key=key, defaults=defaults)
            if was_created:
                created += 1
            else:
                updated += 1
            self.stdout.write(f"{'Created' if was_created else 'Updated'} building type {obj.key}")

        clear_building_template_cache()
        self.stdout.write(
            self.style.SUCCESS(
                f"Building templates synced. created={created} updated={updated} skipped={skipped}"
            )
        )
