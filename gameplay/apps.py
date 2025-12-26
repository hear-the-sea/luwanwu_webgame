from django.apps import AppConfig


class GameplayConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gameplay"
    verbose_name = "庄园与战斗玩法"

    def ready(self):
        from . import signals  # noqa
