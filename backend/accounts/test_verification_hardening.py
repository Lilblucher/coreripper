"""Tests for the verification-code hardening pass.

Covers every change from the 2026-09 security patch:
  1. EmailVerificationToken generates an 8-char alphanumeric code (not 6-digit numeric)
  2. PasswordResetToken gets the same generator
  3. verify_email_view checks expiry BEFORE burning an attempt on the code match
  4. verify_email_view normalises the submitted code to uppercase before comparing
  5. Attempt cap still burns the token after RESET_MAX_ATTEMPTS wrong guesses
  6. Lockout (used=True after max attempts) is respected on subsequent calls

Run with:
    manage.py test accounts.test_verification_hardening --settings=core_backend.test_settings

Or alongside the rest of the accounts suite:
    manage.py test accounts --settings=core_backend.test_settings
"""

import json
import re
import string
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from .models import EmailVerificationToken, PasswordResetToken


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_ALPHABET = set(
    c for c in (string.ascii_uppercase + string.digits)
    if c not in "O0I1L"
)


def make_unverified_user(email="test@example.com", password="strongpass1!"):
    user = User.objects.create_user(username=email, email=email, password=password)
    # post_save creates Profile automatically; email_verified stays False
    return user


def post_json(client, path, payload):
    return client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# 1. Code generation — EmailVerificationToken
# ---------------------------------------------------------------------------

class EmailVerificationTokenGenerationTests(TestCase):

    def setUp(self):
        self.user = make_unverified_user()

    def _make_token(self):
        return EmailVerificationToken.objects.create(user=self.user)

    def test_token_is_8_characters(self):
        tok = self._make_token()
        self.assertEqual(len(tok.token), 8,
            f"Expected 8-char token, got {len(tok.token)!r}: {tok.token!r}")

    def test_token_uses_only_valid_alphabet(self):
        tok = self._make_token()
        invalid = [c for c in tok.token if c not in VALID_ALPHABET]
        self.assertEqual(invalid, [],
            f"Token {tok.token!r} contains disallowed chars: {invalid}")

    def test_token_contains_no_ambiguous_chars(self):
        """None of O, 0, I, 1, L should ever appear."""
        for _ in range(50):          # 50 tokens to be statistically confident
            tok = EmailVerificationToken.objects.create(user=self.user)
            for bad in "O0I1L":
                self.assertNotIn(bad, tok.token,
                    f"Ambiguous char {bad!r} found in token {tok.token!r}")
            tok.delete()

    def test_token_is_uppercase(self):
        tok = self._make_token()
        self.assertEqual(tok.token, tok.token.upper(),
            f"Token {tok.token!r} is not all-uppercase")

    def test_token_is_not_purely_numeric(self):
        """Old format was always 6 digits; new format must not be."""
        # Generate enough tokens that the chance of getting all-numeric by
        # chance is negligible (~32^-8 per token).
        all_numeric = True
        for _ in range(10):
            tok = EmailVerificationToken.objects.create(user=self.user)
            if not tok.token.isdigit():
                all_numeric = False
                tok.delete()
                break
            tok.delete()
        self.assertFalse(all_numeric,
            "All 10 generated tokens were purely numeric — generator not updated?")

    def test_token_not_regenerated_on_resave(self):
        tok = self._make_token()
        original = tok.token
        tok.used = True
        tok.save(update_fields=["used"])
        tok.refresh_from_db()
        self.assertEqual(tok.token, original,
            "Token was regenerated on a non-create save — guard condition broken")

    def test_each_new_token_is_unique(self):
        """Uniqueness isn't enforced at DB level, but the generator must not
        produce the same code twice in a row for the same user."""
        tokens = set()
        for _ in range(20):
            tok = EmailVerificationToken.objects.create(user=self.user)
            tokens.add(tok.token)
        # With a 32^8 keyspace, collisions across 20 draws are astronomically
        # rare — if we get one the generator is broken.
        self.assertEqual(len(tokens), 20,
            "Duplicate tokens detected across 20 draws — RNG may be broken")


# ---------------------------------------------------------------------------
# 2. Code generation — PasswordResetToken (same fix, same guarantees)
# ---------------------------------------------------------------------------

class PasswordResetTokenGenerationTests(TestCase):

    def setUp(self):
        self.user = make_unverified_user(email="reset@example.com")

    def _make_token(self):
        return PasswordResetToken.objects.create(user=self.user)

    def test_token_is_8_characters(self):
        tok = self._make_token()
        self.assertEqual(len(tok.token), 8,
            f"Expected 8-char reset token, got {len(tok.token)!r}: {tok.token!r}")

    def test_token_uses_only_valid_alphabet(self):
        tok = self._make_token()
        invalid = [c for c in tok.token if c not in VALID_ALPHABET]
        self.assertEqual(invalid, [],
            f"Reset token {tok.token!r} contains disallowed chars: {invalid}")

    def test_no_ambiguous_chars_in_reset_token(self):
        for _ in range(50):
            tok = PasswordResetToken.objects.create(user=self.user)
            for bad in "O0I1L":
                self.assertNotIn(bad, tok.token,
                    f"Ambiguous char {bad!r} found in reset token {tok.token!r}")
            tok.delete()

    def test_reset_token_is_not_purely_numeric(self):
        all_numeric = True
        for _ in range(10):
            tok = PasswordResetToken.objects.create(user=self.user)
            if not tok.token.isdigit():
                all_numeric = False
                tok.delete()
                break
            tok.delete()
        self.assertFalse(all_numeric,
            "All 10 reset tokens were purely numeric — generator not updated?")


# ---------------------------------------------------------------------------
# 3. verify_email_view — expiry checked BEFORE attempting code match
# ---------------------------------------------------------------------------

class VerifyEmailExpiryOrderTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_unverified_user(email="expiry@example.com")
        self.token = EmailVerificationToken.objects.create(user=self.user)

    def _verify(self, code, email="expiry@example.com"):
        return post_json(self.client, "/api/accounts/verify-email/",
                         {"email": email, "code": code})

    def _expire_token(self):
        """Back-date created_at so the token is past its 15-minute window."""
        EmailVerificationToken.objects.filter(pk=self.token.pk).update(
            created_at=timezone.now() - timedelta(minutes=16)
        )
        self.token.refresh_from_db()

    def test_expired_token_returns_expired_code_error(self):
        self._expire_token()
        res = self._verify(self.token.token)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"], "expired_code",
            "Expected 'expired_code', got: " + res.json().get("error", "?"))

    def test_expired_token_does_not_burn_an_attempt(self):
        """Submitting the correct code against an expired token must NOT
        increment attempts — expiry is caught first, before the match check."""
        self._expire_token()
        before = self.token.attempts
        self._verify(self.token.token)      # correct code, expired token
        self.token.refresh_from_db()
        self.assertEqual(self.token.attempts, before,
            "Attempt counter was incremented for an expired token submission")

    def test_expired_token_with_wrong_code_also_does_not_burn_attempt(self):
        """Expiry must short-circuit even when the submitted code is wrong."""
        self._expire_token()
        before = self.token.attempts
        self._verify("WRONGCOD")
        self.token.refresh_from_db()
        self.assertEqual(self.token.attempts, before,
            "Attempt counter was incremented even though token was expired")

    def test_expired_token_is_marked_used(self):
        self._expire_token()
        self._verify(self.token.token)
        self.token.refresh_from_db()
        self.assertTrue(self.token.used,
            "Expired token was not marked used after expiry check")

    def test_non_expired_wrong_code_increments_attempts(self):
        """Sanity check: a still-valid token with a wrong code SHOULD burn."""
        before = self.token.attempts
        self._verify("WRONGCOD")
        self.token.refresh_from_db()
        self.assertEqual(self.token.attempts, before + 1,
            "Attempt counter was NOT incremented for a valid-window wrong-code submission")


# ---------------------------------------------------------------------------
# 4. verify_email_view — case normalisation (lowercase input accepted)
# ---------------------------------------------------------------------------

class VerifyEmailCaseNormalisationTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_unverified_user(email="case@example.com")
        self.token = EmailVerificationToken.objects.create(user=self.user)

    def _verify(self, code):
        return post_json(self.client, "/api/accounts/verify-email/",
                         {"email": "case@example.com", "code": code})

    def test_lowercase_code_is_accepted(self):
        """User types the code in lowercase — view must normalise to uppercase."""
        lowercase_code = self.token.token.lower()
        res = self._verify(lowercase_code)
        # 200 = verified; anything else means case normalisation is missing
        self.assertEqual(res.status_code, 200,
            f"Lowercase code rejected (status {res.status_code}): {res.json()}")

    def test_mixed_case_code_is_accepted(self):
        """Mixed capitalisation must also be accepted."""
        code = self.token.token
        # Alternate lower/upper: e.g. "a3X9kP4r"
        mixed = "".join(c.lower() if i % 2 == 0 else c.upper() for i, c in enumerate(code))
        res = self._verify(mixed)
        self.assertEqual(res.status_code, 200,
            f"Mixed-case code rejected (status {res.status_code}): {res.json()}")

    def test_uppercase_code_still_accepted(self):
        """Baseline: the canonical uppercase form must always work."""
        res = self._verify(self.token.token)
        self.assertEqual(res.status_code, 200,
            f"Uppercase code rejected (status {res.status_code}): {res.json()}")


# ---------------------------------------------------------------------------
# 5. verify_email_view — attempt cap burns token after RESET_MAX_ATTEMPTS
# ---------------------------------------------------------------------------

class VerifyEmailAttemptCapTests(TestCase):
    MAX_ATTEMPTS = 5   # mirrors RESET_MAX_ATTEMPTS in views.py

    def setUp(self):
        self.client = Client()
        self.user = make_unverified_user(email="attempts@example.com")
        self.token = EmailVerificationToken.objects.create(user=self.user)

    def _wrong_attempt(self):
        return post_json(self.client, "/api/accounts/verify-email/",
                         {"email": "attempts@example.com", "code": "WRONGCOD"})

    def test_token_burned_after_max_wrong_attempts(self):
        for _ in range(self.MAX_ATTEMPTS):
            self._wrong_attempt()
        self.token.refresh_from_db()
        self.assertTrue(self.token.used,
            f"Token not marked used after {self.MAX_ATTEMPTS} wrong attempts")

    def test_correct_code_rejected_after_lockout(self):
        """Once the token is burned, even the real code must be rejected."""
        for _ in range(self.MAX_ATTEMPTS):
            self._wrong_attempt()
        # Try the correct code on the now-burned token
        res = post_json(self.client, "/api/accounts/verify-email/",
                        {"email": "attempts@example.com", "code": self.token.token})
        self.assertNotEqual(res.status_code, 200,
            "Correct code accepted on a burned (used=True) token — lockout not enforced")

    def test_attempts_counted_correctly(self):
        for i in range(1, self.MAX_ATTEMPTS + 1):
            self._wrong_attempt()
            self.token.refresh_from_db()
            expected_attempts = i
            self.assertEqual(self.token.attempts, expected_attempts,
                f"After {i} wrong attempts, expected attempts={expected_attempts}, "
                f"got {self.token.attempts}")

    def test_four_wrong_then_correct_still_succeeds(self):
        """One attempt to spare: MAX-1 wrong guesses, then the real code works."""
        for _ in range(self.MAX_ATTEMPTS - 1):
            self._wrong_attempt()
        # The token must still be active
        self.token.refresh_from_db()
        self.assertFalse(self.token.used,
            "Token burned after only MAX_ATTEMPTS-1 wrong guesses")
        res = post_json(self.client, "/api/accounts/verify-email/",
                        {"email": "attempts@example.com", "code": self.token.token})
        self.assertEqual(res.status_code, 200,
            f"Correct code rejected with one attempt to spare: {res.json()}")


# ---------------------------------------------------------------------------
# 6. Full happy-path: signup → verify → session issued
# ---------------------------------------------------------------------------

class VerifyEmailHappyPathTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_unverified_user(email="happy@example.com")
        self.token = EmailVerificationToken.objects.create(user=self.user)

    def test_correct_code_returns_token_and_user(self):
        res = post_json(self.client, "/api/accounts/verify-email/",
                        {"email": "happy@example.com", "code": self.token.token})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("token", data, "No bearer token in verification response")
        self.assertIn("user", data, "No user object in verification response")

    def test_correct_code_marks_email_verified(self):
        post_json(self.client, "/api/accounts/verify-email/",
                  {"email": "happy@example.com", "code": self.token.token})
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.email_verified,
            "email_verified not set to True after successful verification")

    def test_correct_code_marks_token_used(self):
        post_json(self.client, "/api/accounts/verify-email/",
                  {"email": "happy@example.com", "code": self.token.token})
        self.token.refresh_from_db()
        self.assertTrue(self.token.used,
            "Token not marked used after successful verification")

    def test_replay_attack_rejected(self):
        """Using the same (now-used) token a second time must be refused."""
        post_json(self.client, "/api/accounts/verify-email/",
                  {"email": "happy@example.com", "code": self.token.token})
        res = post_json(self.client, "/api/accounts/verify-email/",
                        {"email": "happy@example.com", "code": self.token.token})
        # Either already_verified (profile) or invalid_code (token is used=True)
        self.assertNotEqual(res.status_code, 200,
            "Second use of the same verification token was accepted — replay not blocked")

    def test_already_verified_user_gets_correct_error(self):
        post_json(self.client, "/api/accounts/verify-email/",
                  {"email": "happy@example.com", "code": self.token.token})
        # A second totally different token for the same now-verified user
        new_token = EmailVerificationToken.objects.create(user=self.user)
        res = post_json(self.client, "/api/accounts/verify-email/",
                        {"email": "happy@example.com", "code": new_token.token})
        self.assertEqual(res.json().get("error"), "already_verified",
            f"Expected 'already_verified', got: {res.json()}")
