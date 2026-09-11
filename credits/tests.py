import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import (
    AIUsageRecord,
    ClaudeUnavailable,
    CreditLedger,
    CreditWallet,
    InsufficientCredits,
    PackCreditLot,
)
from . import services, tasks


def make_user(email="u@example.com"):
    return User.objects.create_user(username=email, email=email, password="pw12345!")


def set_claude_flag(enabled):
    """Flip the `claude_ai` kill switch for a test, cache included.

    The flag ships OFF (core migration 0007) because Anthropic credits aren't
    funded yet, and migrations run for the test database too  so any test that
    exercises the Sonnet-5 path or a credit-pack purchase has to opt in. Engine
    tests assert what happens once the switch is on; ClaudeSwitchTests below
    covers the off state.
    """
    from django.core.cache import cache

    from core.middleware import FLAG_CACHE_KEY
    from core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="claude_ai", defaults={"label": "Sonnet-5 AI", "enabled": enabled}
    )
    cache.delete(FLAG_CACHE_KEY)


def set_monetization_flag(enabled):
    """Flip the `monetization` kill switch for a test, cache included.

    Ships OFF (open-source mode) because the Lenco payment key isn't funded
    yet  same reasoning/mechanics as set_claude_flag above. Tests that assume
    the normal paywall (premium gates, payment checkout) must opt in."""
    from django.core.cache import cache

    from core.middleware import FLAG_CACHE_KEY
    from core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="monetization", defaults={"label": "Monetization", "enabled": enabled}
    )
    cache.delete(FLAG_CACHE_KEY)


class ClaudeEnabledMixin:
    """setUp hook for suites that assume Sonnet-5 is funded and live."""

    def setUp(self):
        set_claude_flag(True)
        super().setUp()


class WalletTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.wallet = self.user.credit_wallet  # created by the signal

    def test_spend_order_and_ledger(self):
        self.wallet.grant("subscription", 5, "monthly_refresh")
        self.wallet.grant_pack(4)
        self.wallet.spend(6, operation="x")  # drains 5 sub then 1 pack
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.subscription_balance, 0)
        self.assertEqual(self.wallet.pack_balance, 3)
        # A subscription spend row (balance_after 0) and a pack spend row (3).
        spends = CreditLedger.objects.filter(user=self.user, reason="spend").order_by("id")
        self.assertEqual([(s.bucket, s.delta, s.balance_after) for s in spends],
                         [("subscription", -5, 0), ("pack", -1, 3)])

    def test_pack_lots_consumed_earliest_expiry_first(self):
        now = timezone.now()
        self.wallet.grant_pack(2, expires_at=now + timedelta(days=300))  # later
        self.wallet.grant_pack(2, expires_at=now + timedelta(days=10))   # sooner
        self.wallet.spend(3, operation="x")
        lots = PackCreditLot.objects.filter(user=self.user).order_by("expires_at")
        self.assertEqual(lots[0].credits_remaining, 0)  # sooner drained first
        self.assertEqual(lots[1].credits_remaining, 1)

    def test_insufficient_leaves_state_untouched(self):
        self.wallet.grant("subscription", 3, "monthly_refresh")
        with self.assertRaises(InsufficientCredits):
            self.wallet.spend(4, operation="x")
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.subscription_balance, 3)
        self.assertEqual(CreditLedger.objects.filter(reason="spend").count(), 0)

    def test_charge_actual_clamps_at_zero(self):
        self.wallet.grant("subscription", 3, "monthly_refresh")
        charged = self.wallet.charge_actual(10, operation="x")
        self.assertEqual(charged, 3)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.total_balance, 0)

    def test_grant_pack_default_expiry_is_365_days(self):
        lot = self.wallet.grant_pack(100)
        delta = lot.expires_at - timezone.now()
        self.assertAlmostEqual(delta.days, 365, delta=1)

    def test_reset_subscription_writes_reset_and_refresh_rows(self):
        self.wallet.grant("subscription", 4, "monthly_refresh")
        self.wallet.reset_subscription(10)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.subscription_balance, 10)
        self.assertTrue(CreditLedger.objects.filter(reason="expiry_reset", delta=-4).exists())
        self.assertTrue(CreditLedger.objects.filter(reason="monthly_refresh", delta=10).exists())
        self.assertIsNotNone(self.wallet.last_refresh_at)


class ExpirePackCreditsTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.wallet = self.user.credit_wallet

    def test_expires_only_past_lots_and_is_idempotent(self):
        now = timezone.now()
        self.wallet.grant_pack(5, expires_at=now - timedelta(days=1))  # already expired
        self.wallet.grant_pack(3, expires_at=now + timedelta(days=30))  # live
        tasks.expire_pack_credits()
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.pack_balance, 3)  # only the live lot remains
        self.assertEqual(CreditLedger.objects.filter(reason="pack_expiry").count(), 1)
        # Run again  no double-charge.
        tasks.expire_pack_credits()
        self.assertEqual(CreditLedger.objects.filter(reason="pack_expiry").count(), 1)


class RunAiTests(ClaudeEnabledMixin, TestCase):
    def setUp(self):
        super().setUp()  # switches claude_ai on  these cover the funded state
        self.user = make_user()
        self.wallet = self.user.credit_wallet

    def test_free_path_records_usage_and_charges_nothing(self):
        fake = {"content": "hi", "tokens_in": 10, "tokens_out": 5,
                "model": "llama-3.1-8b-instant", "cache_hit": False, "est_cost_usd": 0.001}
        with mock.patch("credits.services.get_completion", return_value=fake) as gc:
            res = services.run_ai(user=self.user, operation="feedback_tutor",
                                  system="s", user_msg="u", model="groq")
        gc.assert_called_once()
        self.assertEqual(res["provider"], "groq")
        self.assertEqual(res["credits_used"], 0)
        rec = AIUsageRecord.objects.get(user=self.user)
        self.assertEqual(rec.model, "groq")
        self.assertEqual(rec.credits_charged, 0)

    def test_claude_zero_balance_rejected_preflight(self):
        with mock.patch("credits.services.claude_complete") as cc:
            with self.assertRaises(InsufficientCredits):
                services.run_ai(user=self.user, operation="feedback_tutor",
                                system="s", user_msg="u", model="claude")
        cc.assert_not_called()  # API never touched

    def test_claude_charges_actual_tokens(self):
        self.wallet.grant("subscription", 100, "monthly_refresh")
        # 300 in + 200 out = 500 tokens → ceil(500/250) = 2 credits.
        with mock.patch("credits.services.claude_complete",
                        return_value=("answer", 300, 200, "claude-sonnet-5")):
            res = services.run_ai(user=self.user, operation="feedback_tutor",
                                  system="s", user_msg="u", model="claude")
        self.assertEqual(res["provider"], "claude")
        self.assertEqual(res["credits_used"], 2)
        self.assertEqual(res["credits_remaining"], 98)
        rec = AIUsageRecord.objects.get(model="claude")
        self.assertEqual(rec.credits_charged, 2)

    def test_claude_charge_clamps_when_balance_short(self):
        self.wallet.grant("subscription", 1, "monthly_refresh")
        with mock.patch("credits.services.claude_complete",
                        return_value=("answer", 3000, 3000, "claude-sonnet-5")):
            res = services.run_ai(user=self.user, operation="feedback_tutor",
                                  system="s", user_msg="u", model="claude")
        self.assertEqual(res["credits_used"], 1)  # clamped, never negative
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.total_balance, 0)

    def test_none_user_never_routes_to_claude(self):
        fake = {"content": "x", "tokens_in": 1, "tokens_out": 1,
                "model": "gemini-1.5-flash", "cache_hit": False, "est_cost_usd": 0}
        with mock.patch("credits.services.get_completion", return_value=fake):
            res = services.run_ai(user=None, operation="news_draft",
                                  system="s", user_msg="u", model="claude")
        self.assertIn(res["provider"], ("groq", "gemini"))
        self.assertEqual(res["credits_used"], 0)

    def test_preferred_model_used_when_unspecified(self):
        self.user.profile.preferred_model = "claude"
        self.user.profile.save()
        self.wallet.grant("subscription", 10, "monthly_refresh")
        with mock.patch("credits.services.claude_complete",
                        return_value=("a", 100, 100, "claude-sonnet-5")) as cc:
            services.run_ai(user=self.user, operation="feedback_tutor", system="s", user_msg="u")
        cc.assert_called_once()


class ClaudeSwitchTests(TestCase):
    """The `claude_ai` kill switch: Sonnet-5 stays wired but unreachable until
    Anthropic credits are funded. Flipping the flag on is the only step  no
    code change  so these lock in both states of that one switch."""

    def setUp(self):
        set_claude_flag(False)
        self.user = make_user()
        self.wallet = self.user.credit_wallet
        self.wallet.grant("subscription", 100, "monthly_refresh")

    def test_explicit_claude_request_raises_without_touching_api(self):
        with mock.patch("credits.services.claude_complete") as cc:
            with self.assertRaises(ClaudeUnavailable):
                services.run_ai(user=self.user, operation="feedback_tutor",
                                system="s", user_msg="u", model="claude")
        cc.assert_not_called()

    def test_switched_off_never_charges_a_funded_wallet(self):
        with mock.patch("credits.services.claude_complete"):
            with self.assertRaises(ClaudeUnavailable):
                services.run_ai(user=self.user, operation="feedback_tutor",
                                system="s", user_msg="u", model="claude")
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.subscription_balance, 100)
        self.assertFalse(AIUsageRecord.objects.filter(user=self.user).exists())

    def test_switched_off_beats_insufficient_credits(self):
        """An empty wallet must still hear "not available yet", not "buy credits"
        selling a pack for a model that can't run would be selling nothing."""
        self.wallet.subscription_balance = 0
        self.wallet.save(update_fields=["subscription_balance"])
        with self.assertRaises(ClaudeUnavailable):
            services.run_ai(user=self.user, operation="feedback_tutor",
                            system="s", user_msg="u", model="claude")

    def test_stale_saved_preference_falls_back_to_free_model(self):
        """A profile left on "claude" from before the switch went off shouldn't
        break every call  the user didn't request Sonnet-5 on this one."""
        self.user.profile.preferred_model = "claude"
        self.user.profile.save()
        self.assertEqual(services.resolve_model(self.user, None), "groq")
        # An explicit request is still honoured as claude, so run_ai can answer
        # it honestly rather than silently substituting a different model.
        self.assertEqual(services.resolve_model(self.user, "claude"), "claude")

    def test_flag_on_restores_the_claude_path(self):
        set_claude_flag(True)
        with mock.patch("credits.services.claude_complete",
                        return_value=("a", 100, 100, "claude-sonnet-5")) as cc:
            res = services.run_ai(user=self.user, operation="feedback_tutor",
                                  system="s", user_msg="u", model="claude")
        cc.assert_called_once()
        self.assertEqual(res["provider"], "claude")

    def test_missing_flag_row_fails_closed(self):
        """Unlike every other flag, a missing claude_ai row means OFF  a fresh
        database silently going live on a paid API is the one failure mode that
        costs real money."""
        from core.models import FeatureFlag
        from django.core.cache import cache
        from core.middleware import FLAG_CACHE_KEY

        FeatureFlag.objects.filter(key="claude_ai").delete()
        cache.delete(FLAG_CACHE_KEY)
        self.assertFalse(services.claude_enabled())

    def test_public_features_endpoint_reports_the_switch(self):
        from django.test import Client

        res = Client().get("/api/features/")
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.content)
        self.assertIs(body["features"]["claude_ai"], False)
        self.assertIs(body["features"]["monetization"], False)
        # Never widen the public view beyond the two model-choice/paywall
        # switches that need to be readable while logged out.
        self.assertEqual(set(body["features"]), {"claude_ai", "monetization"})


class ClaudeCompleteTests(TestCase):
    def test_raises_without_key(self):
        from core.llm import claude_complete, LLMNotConfigured

        with self.settings(ANTHROPIC_API_KEY=""):
            with self.assertRaises(LLMNotConfigured):
                claude_complete("s", "u", 100)

    def test_request_shape_and_usage_parsing(self):
        from core.llm import claude_complete

        payload = {
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 100, "cache_creation_input_tokens": 20,
                      "cache_read_input_tokens": 30, "output_tokens": 40},
        }
        resp = mock.Mock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        with self.settings(ANTHROPIC_API_KEY="sk-test", CLAUDE_MODEL="claude-sonnet-5"):
            with mock.patch("core.llm.requests.post", return_value=resp) as post:
                content, tin, tout, model = claude_complete("SYS", "USER", 500)
        self.assertEqual(content, "hello")
        self.assertEqual(tin, 150)  # input + cache_creation + cache_read
        self.assertEqual(tout, 40)
        self.assertEqual(model, "claude-sonnet-5")
        _, kwargs = post.call_args
        self.assertEqual(kwargs["headers"]["x-api-key"], "sk-test")
        self.assertIn("anthropic-version", kwargs["headers"])
        self.assertEqual(kwargs["json"]["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(kwargs["json"]["thinking"], {"type": "disabled"})


class BeatTaskTests(TestCase):
    def _sub(self, email, **fields):
        user = make_user(email)
        sub = user.subscription
        for k, v in fields.items():
            setattr(sub, k, v)
        sub.save()
        return user, sub

    def test_expire_trials(self):
        now = timezone.now()
        user, sub = self._sub("t@example.com", status="trialing", plan="pro",
                              current_period_end=now - timedelta(hours=1))
        tasks.expire_trials()
        sub.refresh_from_db()
        self.assertEqual(sub.status, "expired")
        self.assertEqual(sub.plan, "free")

    def test_request_renewals_idempotent_one_email(self):
        from django.core import mail

        now = timezone.now()
        user, sub = self._sub("r@example.com", status="active", plan="pro",
                              renewal_state="not_due",
                              current_period_end=now + timedelta(days=1))
        tasks.request_renewals()
        tasks.request_renewals()  # second run: already awaiting_payment
        sub.refresh_from_db()
        self.assertEqual(sub.renewal_state, "awaiting_payment")
        self.assertEqual(len(mail.outbox), 1)

    def test_expire_unrenewed_grace_then_expiry_preserves_packs(self):
        now = timezone.now()
        user, sub = self._sub("g@example.com", status="active", plan="pro",
                              current_period_end=now - timedelta(hours=1))
        user.credit_wallet.grant_pack(50)
        # Within grace window → grace, still premium, features keep working.
        tasks.expire_unrenewed()
        sub.refresh_from_db()
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.renewal_state, "grace")
        self.assertTrue(sub.is_premium)
        # Past the grace window → expired/free, but pack credits survive.
        sub.current_period_end = now - timedelta(days=10)
        sub.save()
        tasks.expire_unrenewed()
        sub.refresh_from_db()
        self.assertEqual(sub.status, "expired")
        self.assertEqual(sub.plan, "free")
        self.assertEqual(user.credit_wallet.pack_balance, 50)

    def test_refresh_is_idempotent_same_day(self):
        now = timezone.now()
        user, sub = self._sub("f@example.com", status="active", plan="pro",
                              current_period_end=now + timedelta(days=60))
        tasks.refresh_subscription_credits()
        tasks.refresh_subscription_credits()  # last_refresh_at guards a second grant
        wallet = user.credit_wallet
        wallet.refresh_from_db()
        self.assertEqual(wallet.subscription_balance, 1500)


class ReconcileTests(TestCase):
    def test_fix_restores_from_ledger(self):
        from django.core.management import call_command
        from io import StringIO

        user = make_user()
        wallet = user.credit_wallet
        wallet.grant("subscription", 20, "monthly_refresh")
        # Corrupt the cache.
        CreditWallet.objects.filter(pk=wallet.pk).update(subscription_balance=99)
        out = StringIO()
        call_command("reconcile_credit_wallets", "--fix", stdout=out)
        wallet.refresh_from_db()
        self.assertEqual(wallet.subscription_balance, 20)


class MigrationMappingTests(TestCase):
    def test_classify(self):
        from accounts.migration_helpers import classify_legacy_subscription as classify

        now = timezone.now()
        # paid active → active/pro
        self.assertEqual(classify(plan="premium", active=True, expires_at=None,
                                  has_paid_payment=True, now=now), ("active", "pro"))
        # trial (active, no paid) → trialing/pro
        self.assertEqual(classify(plan="premium", active=True, expires_at=None,
                                  has_paid_payment=False, now=now), ("trialing", "pro"))
        # lapsed → expired/free
        self.assertEqual(classify(plan="premium", active=False, expires_at=None,
                                  has_paid_payment=False, now=now), ("expired", "free"))


class SignupVerificationTests(TestCase):
    def test_signup_then_verify_flow(self):
        from django.core import mail
        from django.test import Client

        client = Client()
        # Signup: no token, subscription stays expired/free.
        r = client.post("/api/accounts/signup/",
                        data='{"email":"new@example.com","password":"password123"}',
                        content_type="application/json")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["verification_required"])
        self.assertNotIn("token", r.json())
        user = User.objects.get(username="new@example.com")
        self.assertFalse(user.profile.email_verified)
        self.assertEqual(user.subscription.status, "expired")

        # Login before verify → 403.
        r = client.post("/api/accounts/login/",
                        data='{"email":"new@example.com","password":"password123"}',
                        content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"], "email_unverified")

        # Pull the code from the token row (console email in tests).
        from accounts.models import EmailVerificationToken
        code = EmailVerificationToken.objects.filter(user=user, used=False).latest("created_at").token

        # Wrong code increments attempts.
        r = client.post("/api/accounts/verify-email/",
                        data='{"email":"new@example.com","code":"000000"}',
                        content_type="application/json")
        self.assertEqual(r.status_code, 400)

        # Correct code → token issued, trialing/pro, wallet 0/0.
        r = client.post("/api/accounts/verify-email/",
                        data=f'{{"email":"new@example.com","code":"{code}"}}',
                        content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.json())
        user.refresh_from_db()
        self.assertTrue(user.profile.email_verified)
        self.assertEqual(user.subscription.status, "trialing")
        self.assertEqual(user.subscription.plan, "pro")
        self.assertEqual(user.credit_wallet.total_balance, 0)
