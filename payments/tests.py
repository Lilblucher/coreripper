"""Offline test suite for the payment flow  everything runs against the stub
provider (or pure model/util logic); no network is ever touched. The Lenco
adapter itself can only be exercised on the first live test (see the checklist
at the top of payments/lenco.py).
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import AuthToken, Payment
from accounts.subscription_utils import has_active_paid_subscription, settle_payment
from credits.tests import set_claude_flag, set_monetization_flag

from .models import FxRate, PlanPrice


def make_user(email, password="pw12345!", superuser=False):
    factory = User.objects.create_superuser if superuser else User.objects.create_user
    return factory(username=email, email=email, password=password)


def auth_headers(user):
    token = AuthToken.objects.create(user=user)
    return {"HTTP_AUTHORIZATION": f"Bearer {token.key}"}


def make_price(**overrides):
    fields = dict(
        label="Premium Monthly",
        display_amount_usd=Decimal("12.00"),
        period_days=30,
        is_active=True,
        sort_order=0,
    )
    fields.update(overrides)
    return PlanPrice.objects.create(**fields)


class FxTestMixin:
    """Deterministic offline FX: no network fetch ever happens, and a stored
    USD/ZMW rate of 27.5 makes $12 → K330.00 in every assertion."""

    FX_RATE = "27.5"

    def install_fx(self):
        cache.clear()
        patcher = mock.patch("payments.fx._fetch_live_rate", return_value=(None, None))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(cache.clear)
        FxRate.objects.update_or_create(
            pair="USD/ZMW",
            defaults={"rate": Decimal(self.FX_RATE), "source": "test", "fetched_at": timezone.now()},
        )


class PricingEndpointTests(FxTestMixin, TestCase):
    def setUp(self):
        self.client = Client()
        self.install_fx()

    def test_only_active_prices_are_public(self):
        make_price(label="Live", is_active=True)
        make_price(label="Hidden", is_active=False)
        data = self.client.get("/api/payments/pricing/").json()
        labels = [o["label"] for o in data["options"]]
        self.assertIn("Live", labels)
        self.assertNotIn("Hidden", labels)

    def test_zmw_amount_computed_from_rate(self):
        make_price(is_active=True)
        data = self.client.get("/api/payments/pricing/").json()
        self.assertEqual(data["options"][0]["amount_zmw"], "330.00")  # 12 × 27.5
        self.assertEqual(Decimal(data["fx"]["usd_to_zmw"]), Decimal("27.5"))
        self.assertEqual(data["fx"]["source"], "stored")

    def test_fx_fallback_when_nothing_stored(self):
        FxRate.objects.all().delete()
        cache.clear()
        make_price(is_active=True)
        with mock.patch.dict("os.environ", {"FX_FALLBACK_USD_ZMW": "25.00"}):
            # FALLBACK_USD_ZMW is read at import; patch the module constant too.
            with mock.patch("payments.fx.FALLBACK_USD_ZMW", "25.00"):
                data = self.client.get("/api/payments/pricing/").json()
        self.assertEqual(data["fx"]["source"], "fallback")
        self.assertEqual(data["options"][0]["amount_zmw"], "300.00")  # 12 × 25

    def test_config_never_leaks_secret(self):
        response = self.client.get("/api/payments/config/")
        self.assertNotIn("LENCO_API_KEY", response.content.decode())
        self.assertNotIn("api_key", response.json())


class CreateChargeTests(FxTestMixin, TestCase):
    def setUp(self):
        # Charge creation is gated on the `monetization` switch, which ships
        # OFF (open-source mode). These cover the funded/normal-paywall state;
        # the off state is test_create_charge_blocked_in_open_source_mode below.
        set_monetization_flag(True)
        self.install_fx()
        self.client = Client()
        self.user = make_user("payer@example.com")
        self.headers = auth_headers(self.user)
        self.price = make_price()

    def post_charge(self, body):
        return self.client.post(
            "/api/payments/create-charge/", json.dumps(body), content_type="application/json", **self.headers
        )

    def test_create_charge_blocked_in_open_source_mode(self):
        """While `monetization` is off, every account already has full access
        for free  a checkout attempt (subscription or pack) must be blocked
        server-side even if a stray client request reaches the endpoint."""
        set_monetization_flag(False)
        response = self.post_charge({"price_id": self.price.id, "method": "mtn_momo", "phone": "0961234567"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "monetization_disabled")
        self.assertFalse(Payment.objects.filter(user=self.user).exists())

    def test_requires_login(self):
        response = Client().post(
            "/api/payments/create-charge/",
            json.dumps({"price_id": self.price.id, "method": "mtn_momo", "phone": "0961234567"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_charge_snapshots_server_side_amount(self):
        response = self.post_charge(
            {"price_id": self.price.id, "method": "mtn_momo", "phone": "0961234567", "amount": "0.01"}
        )
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get(user=self.user)
        # The client-sent "amount" is ignored entirely  the PlanPrice decides.
        self.assertEqual(payment.amount, Decimal("330.00"))
        self.assertEqual(payment.currency, "ZMW")
        self.assertEqual(payment.method, "mtn_momo")
        self.assertEqual(payment.period_days, 30)
        self.assertEqual(payment.price_id, self.price.id)
        self.assertEqual(payment.status, "pending")

    def test_inactive_price_rejected(self):
        self.price.is_active = False
        self.price.save()
        response = self.post_charge({"price_id": self.price.id, "method": "mtn_momo", "phone": "0961234567"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_price")

    def test_zamtel_no_longer_accepted(self):
        response = self.post_charge({"price_id": self.price.id, "method": "zamtel_kwacha", "phone": "0961234567"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_method")

    def test_bad_phone_rejected_for_momo(self):
        response = self.post_charge({"price_id": self.price.id, "method": "airtel_money", "phone": "12345"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_phone")

    def test_phone_not_required_for_card(self):
        response = self.post_charge({"price_id": self.price.id, "method": "card"})
        self.assertEqual(response.status_code, 200)

    def test_card_can_charge_usd(self):
        response = self.post_charge({"price_id": self.price.id, "method": "card", "currency": "USD"})
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get(user=self.user)
        self.assertEqual(payment.currency, "USD")
        self.assertEqual(payment.amount, Decimal("12.00"))  # the USD price as-is

    def test_momo_forces_zmw_even_if_client_asks_usd(self):
        response = self.post_charge(
            {"price_id": self.price.id, "method": "mtn_momo", "phone": "0961234567", "currency": "USD"}
        )
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get(user=self.user)
        self.assertEqual(payment.currency, "ZMW")
        self.assertEqual(payment.amount, Decimal("330.00"))

    def test_invalid_currency_rejected(self):
        response = self.post_charge({"price_id": self.price.id, "method": "card", "currency": "EUR"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_currency")

    def test_rate_limit_trips_on_sixth_attempt(self):
        body = {"price_id": self.price.id, "method": "mtn_momo", "phone": "0961234567"}
        for _ in range(5):
            self.assertEqual(self.post_charge(body).status_code, 200)
        response = self.post_charge(body)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "rate_limited")


class SettlementTests(FxTestMixin, TestCase):
    def fresh_sub(self):
        # The post_save signal caches user.subscription on this exact instance
        # at creation time; settle_payment updates the row through its own
        # queryset, so tests must refresh before reading (request-scoped code
        # always loads users fresh and never hits this).
        self.user.subscription.refresh_from_db()
        return self.user.subscription

    def setUp(self):
        self.install_fx()
        self.user = make_user("settle@example.com")
        self.price = make_price()
        self.payment = Payment.objects.create(
            user=self.user,
            provider="stub",
            provider_ref="stub_testsettle",
            amount=Decimal("330.00"),
            currency="ZMW",
            method="mtn_momo",
            period_days=30,
            price=self.price,
            status="pending",
        )

    def test_settle_activates_premium_and_sends_receipt(self):
        from credits.models import CreditWallet

        self.assertTrue(settle_payment(self.payment.pk))
        sub = self.fresh_sub()
        self.assertTrue(sub.is_premium)
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.plan, "pro")  # legacy "premium" price → pro tier
        self.assertEqual(sub.renewal_state, "not_due")
        self.assertAlmostEqual((sub.expires_at - timezone.now()).days, 29, delta=1)
        # Settlement grants the tier's monthly Claude credits.
        wallet = CreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.subscription_balance, 1500)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("receipt", mail.outbox[0].subject.lower())
        self.assertIn("K330.00", mail.outbox[0].body)
        self.assertIn("$12.00", mail.outbox[0].body)

    def test_settle_is_idempotent(self):
        self.assertTrue(settle_payment(self.payment.pk))
        expires_first = self.fresh_sub().expires_at
        self.assertFalse(settle_payment(self.payment.pk))
        self.assertEqual(self.fresh_sub().expires_at, expires_first)
        self.assertEqual(len(mail.outbox), 1)  # one receipt, not two

    def test_receipt_failure_does_not_unpay(self):
        with mock.patch(
            "accounts.subscription_utils.send_payment_receipt", side_effect=RuntimeError("smtp down")
        ):
            self.assertTrue(settle_payment(self.payment.pk))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")
        self.assertTrue(self.fresh_sub().is_premium)

    def test_verify_endpoint_is_owner_scoped(self):
        client = Client()
        headers = auth_headers(self.user)
        other = make_user("other@example.com")
        other_headers = auth_headers(other)
        response = client.get(f"/api/payments/verify/{self.payment.provider_ref}/", **other_headers)
        self.assertEqual(response.status_code, 404)  # not your payment

        response = client.get(f"/api/payments/verify/{self.payment.provider_ref}/", **headers)
        self.assertEqual(response.json()["status"], "pending")

    def test_admin_plan_lock(self):
        superuser = make_user("boss@example.com", superuser=True)
        su_headers = auth_headers(superuser)
        client = Client()

        # Before payment: not locked.
        self.assertFalse(has_active_paid_subscription(self.user))
        settle_payment(self.payment.pk)
        self.fresh_sub()
        self.assertTrue(has_active_paid_subscription(self.user))

        # Users list carries the flag.
        data = client.get("/api/accounts/admin/users/", **su_headers).json()
        row = next(u for u in data["users"] if u["email"] == "settle@example.com")
        self.assertTrue(row["paid_subscriber"])

        # PATCHing the plan is refused with 409.
        response = client.patch(
            f"/api/accounts/admin/users/{self.user.id}/",
            json.dumps({"plan": "free"}),
            content_type="application/json",
            **su_headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "paid_subscriber")

        # is_staff stays editable.
        response = client.patch(
            f"/api/accounts/admin/users/{self.user.id}/",
            json.dumps({"is_staff": True}),
            content_type="application/json",
            **su_headers,
        )
        self.assertEqual(response.status_code, 200)

        # Lock lifts once the paid period expires. Paid expiry is beat-driven
        # (grace window), so the shim doesn't lazy-expire on expires_at  simulate
        # what expire_unrenewed does: flip status→expired, plan→free.
        sub = self.fresh_sub()
        sub.status = "expired"
        sub.plan = "free"
        sub.current_period_end = timezone.now() - timedelta(days=1)
        sub.expires_at = sub.current_period_end
        sub.save()
        self.assertFalse(has_active_paid_subscription(self.user))
        response = client.patch(
            f"/api/accounts/admin/users/{self.user.id}/",
            json.dumps({"plan": "free"}),
            content_type="application/json",
            **su_headers,
        )
        self.assertEqual(response.status_code, 200)


class AdminPricingCrudTests(FxTestMixin, TestCase):
    def setUp(self):
        self.install_fx()
        self.client = Client()
        self.superuser = make_user("root@example.com", superuser=True)
        self.su_headers = auth_headers(self.superuser)
        self.normal = make_user("pleb@example.com")
        self.normal_headers = auth_headers(self.normal)

    def test_non_superuser_forbidden(self):
        response = self.client.get("/api/payments/admin/prices/", **self.normal_headers)
        self.assertEqual(response.status_code, 403)

    def test_create_validate_update_delete(self):
        # Bad amount rejected.
        response = self.client.post(
            "/api/payments/admin/prices/",
            json.dumps({"label": "Annual", "display_amount_usd": "-5", "period_days": 365}),
            content_type="application/json",
            **self.su_headers,
        )
        self.assertEqual(response.status_code, 400)

        # Create (USD only  ZMW is computed from the live rate; inactive unless is_active sent).
        response = self.client.post(
            "/api/payments/admin/prices/",
            json.dumps({"label": "Annual", "display_amount_usd": "120", "period_days": 365}),
            content_type="application/json",
            **self.su_headers,
        )
        self.assertEqual(response.status_code, 201)
        price_id = response.json()["price"]["id"]
        self.assertFalse(response.json()["price"]["is_active"])
        self.assertEqual(response.json()["price"]["amount_zmw"], "3300.00")  # 120 × 27.5, computed

        # Activate via PATCH → appears on the public endpoint.
        response = self.client.patch(
            f"/api/payments/admin/prices/{price_id}/",
            json.dumps({"is_active": True}),
            content_type="application/json",
            **self.su_headers,
        )
        self.assertEqual(response.status_code, 200)
        public = Client().get("/api/payments/pricing/").json()
        self.assertIn("Annual", [o["label"] for o in public["options"]])

        # Delete.
        response = self.client.delete(f"/api/payments/admin/prices/{price_id}/", **self.su_headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PlanPrice.objects.filter(pk=price_id).exists())


class WebhookTests(TestCase):
    def test_webhook_disabled_without_secret(self):
        with mock.patch.dict("os.environ", {"LENCO_WEBHOOK_SECRET": ""}):
            response = Client().post(
                "/api/payments/webhook/lenco/whatever/", json.dumps({}), content_type="application/json"
            )
        self.assertEqual(response.status_code, 404)

    def test_webhook_wrong_secret_forbidden(self):
        with mock.patch.dict("os.environ", {"LENCO_WEBHOOK_SECRET": "correct-secret"}):
            response = Client().post(
                "/api/payments/webhook/lenco/wrong-secret/", json.dumps({}), content_type="application/json"
            )
        self.assertEqual(response.status_code, 403)

    def test_webhook_unknown_ref_ignored(self):
        with mock.patch.dict("os.environ", {"LENCO_WEBHOOK_SECRET": "correct-secret"}):
            response = Client().post(
                "/api/payments/webhook/lenco/correct-secret/",
                json.dumps({"ref": "nonexistent", "status": "paid"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ignored"))


class LencoAdapterOfflineTests(FxTestMixin, TestCase):
    """What CAN be tested about the Lenco adapter with no network: phone
    formatting and that an unconfigured gateway yields a clean 503  proving
    the whole PAYMENT_PROVIDER=lenco wiring end-to-end."""

    def setUp(self):
        set_monetization_flag(True)
        self.install_fx()
        self.user = make_user("lenco@example.com")
        self.headers = auth_headers(self.user)
        self.price = make_price()

    def test_phone_formatting(self):
        # Lenco's mobile-money endpoint takes the MSISDN in international form
        # ("2609XXXXXXXX"); every accepted local/international input normalizes
        # to that (PHONE_FORMAT="international", verified against the live API).
        from .lenco import format_phone

        self.assertEqual(format_phone("+260961234567"), "260961234567")
        self.assertEqual(format_phone("260961234567"), "260961234567")
        self.assertEqual(format_phone("0961234567"), "260961234567")
        self.assertEqual(format_phone("961234567"), "260961234567")

    def test_unconfigured_lenco_returns_503(self):
        import payments

        with mock.patch.dict(
            "os.environ", {"PAYMENT_PROVIDER": "lenco", "LENCO_API_KEY": "", "LENCO_PUBLIC_KEY": ""}
        ):
            with mock.patch.object(payments, "_PROVIDER_INSTANCE", None):
                response = self.client.post(
                    "/api/payments/create-charge/",
                    json.dumps({"price_id": self.price.id, "method": "mtn_momo", "phone": "0961234567"}),
                    content_type="application/json",
                    **self.headers,
                )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "gateway_not_configured")
        # The failed attempt did not leave a dangling pending payment.
        self.assertFalse(Payment.objects.filter(user=self.user, status="pending").exists())


class CreditPackTests(FxTestMixin, TestCase):
    """Phase 4: one-time Claude-credit pack checkout. Same stub-provider offline
    setup as the subscription flow  the seeded packs (payments migration 0006)
    are the real purchasable rows, so tests use them directly."""

    def setUp(self):
        # Packs only buy Sonnet-5, so checkout is gated on both the claude_ai
        # switch and the monetization switch, which both ship OFF. These cover
        # the funded state; the off states are
        # test_pack_charge_blocked_while_sonnet5_switched_off below and
        # CreateChargeTests.test_create_charge_blocked_in_open_source_mode.
        set_claude_flag(True)
        set_monetization_flag(True)
        self.install_fx()
        self.client = Client()
        self.user = make_user("packs@example.com")
        self.headers = auth_headers(self.user)
        from .models import CreditPackPrice

        self.starter = CreditPackPrice.objects.get(label="Starter")

    def post_charge(self, body):
        return self.client.post(
            "/api/payments/create-charge/", json.dumps(body), content_type="application/json", **self.headers
        )

    def test_pricing_lists_only_active_packs(self):
        from .models import CreditPackPrice

        CreditPackPrice.objects.filter(label="Ultimate").update(is_active=False)
        data = self.client.get("/api/payments/pricing/").json()
        labels = [p["label"] for p in data["packs"]]
        self.assertEqual(labels, ["Starter", "Basic", "Standard", "Pro"])
        starter = data["packs"][0]
        self.assertEqual(starter["credits"], 250)
        self.assertEqual(starter["amount_zmw"], "27.23")  # 0.99 × 27.5

    def test_pack_charge_snapshots_credits_and_amount(self):
        response = self.post_charge(
            {"pack_id": self.starter.id, "method": "mtn_momo", "phone": "0961234567", "amount": "0.01"}
        )
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get(user=self.user)
        self.assertEqual(payment.amount, Decimal("27.23"))
        self.assertEqual(payment.currency, "ZMW")
        self.assertEqual(payment.credits_amount, 250)
        self.assertEqual(payment.pack_id, self.starter.id)
        self.assertIsNone(payment.price_id)
        self.assertEqual(payment.period_days, 0)
        self.assertEqual(payment.status, "pending")

    def test_pack_charge_blocked_while_sonnet5_switched_off(self):
        """Credits only buy Sonnet-5, so with the switch off a pack purchase would
        take real money for something unusable. Subscriptions stay buyable  their
        non-AI tier benefits are all live."""
        set_claude_flag(False)
        response = self.post_charge(
            {"pack_id": self.starter.id, "method": "mtn_momo", "phone": "0961234567"}
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "claude_disabled")
        self.assertFalse(Payment.objects.filter(user=self.user).exists())  # no dangling pending row

        price = make_price()
        subscription = self.post_charge(
            {"price_id": price.id, "method": "mtn_momo", "phone": "0961234567"}
        )
        self.assertEqual(subscription.status_code, 200)

    def test_pricing_reports_pack_availability(self):
        self.assertIs(self.client.get("/api/payments/pricing/").json()["packs_available"], True)
        set_claude_flag(False)
        data = self.client.get("/api/payments/pricing/").json()
        self.assertIs(data["packs_available"], False)
        # Still listed, so the pricing page can show what's coming  just not buyable.
        self.assertTrue(data["packs"])

    def test_price_and_pack_together_rejected(self):
        price = make_price()
        response = self.post_charge(
            {"pack_id": self.starter.id, "price_id": price.id, "method": "mtn_momo", "phone": "0961234567"}
        )
        self.assertEqual(response.status_code, 400)

    def test_inactive_pack_rejected(self):
        from .models import CreditPackPrice

        CreditPackPrice.objects.filter(pk=self.starter.pk).update(is_active=False)
        response = self.post_charge({"pack_id": self.starter.id, "method": "mtn_momo", "phone": "0961234567"})
        self.assertEqual(response.status_code, 400)

    def _settled_pack_payment(self):
        payment = Payment.objects.create(
            user=self.user,
            provider="stub",
            provider_ref="stub_packsettle",
            amount=Decimal("27.23"),
            currency="ZMW",
            method="mtn_momo",
            period_days=0,
            pack=self.starter,
            credits_amount=250,
            status="pending",
        )
        self.assertTrue(settle_payment(payment.pk))
        return payment

    def test_settle_grants_pack_credits_not_premium(self):
        from credits.models import CreditWallet, PackCreditLot

        payment = self._settled_pack_payment()
        wallet = CreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.pack_balance, 250)
        self.assertEqual(wallet.subscription_balance, 0)
        lot = PackCreditLot.objects.get(user=self.user)
        self.assertEqual(lot.credits_remaining, 250)
        self.assertEqual(lot.purchase_ref, payment.provider_ref)
        self.assertAlmostEqual((lot.expires_at - timezone.now()).days, 364, delta=1)
        # The subscription is untouched  a pack is not a plan.
        self.user.subscription.refresh_from_db()
        self.assertFalse(self.user.subscription.is_premium)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("250", mail.outbox[0].body)
        self.assertIn("credit", mail.outbox[0].body.lower())

    def test_pack_settle_is_idempotent(self):
        from credits.models import CreditWallet

        payment = self._settled_pack_payment()
        self.assertFalse(settle_payment(payment.pk))
        self.assertEqual(CreditWallet.objects.get(user=self.user).pack_balance, 250)

    def test_pack_purchase_does_not_plan_lock(self):
        sub = self.user.subscription
        sub.plan = "pro"
        sub.status = "trialing"
        sub.expires_at = timezone.now() + timedelta(days=3)
        sub.current_period_end = sub.expires_at
        sub.save()
        self._settled_pack_payment()
        self.assertFalse(has_active_paid_subscription(self.user))
