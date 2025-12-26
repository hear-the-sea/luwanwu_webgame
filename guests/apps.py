from django.apps import AppConfig


class GuestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "guests"
    verbose_name = "门客系统"

    def ready(self):
        from . import signals  # noqa
