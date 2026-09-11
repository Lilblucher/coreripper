"""Runs one provider-manager sync pass per hardware type. This is the
primary data path (hardware/providers/manager.py, currently backed by the
one live Wikidata provider  see field_priority.py for why GSMArena/
Notebookcheck/PassMark aren't wired in). Scheduled via Celery Beat in
production (see the beat-registration migration); safe to run by hand any
time  idempotent, a no-change re-run creates nothing new.
"""
from django.core.management.base import BaseCommand

from hardware.providers.manager import sync_type

TYPE_KEYS = ["cpu", "gpu", "laptop", "mobile_soc"]


class Command(BaseCommand):
    help = "Sync CPU/GPU/Laptop/MobileSoC rows from every live hardware spec provider."

    def add_arguments(self, parser):
        parser.add_argument(
            "--type", dest="type_key", choices=TYPE_KEYS, default=None,
            help="Sync only this type_key (default: all four).",
        )

    def handle(self, *args, **options):
        type_keys = [options["type_key"]] if options["type_key"] else TYPE_KEYS
        for type_key in type_keys:
            summary = sync_type(type_key)
            self.stdout.write(
                f"{type_key}: seen={summary['devices_seen']} created={summary['created']} "
                f"updated={summary['updated']} unchanged={summary['unchanged']} "
                f"ai_profiles_regenerated={summary['profiles_regenerated']}"
            )
