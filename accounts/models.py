from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user for future gameplay/运营字段扩展。"""

    email = models.EmailField("email address", unique=True, null=True, blank=True)  # type: ignore[assignment]
    title = models.CharField("头衔", max_length=64, blank=True)

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    def save(self, *args, **kwargs) -> None:
        normalized_email = (self.email or "").strip().lower()
        self.email = normalized_email or None
        super().save(*args, **kwargs)
