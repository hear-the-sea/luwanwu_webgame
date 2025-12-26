from __future__ import annotations

import json
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from guests.models import (
    GuestRarity,
    GuestTemplate,
    RARITY_HP_PROFILES,
    RecruitmentPool,
    RecruitmentPoolEntry,
    Skill,
    SkillBook,
    SkillKind,
)
from core.utils.image_utils import compress_and_resize_image


class Command(BaseCommand):
    help = "Load guest templates and recruitment pools from a YAML/JSON file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "guest_templates.yaml"),
            help="Path to YAML/JSON file containing templates/pools definitions.",
        )
        parser.add_argument(
            "--skills-file",
            type=str,
            default="",
            help="Optional YAML/JSON file containing skills/skill_books definitions.",
        )
        parser.add_argument(
            "--heroes-dir",
            type=str,
            default="",
            help="Optional directory containing hero roster YAML files (e.g., gulong.yaml, huangyi.yaml).",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"])
        if not file_path.exists():
            raise CommandError(f"File {file_path} does not exist.")

        def load_payload(path: Path) -> dict:
            with path.open("r", encoding="utf-8") as f:
                if path.suffix.lower() in {".yaml", ".yml"}:
                    return yaml.safe_load(f) or {}
                if path.suffix.lower() == ".json":
                    return json.load(f) or {}
                raise CommandError("Unsupported file type. Use .yaml/.yml/.json")

        payload = load_payload(file_path)

        if not payload:
            self.stdout.write(self.style.WARNING("Empty payload, nothing to import."))
            return

        skills_file = options.get("skills_file") or ""
        skills_payload = {}
        if skills_file:
            skills_path = Path(skills_file)
            if not skills_path.exists():
                raise CommandError(f"Skills file {skills_path} does not exist.")
            skills_payload = load_payload(skills_path)
        else:
            default_skills_path = Path(settings.BASE_DIR) / "data" / "guest_skills.yaml"
            if default_skills_path.exists():
                skills_payload = load_payload(default_skills_path)

        # Load hero roster from separate directory if specified
        heroes_dir = options.get("heroes_dir") or ""
        heroes_dir_payload: dict[str, list] = {}
        if heroes_dir:
            heroes_path = Path(heroes_dir)
            if not heroes_path.exists() or not heroes_path.is_dir():
                raise CommandError(f"Heroes directory {heroes_path} does not exist.")
            heroes_dir_payload = self._load_heroes_from_dir(heroes_path, load_payload)
        else:
            # Try default directory
            default_heroes_path = Path(settings.BASE_DIR) / "data" / "guests"
            if default_heroes_path.exists() and default_heroes_path.is_dir():
                heroes_dir_payload = self._load_heroes_from_dir(default_heroes_path, load_payload)

        template_data = payload.get("templates") or []
        pool_data = payload.get("pools") or []
        skill_data = (payload.get("skills") or []) + (skills_payload.get("skills") or [])
        book_data = (payload.get("skill_books") or []) + (skills_payload.get("skill_books") or [])
        attribute_profiles = payload.get("attribute_profiles") or {}
        # Merge hero_roster from main file and heroes directory
        hero_roster = payload.get("heroes") or payload.get("hero_roster") or {}
        for rarity, heroes in heroes_dir_payload.items():
            if rarity in hero_roster:
                hero_roster[rarity].extend(heroes)
            else:
                hero_roster[rarity] = heroes
        template_skill_keys: dict[str, list[str]] = {}

        def build_template_from_stats(entry: dict, rarity: str, archetype: str, stats: dict) -> dict:
            stats = stats or {}
            hp_profile = RARITY_HP_PROFILES.get(rarity, {"base": 1200})
            base_hp = stats.get("base_hp", entry.get("base_hp", hp_profile["base"]))
            mapped = {
                "base_attack": stats.get("force", entry.get("base_attack", 100)),
                "base_intellect": stats.get("intellect", entry.get("base_intellect", 100)),
                "base_defense": stats.get("defense", entry.get("base_defense", 100)),
                "base_agility": stats.get("agility", entry.get("base_agility", 80)),
                "base_luck": stats.get("luck", entry.get("base_luck", 50)),
                "base_hp": base_hp,
            }
            built = {
                "key": entry["key"],
                "name": entry["name"],
                "archetype": archetype,
                "rarity": rarity,
                "flavor": entry.get("flavor", ""),
                "default_gender": entry.get("default_gender", "unknown"),
                "default_morality": entry.get("default_morality", 70),
                "recruitable": entry.get("recruitable", True),
                "is_hermit": entry.get("is_hermit", False),
                "skills": entry.get("skills") or [],
                "avatar": entry.get("avatar"),  # 保留头像字段
                "growth_range": entry.get("growth_range") or [],
                "attribute_weights": entry.get("attribute_weights") or {},
            }
            built.update(mapped)
            return built

        for rarity, heroes in hero_roster.items():
            profiles = attribute_profiles.get(rarity, {})
            for hero in heroes:
                archetype = hero["archetype"]
                stats = hero.get("custom_stats") or profiles.get(archetype)
                if not stats:
                    self.stdout.write(
                        self.style.WARNING(f"Skip hero {hero['key']}: missing attribute profile for {rarity}/{archetype}")
                    )
                    continue
                template_data.append(build_template_from_stats(hero, rarity, archetype, stats))

        skill_map = {}
        for data in skill_data:
            defaults = {
                "name": data["name"],
                "rarity": data.get("rarity", GuestRarity.GRAY),
                "description": data.get("description", ""),
                "base_power": data.get("base_power", 100),
                "base_probability": data.get("base_probability", 0.1),
                "targets": data.get("targets", 1),
                "kind": data.get("kind", SkillKind.ACTIVE),
                "status_effect": data.get("status_effect", ""),
                "status_probability": data.get("status_probability", 0.0),
                "status_duration": data.get("status_duration", 1),
                "damage_formula": data.get("damage_formula", {}),
                "required_level": data.get("required_level", 0),
                "required_force": data.get("required_force", 0),
                "required_intellect": data.get("required_intellect", 0),
                "required_defense": data.get("required_defense", 0),
                "required_agility": data.get("required_agility", 0),
            }
            obj, created = Skill.objects.update_or_create(key=data["key"], defaults=defaults)
            skill_map[obj.key] = obj
            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} skill {obj.key}")

        for data in book_data:
            skill_key = data["skill"]
            skill_obj = skill_map.get(skill_key) or Skill.objects.filter(key=skill_key).first()
            if not skill_obj:
                self.stdout.write(self.style.WARNING(f"Skip book {data['key']}: missing skill {skill_key}"))
                continue
            defaults = {
                "name": data["name"],
                "description": data.get("description", ""),
                "skill": skill_obj,
            }
            obj, created = SkillBook.objects.update_or_create(key=data["key"], defaults=defaults)
            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} book {obj.key}")

        # 图片源目录
        image_source_dir = Path(settings.BASE_DIR) / "data" / "images" / "guests"

        template_keys = set()
        for data in template_data:
            hp_profile = RARITY_HP_PROFILES.get(data["rarity"], {"base": 1200})
            base_hp = data.get("base_hp", hp_profile["base"])
            defaults = {
                "name": data["name"],
                "archetype": data["archetype"],
                "rarity": data["rarity"],
                "base_attack": data.get("base_attack", 100),
                "base_intellect": data.get("base_intellect", 100),
                "base_defense": data.get("base_defense", 100),
                "base_agility": data.get("base_agility", 80),
                "base_luck": data.get("base_luck", 50),
                "base_hp": base_hp,
                "flavor": data.get("flavor", ""),
                "default_gender": data.get("default_gender", "unknown"),
                "default_morality": data.get("default_morality", 50),
                "recruitable": data.get("recruitable", True),
                "is_hermit": data.get("is_hermit", False),
                "growth_range": data.get("growth_range") or [],
                "attribute_weights": data.get("attribute_weights") or {},
            }
            obj, created = GuestTemplate.objects.update_or_create(key=data["key"], defaults=defaults)

            # 处理头像字段（压缩并保存）
            avatar_filename = data.get("avatar")
            if avatar_filename:
                avatar_path = image_source_dir / avatar_filename
                if avatar_path.exists():
                    try:
                        # 压缩图片：门客头像最大 400x400，质量 85%，转换为 WebP
                        compressed_file, new_filename = compress_and_resize_image(
                            avatar_path,
                            max_size=(400, 400),
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

            template_keys.add(obj.key)
            template_skill_keys[obj.key] = data.get("skills") or []
            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} template {obj.key}")

        key_to_template = {tpl.key: tpl for tpl in GuestTemplate.objects.filter(key__in=template_keys)}

        if template_skill_keys:
            for template_key, skill_keys in template_skill_keys.items():
                tpl = key_to_template.get(template_key)
                if not tpl:
                    continue
                if not skill_keys:
                    tpl.initial_skills.clear()
                    continue
                skill_objs = []
                for skill_key in skill_keys:
                    skill_obj = skill_map.get(skill_key) or Skill.objects.filter(key=skill_key).first()
                    if not skill_obj:
                        self.stdout.write(
                            self.style.WARNING(f"Skip template skill {skill_key} for {template_key}: skill not found")
                        )
                        continue
                    skill_objs.append(skill_obj)
                tpl.initial_skills.set(skill_objs)

        pool_keys = set()
        for pool in pool_data:
            entries = pool.pop("entries", [])
            defaults = {
                "name": pool["name"],
                "tier": pool.get("tier", RecruitmentPool.Tier.TONGSHI),
                "description": pool.get("description", ""),
                "cost": pool.get("cost", {}),
                "draw_count": pool.get("draw_count", 1),
            }
            pool_obj, _ = RecruitmentPool.objects.update_or_create(key=pool["key"], defaults=defaults)
            pool_keys.add(pool_obj.key)
            RecruitmentPoolEntry.objects.filter(pool=pool_obj).delete()
            for entry in entries:
                template_key = entry.get("template")
                rarity = entry.get("rarity")
                archetype = entry.get("archetype")
                weight = entry.get("weight", 1)
                tpl = None
                if template_key:
                    tpl = key_to_template.get(template_key) or GuestTemplate.objects.filter(key=template_key).first()
                    if not tpl:
                        self.stdout.write(
                            self.style.WARNING(f"Skip pool {pool_obj.key} entry {template_key}: template not found")
                        )
                        continue
                elif not rarity:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skip pool {pool_obj.key} entry with weight {weight}: "
                            "must specify template or rarity."
                        )
                    )
                    continue
                RecruitmentPoolEntry.objects.create(
                    pool=pool_obj,
                    template=tpl,
                    rarity=rarity,
                    archetype=archetype,
                    weight=weight,
                )
            self.stdout.write(f"Configured pool {pool_obj.key} with {len(entries)} entries")

        if pool_keys:
            removed, _ = RecruitmentPool.objects.exclude(key__in=pool_keys).delete()
            if removed:
                self.stdout.write(self.style.WARNING(f"Removed {removed} pools not defined in payload"))

        self.stdout.write(self.style.SUCCESS("Guest templates and pools synced."))

    def _load_heroes_from_dir(self, dir_path: Path, load_payload) -> dict[str, list]:
        """Load and merge hero roster from all YAML/JSON files in a directory.

        Each file should contain a 'heroes' key with rarity-based hero lists.
        Files are loaded in alphabetical order and merged together.
        """
        merged: dict[str, list] = {}
        files = sorted(dir_path.glob("*.yaml")) + sorted(dir_path.glob("*.yml")) + sorted(dir_path.glob("*.json"))
        for file_path in files:
            try:
                payload = load_payload(file_path)
                heroes = payload.get("heroes") or payload.get("hero_roster") or {}
                for rarity, hero_list in heroes.items():
                    if rarity in merged:
                        merged[rarity].extend(hero_list)
                    else:
                        merged[rarity] = list(hero_list)
                self.stdout.write(f"Loaded heroes from {file_path.name}")
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Failed to load {file_path.name}: {e}"))
        return merged
