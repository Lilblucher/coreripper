"""Session-lifecycle tests: AuthToken expiry + the Remember-Me refresh flow.

Runs offline on SQLite via core_backend.test_settings, same as credits/payments:
    manage.py test accounts --settings=core_backend.test_settings

Signup/verification/wallet integration coverage lives in credits/tests.py;
this file covers what the 2026-07-25 session-hardening pass added.
"""

import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from .models import AuthToken, RefreshToken


def make_verified_user(email="sess@example.com", password="pw12345!"):
    user = User.objects.create_user(username=email, email=email, password=password)
    user.profile.email_verified = True
    user.profile.save(update_fields=["email_verified"])
    return user


def post_json(client, path, payload, **extra):
    return client.post(
        path,
        data=json.dumps(payload),
        content_type="application/json",
        **extra,
    )


class LoginSessionTests(TestCase):
    def setUp(self):
        self.user = make_verified_user()
        self.client = Client()

    def login(self, remember_me=False):
        return post_json(
            self.client,
            "/api/accounts/login/",
            {"email": self.user.email, "password": "pw12345!", "remember_me": remember_me},
        )

    def test_login_issues_expiring_token_without_refresh(self):
        res = self.login()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertNotIn("refresh_token", data)
        token = AuthToken.objects.get(key=data["token"])
        self.assertIsNotNone(token.expires_at)
        expected = timezone.now() + timedelta(hours=settings.AUTH_TOKEN_LIFETIME_HOURS)
        self.assertAlmostEqual(token.expires_at.timestamp(), expected.timestamp(), delta=60)
        self.assertEqual(data["token_expires_at"], token.expires_at.isoformat())

    def test_remember_me_issues_hashed_refresh_token(self):
        data = self.login(remember_me=True).json()
        raw = data["refresh_token"]
        rt = RefreshToken.objects.get(user=self.user)
        # Only the SHA-256 lands in the DB, linked to the login's AuthToken.
        self.assertNotEqual(rt.token_hash, raw)
        self.assertEqual(rt.token_hash, RefreshToken.hash_raw(raw))
        self.assertEqual(rt.auth_token.key, data["token"])
        self.assertFalse(rt.revoked)
        expected = timezone.now() + timedelta(days=settings.REFRESH_TOKEN_LIFETIME_DAYS)
        self.assertAlmostEqual(rt.expires_at.timestamp(), expected.timestamp(), delta=60)

    def test_expired_token_is_rejected_by_middleware(self):
        data = self.login().json()
        AuthToken.objects.filter(key=data["token"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        res = self.client.get(
            "/api/accounts/me/",
            HTTP_AUTHORIZATION=f"Bearer {data['token']}",
        )
        self.assertEqual(res.status_code, 401)

    def test_valid_token_still_authenticates(self):
        data = self.login().json()
        res = self.client.get(
            "/api/accounts/me/",
            HTTP_AUTHORIZATION=f"Bearer {data['token']}",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["email"], self.user.email)


class RefreshFlowTests(TestCase):
    def setUp(self):
        self.user = make_verified_user()
        self.client = Client()
        res = post_json(
            self.client,
            "/api/accounts/login/",
            {"email": self.user.email, "password": "pw12345!", "remember_me": True},
        )
        self.session = res.json()

    def refresh(self, raw):
        return post_json(self.client, "/api/accounts/refresh/", {"refresh_token": raw})

    def test_refresh_rotates_both_tokens_and_keeps_the_session_row(self):
        old_key = self.session["token"]
        old_raw = self.session["refresh_token"]
        token_id = AuthToken.objects.get(key=old_key).id

        res = self.refresh(old_raw)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Same AuthToken row (stable session list), new bearer key + expiry.
        token = AuthToken.objects.get(id=token_id)
        self.assertEqual(token.key, data["token"])
        self.assertNotEqual(data["token"], old_key)
        # Old refresh token is single-use; a successor exists on the same row.
        self.assertNotEqual(data["refresh_token"], old_raw)
        old_rt = RefreshToken.objects.get(token_hash=RefreshToken.hash_raw(old_raw))
        self.assertTrue(old_rt.revoked)
        new_rt = RefreshToken.objects.get(token_hash=RefreshToken.hash_raw(data["refresh_token"]))
        self.assertFalse(new_rt.revoked)
        self.assertEqual(new_rt.auth_token_id, token_id)
        # The old bearer key no longer authenticates; the new one does.
        self.assertEqual(
            self.client.get(
                "/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {old_key}"
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                "/api/accounts/me/", HTTP_AUTHORIZATION=f"Bearer {data['token']}"
            ).status_code,
            200,
        )

    def test_used_refresh_token_is_rejected(self):
        raw = self.session["refresh_token"]
        self.assertEqual(self.refresh(raw).status_code, 200)
        self.assertEqual(self.refresh(raw).status_code, 401)

    def test_expired_refresh_token_is_rejected(self):
        RefreshToken.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(self.refresh(self.session["refresh_token"]).status_code, 401)

    def test_garbage_refresh_token_is_rejected(self):
        self.assertEqual(self.refresh("not-a-real-token").status_code, 401)
        res = post_json(self.client, "/api/accounts/refresh/", {})
        self.assertEqual(res.status_code, 400)

    def test_revoking_the_session_kills_its_refresh_chain(self):
        token = AuthToken.objects.get(key=self.session["token"])
        res = self.client.delete(
            f"/api/accounts/sessions/{token.id}/",
            HTTP_AUTHORIZATION=f"Bearer {token.key}",
        )
        self.assertEqual(res.status_code, 200)
        # CASCADE took the refresh token with it  no silent resurrection.
        self.assertEqual(RefreshToken.objects.filter(user=self.user).count(), 0)
        self.assertEqual(self.refresh(self.session["refresh_token"]).status_code, 401)


class LogoutTests(TestCase):
    def setUp(self):
        self.user = make_verified_user()
        self.client = Client()
        res = post_json(
            self.client,
            "/api/accounts/login/",
            {"email": self.user.email, "password": "pw12345!", "remember_me": True},
        )
        self.session = res.json()

    def test_logout_with_bearer_token_deletes_session_and_refresh(self):
        res = post_json(
            self.client,
            "/api/accounts/logout/",
            {"refresh_token": self.session["refresh_token"]},
            HTTP_AUTHORIZATION=f"Bearer {self.session['token']}",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 0)
        self.assertEqual(RefreshToken.objects.filter(user=self.user).count(), 0)

    def test_logout_with_only_refresh_token_still_kills_the_session(self):
        # The access token already expired  logout must still work off the
        # refresh token alone (the swept frontend snippet sends both).
        AuthToken.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        res = post_json(
            self.client,
            "/api/accounts/logout/",
            {"refresh_token": self.session["refresh_token"]},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 0)
        self.assertEqual(RefreshToken.objects.filter(user=self.user).count(), 0)

    def test_logout_never_fails(self):
        res = post_json(self.client, "/api/accounts/logout/", {})
        self.assertEqual(res.status_code, 200)


class SessionsListTests(TestCase):
    def setUp(self):
        self.user = make_verified_user()
        self.client = Client()

    def login(self, remember_me=False):
        return post_json(
            self.client,
            "/api/accounts/login/",
            {"email": self.user.email, "password": "pw12345!", "remember_me": remember_me},
        ).json()

    def test_expired_sessions_hidden_and_remembered_flagged(self):
        remembered = self.login(remember_me=True)
        plain = self.login()
        stale = self.login()
        AuthToken.objects.filter(key=stale["token"]).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        res = self.client.get(
            "/api/accounts/sessions/",
            HTTP_AUTHORIZATION=f"Bearer {plain['token']}",
        )
        sessions = res.json()["sessions"]
        self.assertEqual(len(sessions), 2)  # the expired one is gone
        by_current = {s["is_current"]: s for s in sessions}
        self.assertTrue(by_current[False]["remembered"])   # the Remember-Me login
        self.assertFalse(by_current[True]["remembered"])   # this plain login
        self.assertEqual(
            by_current[True]["expires_at"],
            AuthToken.objects.get(key=plain["token"]).expires_at.isoformat(),
        )
