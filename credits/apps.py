from django.apps import AppConfig


class CreditsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "credits"

    def ready(self):
        # Register the wallet-creation signal (mirrors accounts.models's
        # per-user Subscription/Profile signal). Imported here so app loading
        # order never trips over a top-level model import.
        from . import signals  # noqa: F401
