"""Test-only settings: in-memory SQLite instead of Postgres, because the
`corelom` DB role deliberately has no CREATEDB privilege (so a test run can
never touch the real database server).

Run the suite with:
    /home/clive/anaconda3/bin/python manage.py test payments accounts \
        --settings=core_backend.test_settings
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Tests must never send real email; locmem exposes django.core.mail.outbox.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
