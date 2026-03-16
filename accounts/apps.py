from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "账号体系"

    def ready(self) -> None:
        from . import signals  # noqa: F401
