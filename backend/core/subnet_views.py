"""Subnet & CIDR drill streak  persistence for the practice trainer.

A calendar-day practice streak (not session-based), available to every
logged-in user (Free included)  it's a retention hook, not a paywall
feature. The frontend does all the drill math client-side; this only
records that a session was completed and maintains the streak counters.
"""
import json
from datetime import date, timedelta

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import login_required_json

from .models import SubnetDrillStreak


def _streak_json(streak):
    return {
        "current_streak_days": streak.current_streak_days,
        "longest_streak_days": streak.longest_streak_days,
        "last_practiced_date": streak.last_practiced_date.isoformat() if streak.last_practiced_date else None,
        "total_problems_solved": streak.total_problems_solved,
    }


@require_GET
@login_required_json
def subnet_streak_view(request):
    """Current streak for the logged-in user (creates a zeroed row on first read)."""
    streak, _ = SubnetDrillStreak.objects.get_or_create(user=request.user)
    return JsonResponse(_streak_json(streak))


@csrf_exempt
@require_POST
@login_required_json
def subnet_streak_log_view(request):
    """Record a completed drill session. Body: {"solved": <int>}.

    Streak rules (calendar-day, idempotent within a day):
      - already practiced today  -> streak unchanged, just add to solved count
      - practiced yesterday       -> streak + 1
      - anything else / never     -> streak resets to 1
    """
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    solved = body.get("solved", 0)
    try:
        solved = max(0, int(solved))
    except (TypeError, ValueError):
        solved = 0

    streak, _ = SubnetDrillStreak.objects.get_or_create(user=request.user)
    today = date.today()

    if streak.last_practiced_date == today:
        pass  # already counted today's streak; only the solved tally grows
    elif streak.last_practiced_date == today - timedelta(days=1):
        streak.current_streak_days += 1
    else:
        streak.current_streak_days = 1

    streak.last_practiced_date = today
    streak.longest_streak_days = max(streak.longest_streak_days, streak.current_streak_days)
    streak.total_problems_solved += solved
    streak.save()

    return JsonResponse(_streak_json(streak))
