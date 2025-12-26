from __future__ import annotations

import json
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from gameplay.models import MissionTemplate


class Command(BaseCommand):
    help = "Load mission templates (掉落/敌人/耗时) from a YAML/JSON config file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "mission_templates.yaml"),
            help="Path to YAML/JSON file containing mission definitions.",
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

        missions = payload.get("missions") if isinstance(payload, dict) else None
        if not missions:
            self.stdout.write(self.style.WARNING("No missions found in file; nothing to import."))
            return

        for entry in missions:
            key = entry.get("key")
            name = entry.get("name")
            if not key or not name:
                self.stdout.write(self.style.WARNING(f"Skip entry {entry}: missing key or name"))
                continue
            defaults = {
                "name": name,
                "description": entry.get("description", ""),
                "battle_type": entry.get("battle_type", "task"),
                "is_defense": bool(entry.get("is_defense", False)),
                "enemy_guests": entry.get("enemy_guests") or [],
                "enemy_troops": entry.get("enemy_troops") or {},
                "enemy_technology": entry.get("enemy_technology") or {},
                "drop_table": entry.get("drop_table") or {},
                "base_travel_time": int(entry.get("base_travel_time", 1200) or 1200),
                "daily_limit": int(entry.get("daily_limit", 3) or 3),
            }
            obj, created = MissionTemplate.objects.update_or_create(key=key, defaults=defaults)
            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} mission {obj.key}")
