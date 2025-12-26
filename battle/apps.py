from django.apps import AppConfig


class BattleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "battle"
    verbose_name = "战斗系统"

    def ready(self):
        import battle.signals  # noqa: F401
