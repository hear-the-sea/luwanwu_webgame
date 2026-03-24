from django.contrib.auth import get_user_model

from gameplay.models import ItemTemplate

User = get_user_model()


def ensure_grain_template() -> ItemTemplate:
    template, _ = ItemTemplate.objects.get_or_create(
        key="grain",
        defaults={"name": "粮食"},
    )
    if not template.name:
        template.name = "粮食"
        template.save(update_fields=["name"])
    return template
