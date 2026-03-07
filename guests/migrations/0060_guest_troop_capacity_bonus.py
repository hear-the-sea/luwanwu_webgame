from django.db import migrations, models


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_set_bonus_definition(raw_bonus):
    bonus_def = raw_bonus or {}
    if not isinstance(bonus_def, dict):
        if isinstance(bonus_def, (list, tuple)):
            bonus_def = {"bonus": bonus_def}
        else:
            return None, {}

    pieces = bonus_def.get("pieces")
    bonuses = bonus_def.get("bonus") or bonus_def.get("bonuses") or bonus_def
    if not isinstance(bonuses, dict):
        return pieces, {}
    return pieces, bonuses


def _compute_set_bonus(gear_items):
    sets = {}
    for gear in gear_items:
        template = getattr(gear, "template", None)
        if not template:
            continue
        set_key = getattr(template, "set_key", "") or ""
        if not set_key:
            continue
        pieces, bonuses = _normalize_set_bonus_definition(getattr(template, "set_bonus", None))
        if not bonuses:
            continue

        info = sets.setdefault(set_key, {"count": 0, "pieces": pieces, "bonus": bonuses})
        info["count"] = _safe_int(info.get("count")) + 1
        if info.get("pieces") is None and pieces is not None:
            info["pieces"] = pieces
        if info.get("bonus") is None:
            info["bonus"] = bonuses

    active_bonus = {}
    for info in sets.values():
        required = _safe_int(info.get("pieces") or info.get("count") or 0)
        if _safe_int(info.get("count")) < required:
            continue
        bonus_map = info.get("bonus") or {}
        if not isinstance(bonus_map, dict):
            continue
        for stat, value in bonus_map.items():
            active_bonus[stat] = active_bonus.get(stat, 0) + _safe_int(value)
    return active_bonus


def backfill_troop_capacity_bonus(apps, schema_editor):
    Guest = apps.get_model("guests", "Guest")
    GearItem = apps.get_model("guests", "GearItem")

    for guest in Guest.objects.iterator():
        gear_items = list(GearItem.objects.filter(guest_id=guest.id).select_related("template"))
        gear_bonus = 0
        for gear in gear_items:
            template = getattr(gear, "template", None)
            if not template:
                continue
            extra_stats = getattr(template, "extra_stats", None) or {}
            gear_bonus += _safe_int(extra_stats.get("troop_capacity"))

        current_set_bonus = _compute_set_bonus(gear_items)
        guest.troop_capacity_bonus = gear_bonus + _safe_int(current_set_bonus.get("troop_capacity"))
        guest.gear_set_bonus = current_set_bonus
        guest.save(update_fields=["troop_capacity_bonus", "gear_set_bonus"])


class Migration(migrations.Migration):
    dependencies = [
        ("guests", "0059_alter_recruitmentpool_tier"),
    ]

    operations = [
        migrations.AddField(
            model_name="guest",
            name="troop_capacity_bonus",
            field=models.IntegerField(default=0),
        ),
        migrations.RunPython(backfill_troop_capacity_bonus, migrations.RunPython.noop),
    ]
