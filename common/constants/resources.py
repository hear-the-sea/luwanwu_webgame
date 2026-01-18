from __future__ import annotations

from django.db import models


class ResourceType(models.TextChoices):
    GRAIN = "grain", "粮食"
    SILVER = "silver", "银两"


# Backwards-friendly alias for callsites that used a plain constants container.
ResourceTypes = ResourceType

