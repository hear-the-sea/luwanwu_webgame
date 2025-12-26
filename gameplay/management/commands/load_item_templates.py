from __future__ import annotations

import json
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from gameplay.models import ItemTemplate
from core.utils.image_utils import compress_and_resize_image


class Command(BaseCommand):
    help = "Load ItemTemplate definitions from a YAML/JSON file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "item_templates.yaml"),
            help="Path to YAML/JSON file containing item templates.",
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

        items = payload.get("items") if isinstance(payload, dict) else None
        if not items:
            self.stdout.write(self.style.WARNING("No items found; nothing to import."))
            return

        # 图片源目录
        image_source_dir = Path(settings.BASE_DIR) / "data" / "images" / "items"

        for entry in items:
            key = entry.get("key")
            name = entry.get("name")
            if not key or not name:
                self.stdout.write(self.style.WARNING(f"Skip entry {entry}: missing key or name."))
                continue
            defaults = {
                "name": name,
                "description": entry.get("description", ""),
                "effect_type": entry.get("effect_type", ItemTemplate.EffectType.RESOURCE_PACK),
                "effect_payload": entry.get("effect_payload") or {},
                "icon": entry.get("icon", ""),
                "rarity": entry.get("rarity", "gray"),
                "tradeable": entry.get("tradeable", False),
                "price": entry.get("price", 0),
                "storage_space": entry.get("storage_space", 1),
                "is_usable": entry.get("is_usable", False),
            }
            obj, created = ItemTemplate.objects.update_or_create(key=key, defaults=defaults)

            # 处理图片字段（压缩并保存）
            image_filename = entry.get("image")
            if image_filename:
                image_path = image_source_dir / image_filename
                if image_path.exists():
                    try:
                        # 压缩图片：物品图标最大 200x200，质量 85%，转换为 WebP
                        compressed_file, new_filename = compress_and_resize_image(
                            image_path,
                            max_size=(200, 200),
                            quality=85,
                            convert_to_webp=True
                        )
                        # 删除旧文件（如果存在）避免重复
                        if obj.image:
                            obj.image.delete(save=False)
                        obj.image.save(new_filename, compressed_file, save=True)
                        self.stdout.write(self.style.SUCCESS(f"  [OK] Compressed and loaded image: {image_filename} -> {new_filename}"))
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"  [FAIL] Failed to load image {image_filename}: {e}"))
                else:
                    self.stdout.write(self.style.WARNING(f"  [NOT FOUND] Image not found: {image_path}"))

            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} item template {obj.key}")
