"""Premium AI tool endpoints (feedback tutor, quiz generator, coding helper).

csrf_exempt on the three views below  same rationale as dashboard/views.py:
auth here is the cross-origin bearer token, not a session cookie, so Django's
CSRF check has nothing valid to compare against and would 403 every real
browser call.
"""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import UsageLog

from .decorators import login_required_json
from .llm import LLMNotConfigured, LLMRequestFailed, get_completion
from .quota import check_global_budget, check_user_quota

FEEDBACK_TUTOR_SYSTEM = (
    "You are a Socratic writing tutor. The student will give you feedback they received "
    "on their work, and optionally the work itself. Never rewrite their work or write the "
    "revision for them. Instead ask guiding questions and point out *what kind* of change "
    "the feedback is asking for, so the student does the revising themselves."
)

QUIZ_GENERATOR_SYSTEM = (
    "You turn study notes into a study aid. Given the student's notes, produce 5 multiple-"
    "choice questions (each with 4 options and the correct answer marked) followed by 5 "
    "flashcards (front/back pairs) covering the same material. Plain text, clearly labeled "
    "sections, no preamble."
)

CODING_HELPER_SYSTEM_EXPLAIN = (
    "You explain code to a student. Given a code snippet, explain what it does step by "
    "step in plain language. Never rewrite or 'fix' the code  only explain it."
)

CODING_HELPER_SYSTEM_DEBUG = (
    "You help a student find bugs in their code. Given a code snippet, point out what's "
    "wrong and why, and describe how to fix it in words. Only include corrected code if "
    "the fix is a single small line  otherwise describe the fix, don't rewrite the file."
)


def _parse_json_body(request):
    try:
        return json.loads(request.body or b"{}"), None
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse({"error": "invalid_json"}, status=400)


def _quota_check(request):
    """Returns a JsonResponse to short-circuit with, or None if the call is allowed."""
    allowed, used, cap = check_global_budget()
    if not allowed:
        return JsonResponse(
            {"error": "global_budget_exceeded", "message": "Premium tools are resting  back tomorrow."},
            status=429,
        )
    allowed, used, cap = check_user_quota(request.user)
    if not allowed:
        return JsonResponse(
            {
                "error": "user_quota_exceeded",
                "message": "You've hit this month's fair-use limit for premium tools.",
                "used": str(used),
                "cap": str(cap),
            },
            status=429,
        )
    return None


def _run_completion(request, tool, system, user_msg, model=None):
    """Shared tail: model routing (credits.run_ai) → UsageLog write (free models
    only, for the $-spend quota) → JSON response, or an honest error JSON.

    max_tokens is owned by settings.MAX_OUTPUT_TOKENS (keyed on `tool`) now, so
    callers no longer pass it. Quota ($-spend) governs the free models only;
    Claude's only gate is the credit wallet, so quota is skipped for Claude 
    the free/paid decision is made here via resolve_model."""
    from credits.models import ClaudeUnavailable, InsufficientCredits
    from credits.services import CLAUDE_DISABLED_MESSAGE, resolve_model, run_ai

    provider = resolve_model(request.user, model)
    if provider in ("groq", "gemini"):
        quota_error = _quota_check(request)
        if quota_error:
            return quota_error

    try:
        result = run_ai(user=request.user, operation=tool, system=system, user_msg=user_msg, model=model)
    except ClaudeUnavailable:
        # Site-wide switch, not a wallet problem  so no upgrade/purchase CTA.
        return JsonResponse(
            {
                "error": "claude_disabled",
                "feature": "claude_ai",
                "message": CLAUDE_DISABLED_MESSAGE,
            },
            status=503,
        )
    except InsufficientCredits:
        return JsonResponse(
            {
                "error": "insufficient_credits",
                "message": "You're out of Sonnet-5 credits.",
                "credits_remaining": 0,
                "purchase_url": "/billing.html",
            },
            status=402,
        )
    except LLMNotConfigured:
        return JsonResponse(
            {"error": "llm_not_configured", "message": "The AI engine isn't connected yet."},
            status=503,
        )
    except LLMRequestFailed:
        return JsonResponse(
            {"error": "llm_request_failed", "message": "The AI engine is temporarily unavailable."},
            status=502,
        )

    # Keep the $-spend UsageLog for free-model runs only (Claude is metered by
    # the credit ledger instead).
    if result["provider"] in ("groq", "gemini"):
        UsageLog.objects.create(
            user=request.user,
            tool=tool,
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            est_cost_usd=result["est_cost_usd"],
            cache_hit=result["cache_hit"],
        )
    return JsonResponse(
        {
            "content": result["content"],
            "model": result["provider"],
            "cache_hit": result["cache_hit"],
            "credits_used": result["credits_used"],
            "credits_remaining": result["credits_remaining"],
        }
    )


@csrf_exempt
@require_POST
@login_required_json
def feedback_tutor_view(request):
    body, error = _parse_json_body(request)
    if error:
        return error

    feedback = (body.get("feedback") or "").strip()
    work = (body.get("work") or "").strip()
    if not feedback:
        return JsonResponse({"error": "missing_field", "message": "'feedback' is required."}, status=400)

    user_msg = f"Feedback I received:\n{feedback}"
    if work:
        user_msg += f"\n\nMy original work:\n{work}"

    return _run_completion(request, "feedback_tutor", FEEDBACK_TUTOR_SYSTEM, user_msg, model=body.get("model"))


@csrf_exempt
@require_POST
@login_required_json
def quiz_generator_view(request):
    body, error = _parse_json_body(request)
    if error:
        return error

    notes = (body.get("notes") or "").strip()
    if not notes:
        return JsonResponse({"error": "missing_field", "message": "'notes' is required."}, status=400)

    return _run_completion(request, "quiz_generator", QUIZ_GENERATOR_SYSTEM, notes, model=body.get("model"))


@csrf_exempt
@require_POST
@login_required_json
def coding_helper_view(request):
    body, error = _parse_json_body(request)
    if error:
        return error

    code = (body.get("code") or "").strip()
    mode = body.get("mode") or "explain"
    language = (body.get("language") or "").strip()
    if not code:
        return JsonResponse({"error": "missing_field", "message": "'code' is required."}, status=400)
    if mode not in ("explain", "debug"):
        return JsonResponse({"error": "invalid_mode", "message": "'mode' must be 'explain' or 'debug'."}, status=400)

    system = CODING_HELPER_SYSTEM_EXPLAIN if mode == "explain" else CODING_HELPER_SYSTEM_DEBUG
    user_msg = f"Language: {language or 'unspecified'}\n\nCode:\n{code}"

    return _run_completion(request, "coding_helper", system, user_msg, model=body.get("model"))
