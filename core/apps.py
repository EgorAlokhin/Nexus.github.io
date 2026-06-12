from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        import sys

        if any(cmd in sys.argv for cmd in ("migrate", "makemigrations", "test", "shell")):
            return
        from core.services import scheduler  # noqa: F401

        scheduler.start_scheduler()
