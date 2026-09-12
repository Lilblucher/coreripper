from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        import accounts.models  # noqa: F401  registers the post_save signal
        self._warm_google_certs()

    @staticmethod
    def _warm_google_certs():
        try:
            import requests
            r = requests.get("https://www.googleapis.com/oauth2/v1/certs", timeout=5)
            print(f"[AccountsConfig] Google certs warmed: {r.status_code}")
        except Exception as e:
            print(f"[AccountsConfig] Google cert warm failed: {e}")