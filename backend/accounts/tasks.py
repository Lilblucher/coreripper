"""Two Celery beat emails, each gated by its own NotificationPreference flag:

- send_weekly_digests (weekly_digest): account-activity summary  AI tool
  usage + monitor status. Summarizes only things this project actually
  tracks per-user. Deliberately does NOT claim a "tool runs" count for
  network/dev tools  those aren't logged per-call anywhere in this
  codebase, so making up a number for them would be exactly the kind of
  fake data this project avoids elsewhere.
- send_newsletter (product_updates): content roundup  latest published
  blog articles + approved news items. Members-only by construction: the
  flag only exists on a User's NotificationPreference, and the frontend only
  ever offers the toggle to a logged-in account (see blog.html/news.html) 
  there's no anonymous email-capture path into this list.
"""
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.utils import timezone

from .models import NotificationPreference, UsageLog


@shared_task
def send_weekly_digests():
    """Runs weekly (registered via a data migration, same pattern as
    monitors.tasks.dispatch_due_monitors). One email per opted-in user;
    a failure sending to one user must not stop the rest."""
    week_ago = timezone.now() - timedelta(days=7)
    user_ids = NotificationPreference.objects.filter(weekly_digest=True).values_list("user_id", flat=True)

    for user in User.objects.filter(id__in=user_ids):
        try:
            _send_digest_for_user(user, week_ago)
        except Exception as exc:
            print(f"[send_weekly_digests] failed for {user.email}: {exc}")


def _send_digest_for_user(user, since):
    from monitors.models import AlertLog, Monitor  # local import  same app-load-order reasoning as elsewhere

    ai_calls = UsageLog.objects.filter(user=user, created_at__gte=since).count()
    monitors = Monitor.objects.filter(user=user)
    alerts = AlertLog.objects.filter(monitor__user=user, triggered_at__gte=since).order_by("-triggered_at")

    if ai_calls == 0 and not monitors.exists():
        return  # nothing real to report  don't send an empty digest

    lines = [
        f"Hello{' ' + user.first_name if user.first_name else ''},",
        "",
        "Here's a summary of the last seven days on your CoreRipper account.",
        "",
        f"AI tool runs        {ai_calls}",
    ]

    if monitors.exists():
        healthy = monitors.filter(status="ok").count()
        lines += ["", f"Monitors ({healthy} of {monitors.count()} healthy)"]
        for m in monitors:
            lines.append(f"  {m.get_status_display():<8} {m.get_tool_key_display()} on {m.target}")

    if alerts.exists():
        lines += ["", f"Alerts raised this week ({alerts.count()})"]
        for a in alerts[:10]:
            lines.append(f"  {a.triggered_at.strftime('%a %d %b, %H:%M')}  {a.change_summary}")
        if alerts.count() > 10:
            lines.append(f"  ...and {alerts.count() - 10} more, listed in your Workbench.")
    elif monitors.exists():
        lines += ["", "No alerts were raised this week - everything stayed within range."]

    lines += [
        "",
        "Full history and settings are on your account:  www.coreripper.site",
        "",
        "You can turn this digest off any time from the Notifications tab in "
        "your account settings.",
        "",
        "CoreRipper Monitoring",
    ]

    send_mail(
        subject="Your CoreRipper weekly summary",
        message="\n".join(lines),
        from_email=settings.EMAIL_FROM_ALERTS,
        recipient_list=[user.email],
        fail_silently=False,
    )


@shared_task
def send_newsletter():
    """Runs weekly (registered via a data migration, same pattern as
    send_weekly_digests / monitors.tasks.dispatch_due_monitors), on a
    different day/time so it never lands in the same email as the account
    digest. One email per opted-in member; a failure sending to one user
    must not stop the rest."""
    week_ago = timezone.now() - timedelta(days=7)
    content = _gather_newsletter_content(week_ago)
    if not content["posts"] and not content["news"]:
        return  # nothing new to report  don't send an empty newsletter

    user_ids = NotificationPreference.objects.filter(product_updates=True).values_list("user_id", flat=True)
    for user in User.objects.filter(id__in=user_ids):
        try:
            _send_newsletter_for_user(user, content)
        except Exception as exc:
            print(f"[send_newsletter] failed for {user.email}: {exc}")


def _gather_newsletter_content(since):
    from blog.models import Post
    from news.models import NewsDraft

    posts = Post.objects.filter(is_published=True, published_at__gte=since).order_by("-published_at")[:10]
    news = NewsDraft.objects.filter(status="published", reviewed_at__gte=since).order_by("-reviewed_at")[:10]
    return {"posts": list(posts), "news": list(news)}


def _send_newsletter_for_user(user, content):
    lines = [
        f"Hello{' ' + user.first_name if user.first_name else ''},",
        "",
        "Here's what we published this week.",
        "",
    ]

    if content["posts"]:
        lines.append(f"FROM THE BLOG ({len(content['posts'])})")
        for p in content["posts"]:
            lines.append(f"  {p.title}")
            lines.append("")

    if content["news"]:
        lines.append(f"TECH NEWS ({len(content['news'])})")
        for n in content["news"]:
            lines.append(f"  [{n.get_category_display()}] {n.title}")
            lines.append(f"  {n.ai_summary}")
            lines.append("")

    lines += [
        "Read all of this and more at:  www.coreripper.site",
        "",
        "Thanks for reading.",
        "",
        "CoreRipper",
        "",
        "You're receiving this because product updates are switched on for your "
        "account. Turn them off any time in the Notifications tab of your settings.",
    ]

    send_mail(
        subject="Your CoreRipper weekly roundup",
        message="\n".join(lines),
        from_email=settings.EMAIL_FROM_ALERTS,
        recipient_list=[user.email],
        fail_silently=False,
    )
