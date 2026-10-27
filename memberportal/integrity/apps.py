from django.apps import AppConfig


class IntegrityConfig(AppConfig):
    name = "integrity"
    verbose_name = "Integrity checks"

    def ready(self):
        from .metrics import register_collector

        register_collector()
