
"""run_ai()  the single AI entry point for every tool.

Model routing: groq and gemini are free (governed by core.quota's $-spend
guardrails, unchanged); claude burns credits from the user's wallet. The free
path delegates to core.llm.get_completion() so the existing Redis cache and
Groq→Gemini fallback are preserved exactly. The claude path meters spend:
estimate → pre-check balance → call → charge actual tokens → ledger +
AIUsageRecord in one transaction → receipt fields on the response.
"""
import math

from decimal import Decimal

from django.conf import settings
from django.db import transaction

from core.llm import (
    LLMNotConfigured,
    LLMRequestFailed,
    claude_complete,
    estimate_cost_usd,
    get_completion,
)

from .models import AIUsageRecord, ClaudeUnavailable, CreditWallet, InsufficientCredits

VALID_MODELS = ("groq", "gemini", "claude")

# Shown verbatim wherever a Sonnet-5 surface is unavailable (API 503 bodies and
# the frontend's disabled states both read from this wording). Kept honest: the
# feature isn't broken and the user's wallet isn't the problem  it isn't live yet.
CLAUDE_DISABLED_MESSAGE = "Sonnet-5 is still being worked on. Livia AI is available in the meantime."


def claude_enabled():
    """Is the paid Sonnet-5 path switched on? Backed by the `claude_ai`
    FeatureFlag, so it's flipped from the Engine Room with no deploy  see
    core.middleware for why this flag isn't a path prefix."""
    from core.middleware import flag_enabled

    return flag_enabled("claude_ai")


def resolve_model(user, requested=None):
    """Which model a call will use. Explicit request wins; else the user's saved
    preference; else groq. A None user (e.g. news_draft) can never route to
    Claude  free models only."""
    model = requested
    if model not in VALID_MODELS:
        model = None
    if model is None and user is not None:
        profile = getattr(user, "profile", None)
        model = getattr(profile, "preferred_model", None) if profile else None
        if model not in VALID_MODELS:
            model = "groq"
    if model is None:
        model = "groq"
    if user is None and model == "claude":
        model = "groq"
    if model == "claude" and requested != "claude" and not claude_enabled():
        # A saved Profile.preferred_model of "claude" from before the switch went
        # off shouldn't break every call: the user didn't ask for Sonnet-5 on
        # *this* request, so serve the free model. An explicit claude request is
        # left alone, so run_ai can answer it honestly with ClaudeUnavailable
        # instead of quietly substituting a different model.
        model = "groq"
    return model


def _max_tokens_for(operation):
    caps = settings.MAX_OUTPUT_TOKENS
    # Content-generation operations need more headroom than the default 800.
    # These are internal/free-model calls (news drafts, buying guides) where
    # a truncated response causes a JSON parse failure downstream.
    CONTENT_HEAVY_OPERATIONS = {
        "buying_guide_draft": 2000,
        "news_draft": 1200,
        "news_wrapup": 600,
    }
    return caps.get(operation, CONTENT_HEAVY_OPERATIONS.get(operation, caps.get("default", 800)))


def _credits_for(total_tokens):
    return max(
        settings.MIN_CREDIT_CHARGE,
        math.ceil(total_tokens / settings.TOKENS_PER_CREDIT),
    )


def _wallet_for(user):
    if user is None:
        return None
    wallet, _ = CreditWallet.objects.get_or_create(user=user)
    return wallet


def run_ai(*, user, operation, system, user_msg, model=None):
    """Run an AI operation and return a dict:
        {content, provider, model_name, tokens_in, tokens_out, est_cost_usd,
         cache_hit, credits_used, credits_remaining}

    Raises:
        ClaudeUnavailable  claude requested while the `claude_ai` flag is off.
            Checked before the wallet, so a zero-balance user is told the feature
            isn't live rather than being sold credits they can't spend.
        InsufficientCredits  claude requested with an empty wallet (pre-flight;
            the API is never called).
        LLMNotConfigured / LLMRequestFailed  propagated from the provider call;
            nothing is charged (the charge happens strictly after a successful
            claude call).
    """
    provider = resolve_model(user, model)
    max_tokens = _max_tokens_for(operation)

    if provider in ("groq", "gemini"):
        # Free path: keep the existing cache + Groq→Gemini fallback exactly.
        result = get_completion(tool=operation, system=system, user_msg=user_msg, max_tokens=max_tokens)
        model_used = result["model"]
        # Record the family we actually hit (fallback may swap providers).
        family = "gemini" if "gemini" in model_used.lower() else "groq"
        AIUsageRecord.objects.create(
            user=user,
            operation=operation,
            model=family,
            model_name=model_used,
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            est_cost_usd=Decimal(str(result["est_cost_usd"])),
            credits_charged=0,
        )
        wallet = _wallet_for(user)
        return {
            "content": result["content"],
            "provider": family,
            "model_name": model_used,
            "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"],
            "est_cost_usd": result["est_cost_usd"],
            "cache_hit": result["cache_hit"],
            "credits_used": 0,
            "credits_remaining": wallet.total_balance if wallet else None,
        }

    # -- Claude path (paid) --
    # Site-wide switch first: no wallet read, no API call, no charge.
    if not claude_enabled():
        raise ClaudeUnavailable(CLAUDE_DISABLED_MESSAGE)

    wallet = _wallet_for(user)
    # Pre-flight: zero balance never touches the API.
    if wallet is None or wallet.total_balance < settings.MIN_CREDIT_CHARGE:
        raise InsufficientCredits("no credits for Claude")

    content, tokens_in, tokens_out, model_used = claude_complete(system, user_msg, max_tokens)
    total = tokens_in + tokens_out
    charge = _credits_for(total)
    est_cost = estimate_cost_usd(model_used, tokens_in, tokens_out)

    with transaction.atomic():
        charged = wallet.charge_actual(charge, operation=operation, tokens=total)
        AIUsageRecord.objects.create(
            user=user,
            operation=operation,
            model="claude",
            model_name=model_used,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            est_cost_usd=Decimal(str(est_cost)),
            credits_charged=charged,
        )

    return {
        "content": content,
        "provider": "claude",
        "model_name": model_used,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "est_cost_usd": est_cost,
        "cache_hit": False,
        "credits_used": charged,
        "credits_remaining": wallet.total_balance,
    }