"""Re-run the category classifier over existing NewsDraft rows.

Categories are assigned once at ingest time, so an improvement to
`news.services.classify_category` only affects articles fetched *after* the
change -- every already-published card keeps whatever the old classifier
decided. This command replays the current classifier over stored rows so the
visible category chips catch up.

Idempotent: running it twice in a row changes nothing the second time.
Dry-run by default; pass --apply to actually write.
"""

from django.core.management.base import BaseCommand

from news.models import NewsDraft
from news.services import classify_category


class Command(BaseCommand):
    help = "Re-classify existing news articles with the current classifier."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the new categories. Without this flag, only reports what would change.",
        )
        parser.add_argument(
            "--status",
            default="",
            help="Only process rows with this status (pending/published/rejected/archived).",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        status = options["status"]

        qs = NewsDraft.objects.all()
        if status:
            qs = qs.filter(status=status)

        changed = []
        for draft in qs:
            # Classify on the same text a reader actually sees on the card,
            # rather than the raw ingest excerpt the original call used.
            new_category, _ = classify_category(draft.title, draft.ai_summary or "")
            if new_category != draft.category:
                changed.append((draft, draft.category, new_category))

        if not changed:
            self.stdout.write(self.style.SUCCESS(f"No changes needed ({qs.count()} rows checked)."))
            return

        for draft, old, new in changed:
            self.stdout.write(f"  [{draft.status}] {old} -> {new}  {draft.title[:60]}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDRY RUN: {len(changed)} of {qs.count()} rows would change. "
                    f"Re-run with --apply to write."
                )
            )
            return

        for draft, _old, new in changed:
            draft.category = new
            draft.save(update_fields=["category"])

        self.stdout.write(
            self.style.SUCCESS(f"\nUpdated {len(changed)} of {qs.count()} rows.")
        )
