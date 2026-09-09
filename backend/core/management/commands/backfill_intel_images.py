"""Backfill intelligent images onto existing published articles.

One-time (or occasional) pass that runs the Intelligent image pipeline over
already-published news / hardware / blog rows that don't yet have a resolved
image. Safe to re-run: rows that already have an intel image and an unchanged
source hash are skipped unless --force.

    manage.py backfill_intel_images [--type news|hardware|blog|all]
                                    [--limit N] [--force] [--include-pending]

Idempotent, best-effort, honesty-first: a Gemini/search miss leaves the row on
its per-category fallback  nothing is fabricated.
"""
from django.core.management.base import BaseCommand

from core.intel.generate import refresh_article_image


class Command(BaseCommand):
    help = "Resolve accurate images for existing articles via the Intelligent pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--type", default="all", choices=["news", "hardware", "blog", "all"])
        parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
        parser.add_argument("--force", action="store_true", help="Re-resolve even if an image already exists")
        parser.add_argument("--include-pending", action="store_true", help="Also process not-yet-published rows")

    def handle(self, *args, **opts):
        targets = self._collect(opts["type"], opts["include_pending"])
        limit = opts["limit"]
        force = opts["force"]

        total_hits = 0
        for label, title_fn, body_fn, category_fn, queryset in targets:
            processed = hits = 0
            for obj in queryset.iterator():
                changed = refresh_article_image(
                    obj, title_fn(obj), body_fn(obj), category_fn(obj), force=force
                )
                processed += 1
                if changed:
                    hits += 1
                    total_hits += 1
                if limit and processed >= limit:
                    break
            self.stdout.write(f"{label}: processed {processed}, resolved {hits} image(s)")
        self.stdout.write(self.style.SUCCESS(f"Done  {total_hits} image(s) resolved."))

    def _collect(self, which, include_pending):
        out = []
        if which in ("news", "all"):
            from news.models import NewsDraft

            qs = NewsDraft.objects.all() if include_pending else NewsDraft.objects.filter(status="published")
            out.append((
                "news", lambda o: o.title, lambda o: o.ai_summary or o.ai_draft_body,
                lambda o: o.category, qs.order_by("id"),
            ))
        if which in ("hardware", "all"):
            from hardware.models import HardwareArticle

            qs = HardwareArticle.objects.all() if include_pending else HardwareArticle.objects.filter(status="published")
            out.append((
                "hardware", lambda o: o.title, lambda o: o.ai_summary or o.ai_draft_body,
                lambda o: o.category, qs.order_by("id"),
            ))
        if which in ("blog", "all"):
            from blog.models import Post

            qs = Post.objects.all() if include_pending else Post.objects.filter(is_published=True)
            out.append((
                "blog", lambda o: o.title, lambda o: o.excerpt or o.content[:800],
                lambda o: o.category.slug, qs.order_by("id"),
            ))
        return out
