from __future__ import annotations

from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from battle.models import TroopTemplate
from core.utils.image_utils import compress_and_resize_image


class Command(BaseCommand):
    help = "Load troop templates from a YAML file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "troop_templates.yaml"),
            help="Path to YAML file containing troop templates.",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"])
        if not file_path.exists():
            raise CommandError(f"File {file_path} does not exist.")

        with file_path.open("r", encoding="utf-8") as f:
            payload = yaml.safe_load(f)

        if not payload:
            self.stdout.write(self.style.WARNING("Empty payload, nothing to import."))
            return

        troop_data = payload.get("troops") or []

        # 图片源目录
        image_source_dir = Path(settings.BASE_DIR) / "data" / "images" / "troops"

        for data in troop_data:
            defaults = {
                "name": data["name"],
                "description": data.get("description", ""),
                "base_attack": data.get("base_attack", 30),
                "base_defense": data.get("base_defense", 20),
                "base_hp": data.get("base_hp", 80),
                "speed_bonus": data.get("speed_bonus", 10),
                "priority": int(data.get("priority", 0)),
                "default_count": int(data.get("default_count", 120)),
            }
            obj, created = TroopTemplate.objects.update_or_create(key=data["key"], defaults=defaults)

            # 处理头像字段（压缩并保存）
            avatar_filename = data.get("avatar")
            if avatar_filename:
                avatar_path = image_source_dir / avatar_filename
                if avatar_path.exists():
                    try:
                        # 压缩图片：兵种头像最大 300x300，质量 85%，转换为 WebP
                        compressed_file, new_filename = compress_and_resize_image(
                            avatar_path,
                            max_size=(300, 300),
                            quality=85,
                            convert_to_webp=True
                        )
                        # 删除旧文件（如果存在）避免重复
                        if obj.avatar:
                            obj.avatar.delete(save=False)
                        obj.avatar.save(new_filename, compressed_file, save=True)
                        self.stdout.write(self.style.SUCCESS(f"  [OK] Compressed and loaded avatar: {avatar_filename} -> {new_filename}"))
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"  [FAIL] Failed to load avatar {avatar_filename}: {e}"))
                else:
                    self.stdout.write(self.style.WARNING(f"  [NOT FOUND] Avatar not found: {avatar_path}"))

            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} troop template {obj.key}")

        self.stdout.write(self.style.SUCCESS("Troop templates synced."))
