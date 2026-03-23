from guests.models import GuestTemplate


def make_pubayi_template(key: str, rarity: str) -> GuestTemplate:
    return GuestTemplate.objects.create(
        key=key,
        name="蒲巴乙",
        archetype="civil",
        rarity=rarity,
        base_attack=80,
        base_intellect=90,
        base_defense=70,
        base_agility=75,
        base_luck=60,
        base_hp=1000,
        default_gender="male",
        default_morality=60,
        recruitable=False,
    )
