from django.db import migrations


def update_recruitment_data(apps, schema_editor):
    GuestTemplate = apps.get_model("guests", "GuestTemplate")
    RecruitmentPool = apps.get_model("guests", "RecruitmentPool")
    RecruitmentPoolEntry = apps.get_model("guests", "RecruitmentPoolEntry")

    templates = [
        {
            "key": "black_civil_proto",
            "name": "文试学子",
            "archetype": "civil",
            "rarity": "black",
            "base_attack": 80,
            "base_defense": 80,
            "base_support": 90,
            "flavor": "默默无闻的寒门学子。",
        },
        {
            "key": "black_military_proto",
            "name": "武试浪人",
            "archetype": "military",
            "rarity": "black",
            "base_attack": 95,
            "base_defense": 70,
            "base_support": 60,
            "flavor": "赶考途中暂居庄园的游侠。",
        },
        {
            "key": "bai_qi",
            "name": "白起",
            "archetype": "military",
            "rarity": "red",
            "base_attack": 200,
            "base_defense": 150,
            "base_support": 90,
            "flavor": "战神再临，百战百胜。",
            "skill_summary": "斩杀低血量敌人。",
        },
        {
            "key": "mo_zi",
            "name": "墨子",
            "archetype": "civil",
            "rarity": "purple",
            "base_attack": 120,
            "base_defense": 160,
            "base_support": 170,
            "flavor": "兼爱非攻的代表。",
            "skill_summary": "提升全队防御。",
        },
        {
            "key": "hong_fu",
            "name": "红拂",
            "archetype": "military",
            "rarity": "blue",
            "base_attack": 110,
            "base_defense": 100,
            "base_support": 120,
            "flavor": "巾帼不让须眉。",
            "skill_summary": "提升士气。",
        },
    ]

    for data in templates:
        GuestTemplate.objects.update_or_create(key=data["key"], defaults=data)

    pools = [
        {
            "key": "tongshi",
            "name": "童试",
            "tier": "tongshi",
            "description": "单人试招，适合入门。",
            "cost": {"silver": 120},
            "draw_count": 1,
            "entries": [
                ("black_civil_proto", 60),
                ("black_military_proto", 60),
                ("li_qing", 20),
            ],
        },
        {
            "key": "xiangshi",
            "name": "乡试",
            "tier": "xiangshi",
            "description": "可筛选 5 名候选，提升稀有概率。",
            "cost": {"silver": 450},
            "draw_count": 5,
            "entries": [
                ("black_civil_proto", 50),
                ("black_military_proto", 50),
                ("li_qing", 40),
                ("sun_bin", 20),
                ("hong_fu", 15),
            ],
        },
        {
            "key": "huishi",
            "name": "会试",
            "tier": "huishi",
            "description": "一次招募 8 名候选，橙红概率上升。",
            "cost": {"silver": 900},
            "draw_count": 8,
            "entries": [
                ("black_civil_proto", 30),
                ("black_military_proto", 30),
                ("sun_bin", 35),
                ("wu_qi", 25),
                ("hong_fu", 25),
                ("mo_zi", 25),
            ],
        },
        {
            "key": "dianshi",
            "name": "殿试",
            "tier": "dianshi",
            "description": "皇榜特招，提供 10 名候选。",
            "cost": {"silver": 1500},
            "draw_count": 10,
            "entries": [
                ("sun_bin", 40),
                ("mo_zi", 30),
                ("wu_qi", 35),
                ("bai_qi", 25),
                ("hong_fu", 30),
            ],
        },
    ]

    for pool_data in pools:
        entries = pool_data.pop("entries")
        pool, _ = RecruitmentPool.objects.update_or_create(
            key=pool_data["key"],
            defaults={
                "name": pool_data["name"],
                "tier": pool_data["tier"],
                "description": pool_data["description"],
                "cost": pool_data["cost"],
                "draw_count": pool_data["draw_count"],
            },
        )
        RecruitmentPoolEntry.objects.filter(pool=pool).delete()
        for template_key, weight in entries:
            template = GuestTemplate.objects.get(key=template_key)
            RecruitmentPoolEntry.objects.create(pool=pool, template=template, weight=weight)


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0003_recruitment_candidates"),
    ]

    operations = [
        migrations.RunPython(update_recruitment_data, migrations.RunPython.noop),
    ]
