from django.db import migrations


def seed_skill_books(apps, schema_editor):
    ItemTemplate = apps.get_model("gameplay", "ItemTemplate")
    InventoryItem = apps.get_model("gameplay", "InventoryItem")
    Manor = apps.get_model("gameplay", "Manor")
    Skill = apps.get_model("guests", "Skill")

    targets = [
        "inspire_attack",
        "jade_shield",
        "stratagem_burst",
    ]
    skills = {skill.key: skill for skill in Skill.objects.filter(key__in=targets)}
    template_map = {}
    for key in targets:
        skill = skills.get(key)
        if not skill:
            continue
        template, _ = ItemTemplate.objects.get_or_create(
            key=f"book_{key}",
            defaults={
                "name": f"{skill.name} 技能书",
                "description": f"学习技能：{skill.name}",
                "effect_type": "skill_book",
                "effect_payload": {"skill_key": skill.key, "skill_name": skill.name},
            },
        )
        template_map[key] = template

    if not template_map:
        return

    for manor in Manor.objects.all():
        for key, template in template_map.items():
            InventoryItem.objects.get_or_create(
                manor=manor,
                template=template,
                defaults={"quantity": 1},
            )


def remove_skill_books(apps, schema_editor):
    ItemTemplate = apps.get_model("gameplay", "ItemTemplate")
    InventoryItem = apps.get_model("gameplay", "InventoryItem")
    InventoryItem.objects.filter(template__key__startswith="book_").delete()
    ItemTemplate.objects.filter(key__startswith="book_").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0010_skills"),
        ("gameplay", "0010_seed_inventory"),
    ]

    operations = [
        migrations.RunPython(seed_skill_books, remove_skill_books),
    ]
