from __future__ import annotations

from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from battle.models import TroopTemplate
from core.utils.image_utils import compress_and_resize_image
from gameplay.services.utils.template_cache import clear_troop_template_caches


def _build_troop_defaults(data: dict) -> dict:
    return {
        "name": data["name"],
        "description": data.get("description", ""),
        "base_attack": data.get("base_attack", 30),
        "base_defense": data.get("base_defense", 20),
        "base_hp": data.get("base_hp", 80),
        "speed_bonus": data.get("speed_bonus", 10),
        "priority": int(data.get("priority", 0)),
        "default_count": int(data.get("default_count", 120)),
    }


def _log_info(command: BaseCommand, verbosity: int, message: str) -> None:
    if verbosity >= 1:
        command.stdout.write(message)


def _load_avatar_for_troop(
    command: BaseCommand, obj: TroopTemplate, data: dict, image_source_dir: Path, verbosity: int
) -> None:
    avatar_filename = data.get("avatar")
    if not avatar_filename:
        return

    avatar_path = image_source_dir / avatar_filename
    if not avatar_path.exists():
        _log_info(command, verbosity, command.style.WARNING(f"  [NOT FOUND] Avatar not found: {avatar_path}"))
        return

    try:
        compressed_file, new_filename = compress_and_resize_image(
            avatar_path,
            max_size=(300, 300),
            quality=85,
            convert_to_webp=True,
        )
        if obj.avatar:
            obj.avatar.delete(save=False)
        obj.avatar.save(new_filename, compressed_file, save=True)
        _log_info(
            command,
            verbosity,
            command.style.SUCCESS(f"  [OK] Compressed and loaded avatar: {avatar_filename} -> {new_filename}"),
        )
    except Exception as exc:
        _log_info(command, verbosity, command.style.WARNING(f"  [FAIL] Failed to load avatar {avatar_filename}: {exc}"))


class Command(BaseCommand):
    help = "Load troop templates from a YAML file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "troop_templates.yaml"),
            help="Path to YAML file containing troop templates.",
        )
        parser.add_argument(
            "--skip-images",
            action="store_true",
            help="Skip avatar compression/storage. Useful for CI/tests.",
        )

    def _load_payload(self, file_path: Path) -> dict:
        if not file_path.exists():
            raise CommandError(f"File {file_path} does not exist.")

        with file_path.open("r", encoding="utf-8") as f:
            payload = yaml.safe_load(f)

        if not payload:
            self.stdout.write(self.style.WARNING("Empty payload, nothing to import."))
            return {}
        return payload

    def _upsert_troop(self, data: dict) -> tuple[TroopTemplate, bool]:
        defaults = _build_troop_defaults(data)
        return TroopTemplate.objects.update_or_create(key=data["key"], defaults=defaults)

    def handle(self, *args, **options):
        verbosity = int(options.get("verbosity", 1) or 1)
        skip_images = bool(options.get("skip_images"))

        file_path = Path(options["file"])
        payload = self._load_payload(file_path)
        if not payload:
            return

        troop_data = payload.get("troops") or []
        image_source_dir = Path(settings.BASE_DIR) / "data" / "images" / "troops"

        for data in troop_data:
            obj, created = self._upsert_troop(data)
            if not skip_images:
                _load_avatar_for_troop(self, obj, data, image_source_dir, verbosity)

            action = "Created" if created else "Updated"
            _log_info(self, verbosity, f"{action} troop template {obj.key}")

        clear_troop_template_caches()
        _log_info(self, verbosity, self.style.SUCCESS("Troop templates synced."))
