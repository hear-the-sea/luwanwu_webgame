from django.db import migrations


def seed_templates(apps, schema_editor):
    GuestTemplate = apps.get_model("guests", "GuestTemplate")
    GearTemplate = apps.get_model("guests", "GearTemplate")
    RecruitmentPool = apps.get_model("guests", "RecruitmentPool")
    RecruitmentPoolEntry = apps.get_model("guests", "RecruitmentPoolEntry")

    guests = [
        {
            "key": "sun_bin",
            "name": "孙膑",
            "archetype": "civil",
            "rarity": "purple",
            "base_attack": 130,
            "base_defense": 90,
            "base_support": 160,
            "flavor": "奇策百出，擅长谋略。",
            "skill_summary": "出征时提升友军攻防。",
        },
        {
            "key": "wu_qi",
            "name": "吴起",
            "archetype": "military",
            "rarity": "orange",
            "base_attack": 180,
            "base_defense": 140,
            "base_support": 80,
            "flavor": "百战名将，攻守兼备。",
            "skill_summary": "首回合提高暴击。",
        },
        {
            "key": "li_qing",
            "name": "李清",
            "archetype": "civil",
            "rarity": "blue",
            "base_attack": 90,
            "base_defense": 110,
            "base_support": 120,
            "flavor": "后勤达人，擅长补给。",
            "skill_summary": "提高粮草获取。",
        },
    ]
    templates = {}
    for data in guests:
        template, _ = GuestTemplate.objects.update_or_create(key=data["key"], defaults=data)
        templates[data["key"]] = template

    gears = [
        {
            "key": "jade_fan",
            "name": "青玉扇",
            "slot": "accessory",
            "attack_bonus": 10,
            "support_bonus": 30,
        },
        {
            "key": "tiger_blade",
            "name": "虎纹刀",
            "slot": "weapon",
            "attack_bonus": 40,
            "defense_bonus": 10,
        },
    ]
    for data in gears:
        GearTemplate.objects.update_or_create(key=data["key"], defaults=data)

    pools = [
        {
            "key": "standard",
            "name": "常规招募",
            "description": "基础门客常驻卡池",
            "cost": {"grain": 200, "wood": 100},
            "entries": [("sun_bin", 15), ("li_qing", 50)],
        },
        {
            "key": "elite",
            "name": "精英招募",
            "description": "高稀有门客概率提升",
            "cost": {"grain": 400, "iron": 200},
            "entries": [("wu_qi", 20), ("sun_bin", 30)],
        },
    ]
    for pool_data in pools:
        entries = pool_data.pop("entries")
        pool, _ = RecruitmentPool.objects.update_or_create(key=pool_data["key"], defaults=pool_data)
        for key, weight in entries:
            RecruitmentPoolEntry.objects.update_or_create(pool=pool, template=templates[key], defaults={"weight": weight})


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_templates, migrations.RunPython.noop),
    ]
