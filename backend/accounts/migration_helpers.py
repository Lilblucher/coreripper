"""Pure helpers used by data migrations (kept out of the numbered migration
module so they can be imported and unit-tested directly)."""


def classify_legacy_subscription(*, plan, active, expires_at, has_paid_payment, now):
    """Map the legacy (plan, active, expires_at) + payment history onto the new
    (status, plan) pair. Never downgrades a paying customer during migration.

    Returns (new_status, new_plan)."""
    unexpired = active and (expires_at is None or expires_at >= now)
    if plan == "premium" and unexpired:
        if has_paid_payment:
            return "active", "pro"  # closest successor to old Premium
        return "trialing", "pro"    # current 3-day signup trials
    return "expired", "free"
