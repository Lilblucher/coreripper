# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CoreRipper (formerly CoreLom) is a web toolkit: 80+ developer/AI/network tools, a blog, an
AI-curated news feed, a hardware/gaming content pipeline, user accounts with a
Guest/Free + four paid tiers (lite/standard/pro) plus a Claude-credit economy,
monitoring/alerts, and an admin "Engine Room" cockpit.
Backend is Django with plain JSON views (no DRF). Frontend is 96 static HTML pages with
Tailwind via CDN and vanilla JS  **no build step, no bundler, no framework**.

## Commands

**Run the backend** (must use the anaconda interpreter  system `python3` has no Django installed):
```
cd backend && /home/clive/anaconda3/bin/python manage.py runserver 8000
```
**This is local-dev only.** The live VPS (`coreripper.site`, Contabo, `/srv/coreripper/backend`,
deploy user `deploy`) runs gunicorn under systemd instead — see "Production deployment (VPS)"
under Architecture below. Don't `manage.py runserver` on the VPS even to firefight; it dies the
moment the SSH session that started it closes, which is what caused the 2026-07-30 outage below.

**Run the frontend** (use the no-cache wrapper, not plain `http.server`  see Gotchas):
```
cd frontend && python3 _nocache_server.py 5501
```

**Syntax-check every inline `<script>` across all 96 pages** (run this after any sweep-script
edit, before trusting the browser  a `SyntaxError` in one page's inline JS fails silently, it
just stops that page's script executing):
```
cd frontend && python3 -c "
import re, glob, subprocess, tempfile, os
bad = 0
for path in sorted(glob.glob('**/*.html', recursive=True)):
    s = open(path).read()
    for m in re.finditer(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', s, re.S):
        if not m.group(1).strip(): continue
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as f: f.write(m.group(1)); t = f.name
        r = subprocess.run(['node', '--check', t], capture_output=True, text=True); os.unlink(t)
        if r.returncode: bad += 1; print('FAIL', path, r.stderr.strip().splitlines()[-1])
print('done,', bad, 'failures')
"
```

**Run Celery** (worker + beat, required for monitors/news/hardware ingestion, digests, newsletter):
```
/home/clive/anaconda3/bin/celery -A core_backend worker -l info --concurrency=2
/home/clive/anaconda3/bin/celery -A core_backend beat -l info
```
None of these three processes are services  they're started manually and do not survive a
reboot or long idle gap  `MONITORING_SETUP_COMMANDS.md`'s Celery systemd units were never
created, so worker and beat really are hand-started every time. **Redis is the exception**: it is
a real systemd unit (`redis-server` 8.0.5, `active` and `enabled` at boot) and its `CACHES` swap
is done, so don't re-run that part of the setup doc. Before assuming anything is running, check:
```
curl -s http://127.0.0.1:8000/api/stats/
ps aux | grep celery
redis-cli ping          # expect PONG; Redis backs Celery *and* the trial/quota cache
```

**Migrations / management commands** (all from `backend/`, all via the anaconda interpreter):
```
/home/clive/anaconda3/bin/python manage.py migrate
/home/clive/anaconda3/bin/python manage.py seed_tools        # idempotent: seeds the Tool registry
/home/clive/anaconda3/bin/python manage.py seed_blog          # idempotent: seeds blog posts/categories
/home/clive/anaconda3/bin/python manage.py aggregate_news     # manual trigger for the news RSS pipeline
/home/clive/anaconda3/bin/python manage.py reclassify_news [--apply] [--status X]  # dry-run by default: replays news/services.py::classify_category over stored NewsDraft rows (category is assigned once at ingest, never revisited on its own)
/home/clive/anaconda3/bin/python manage.py fetch_category_images  # idempotent: (re)fills CategoryImage pools
/home/clive/anaconda3/bin/python manage.py mcp_server         # exposes local/operational tools over MCP
/home/clive/anaconda3/bin/python manage.py sync_hardware_specs [--type cpu|gpu|laptop|mobile_soc]  # idempotent: live Wikidata spec sync
/home/clive/anaconda3/bin/python manage.py seed_hardware_specs    # idempotent: hand-curated fallback hardware dataset
```
Note there is **no `aggregate_hardware_content` management command** (unlike news' `aggregate_news`)
 hardware *article* ingestion exists only as the Celery task. To trigger it by hand (e.g. to pull
fresh drafts for review without waiting for the 07:00/19:00 UTC beat), call the task directly:
```
/home/clive/anaconda3/bin/python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core_backend.settings'); django.setup(); from hardware.tasks import aggregate_hardware_content; print(aggregate_hardware_content())"
```
It hits the live RSS feeds, dedups on source URL, and lands everything as `status=pending` for
review in the Engine Room's Hardware tab. Ingested drafts are real content  leave them in the
queue, don't delete them as throwaway test data.

**Tests**: `payments`, `credits`, and `accounts` have real test suites (`backend/payments/tests.py`
+ `backend/credits/tests.py` + `backend/accounts/tests.py`  the last covers the session/refresh
lifecycle; signup/verification/wallet integration still lives in `credits/tests.py`); run them with:
```
cd backend && /home/clive/anaconda3/bin/python manage.py test credits payments accounts --settings=core_backend.test_settings
```
77 tests as of the Sonnet-5 kill-switch work; a single class/test runs as e.g.
`manage.py test payments.tests.CreditPackTests --settings=core_backend.test_settings`.
This uses SQLite in-memory (not Postgres) because the `corelom` role deliberately lacks CREATEDB.
Every other app's `tests.py` is a stub. The one non-pytest test lives outside any app:
```
cd backend && /home/clive/anaconda3/bin/python tests/test_dns_lookup.py
```
Verification in this codebase is done ad hoc: Django shell one-liners against the real DB,
`curl` against real endpoints, and browser-preview tooling against the real frontend. When adding
a feature, verify it the same way (real HTTP calls, real browser checks) rather than assuming a
test file must exist. Payment features are an exception  the dual-provider pattern (stub for
testing, Lenco for production) + idempotent settlement semantics + rate snapshot invariants
justify comprehensive offline coverage.

**Getting a logged-in browser session for that verification** (needed for anything gated 
dashboard, settings, billing, the AI tools). Don't try to drive the login form; mint a token and
inject it, since auth is a bearer token in `localStorage`, not a cookie:
```
/home/clive/anaconda3/bin/python -c "
import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core_backend.settings'); django.setup()
from django.contrib.auth.models import User
from accounts.models import AuthToken
from django.utils import timezone; from datetime import timedelta
u=User.objects.get(email='...')   # a user whose subscription.is_premium is True
print(AuthToken.objects.create(user=u, device_label='verify-session',
      expires_at=timezone.now()+timedelta(hours=8)).key)"
```
Then in the page context set `coreripperToken` + `coreripperTokenExpiresAt`, fetch
`/api/accounts/me/` and cache it as `coreripperUser`, and *then* navigate to the gated page 
navigating first just bounces you to `login.html`. Delete the token row and any test rows
(sections, projects, monitors) afterwards: this is the real database, and these are real user
accounts, not fixtures. Note an AI call made while verifying leaves a permanent `AIUsageRecord`
on that user  say so rather than quietly leaving it.

**Env config**: `backend/.env` (see `.env.example`). Nothing crashes if it's unset  LLM calls
raise a catchable `LLMNotConfigured`, payments fall back to a stub adapter, email falls back to
Django's console backend. Credit/AI env vars: `ANTHROPIC_API_KEY=` (unset → Claude tools return
a clean 503; the credit wallet gate still returns 402 correctly), `CLAUDE_MODEL=claude-sonnet-5`
(config only  never render a model version in customer copy), `PAYMENTS_CARD_ENABLED=0` (kill
switch: cards stay wired but hidden until set to `1`  mobile money only for now). Payment env
vars: `PAYMENT_PROVIDER=stub` (default; set to `lenco` for
production), `LENCO_API_KEY=` (secret, env-only, lazy-loaded), `LENCO_PUBLIC_KEY=` (for the
card widget), `LENCO_WEBHOOK_SECRET=` (any long random string; 404 if unset). FX rate env vars:
`FX_API_URL=` (optional override for market-rate feed), `FX_FALLBACK_USD_ZMW=27.00` (default
fallback if APIs unreachable). Gotcha: `load_dotenv()` won't override a var already exported
(even blank) in the shell  if an edit to `.env` doesn't seem to take, `echo $VAR` first.

**Deployment env vars** (all default to the current local-dev behavior, so setting none of them
changes nothing on this box): `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=1`, `DJANGO_ALLOWED_HOSTS=`
(comma-separated; **required once `DJANGO_DEBUG=0` or every request 400s DisallowedHost**),
`DJANGO_CSRF_TRUSTED_ORIGINS=` (comma-separated, scheme included), `DJANGO_CORS_ALLOWED_ORIGINS=`
(same shape). These were hardcoded in `settings.py` until the VPS-readiness pass  don't
re-hardcode them. `CORS_ALLOW_ALL_ORIGINS` is now derived, not set: it is true only when
`DEBUG` is on *and* no whitelist is given, so a production box can never silently stay wide open.
`backend/.env.example` is the annotated master list of every var the code reads, with the go-live
checklist at the top; `.env` mirrors it with the local-dev values.

## Architecture

### Backend apps (`backend/`)
One Django project (`core_backend`), one app per concern, wired together in
`core_backend/urls.py` via `include()`:
- `accounts`  bearer-token auth, subscriptions, trial/quota, password reset, admin user/tx management
- `core`  AI tool endpoints, the LLM client, `$`-spend quota, the `Tool` registry, feature flags, site stats
- `network_tools`  the network-tool dispatcher (see below)
- `dashboard`  Premium "Workbench" backend (saved results, sections, export)
- `blog`  blog posts/categories, public + admin API, sitemap, RSS
- `news`  AI-curated tech news: HN/RSS ingestion → AI draft → moderation → publish
- `hardware`  hardware/gaming content: RSS ingestion → moderation → publish, plus CPU/GPU/Laptop/MobileSoC
  spec models fed by a multi-provider sync pipeline and a structured AI Knowledge layer (see
  "Hardware Hub" below)  the device-vs-device comparison engine that used to live here was
  removed 2026-07-29, see "In-flight work" below
- `monitors`  scheduled uptime/SSL/etc. checks with email/WhatsApp alerting
- `payments`  subscription charge/verify behind a swappable stub adapter
- `credits`  the Claude-credit economy: wallet/ledger/pack-lots, the `run_ai()` AI router,
  subscription-lifecycle beat tasks, wallet reconcile command, and read-only
  `GET /api/credits/wallet/` + `/history/` for the frontend credit meter (see "The credit engine"
  below)

### Frontend (`frontend/`)
Static HTML, one file per page, **zero shared bundle**  every page's `<style>` block and
helper JS is copied verbatim into that file. A site-wide visual or behavioral change means
writing a Python sweep script that edits all affected pages (dry-run first), not editing one
shared component. This is deliberate, not an oversight  don't try to "fix" it by introducing
a shared include/bundle unless asked.

**Brand tokens** (counted off the live pages, since `FRONTEND_DESIGN_SYSTEM.md` still documents
the pre-rebrand purple  see the root-docs warning above): primary `#2597e8`, secondary/lighter
`#15a6de`, page background `#0a0a0a`, body text `#e5e7eb`, muted `#9ca3af`/`#6b7280`. Dark theme
is the real target; a `body.light-mode` override exists on most pages as a secondary concern.
**Default font is `'Space Grotesk'`, not Inter** (swapped 2026-07-29  Inter is kept only as the
fallback in the stack, `font-family: 'Space Grotesk', 'Inter', sans-serif`, and every page's
Google Fonts `<link>` loads Space Grotesk at the full 400;500;600;700;800 weight range). When
adding markup to a page, copy the neighbouring page's existing classes rather than introducing
new tokens.

**The hex-load indicator is the default loading action**, replacing the old plain CSS ring
spinner. It's a small per-page JS pair  `crHexSpinner(px)` (a looping spinning-hexagon mark,
shown for the duration of a real async call) and `crHexStrike(container)` (an async function that
plays a settle-then-strike flourish on that same mark, awaited immediately before swapping in the
real result)  copied into each page next to its other helpers (see `mx_lookup.html` for the
reference copy). Reference spec: `~/Documents/coreRipper(flutter)/LOADING_INDICATOR_HANDOFF.md`.
Live on all network/dev-tool pages that show a loading state. Gotcha already hit once: the
`crHexStrike`/`crHexSpinner` insertion sometimes lands inside a page's own already-single-quoted
JS string (e.g. a `style.cssText` built from `'...' + '...'` chunks)  wrapping the font name in
its own quotes there breaks the enclosing string (`'font-family:'Space Grotesk',...'`), so inside
an existing single-quoted string the font name must stay unquoted.

**Article/card image containers use `aspect-ratio`, not fixed pixel heights (2026-08-04).** All
seven pages that render article images (blog.html, blog/post.html, news.html, news/post.html,
hardware.html, hardware/article.html, index.html's news-teaser thumb) size their image containers
with `aspect-ratio: 16/9` (cards) or `aspect-ratio: 21/9` (article-detail heroes, dropping to
16:9 under 480px) + `width:100%; height:auto;`. The SVG fallback icons (shown when no photo
resolves) use percentage-based sizing (`width:20%; height:20%`) with `min-width`/`max-width`
clamps so they scale proportionally with the container at any viewport width. Don't revert these
to fixed pixel heights  the old pattern (e.g. `height:320px`) produced a near-square box on
phones (375px wide, 320px tall) that made the fallback icon look tiny and lost, and made real
photos crop aggressively. `object-fit:cover` on the `<img>` is unchanged.

**Mobile layout is a separate, sweep-injected override layer, not a rewrite of each page's own
CSS (2026-07-30).** `frontend/_mobile_sweep.py` injects one `<style id="cr-mobile">` block
(wrapped in `<!-- CR_MOBILE_START -->` / `<!-- CR_MOBILE_END -->` markers so re-running the
script replaces it in place instead of stacking copies) before `</head>` on all 97 pages. It
only activates at `max-width: 768px` (tighter passes at 480px/360px) and never touches desktop
rules  the goal was "keep every feature and animation, just make phones not look like squeezed
desktop," not a redesign. Re-run it after any change to the block:
```
cd frontend && python3 _mobile_sweep.py
```
Two things worth knowing before extending it:
- **A per-page override you write can still get clobbered by a later, more specific rule the
  page already had.** The footer (`.cr-footer-grid`) already had its own better-than-generic
  2-column mobile CSS baked into several pages; the sweep's first pass blanket-forced 1-column
  with `!important`, which fought that existing rule and produced a needlessly tall footer. Check
  what a page already does at that breakpoint before overriding it, rather than assuming a
  generic rule is the first word on the subject.
- Marker comments must be **HTML comments** (`<!-- ... -->`), not CSS comments (`/* ... */` written
  outside the `<style>` tag)  a CSS-style marker sitting in the raw HTML before the `<style>` tag
  opens renders as literal visible text in the page body, not a comment.
- **The mobile nav menu (`#crMobileMenu`) uses a `max-height` collapse animation, so its open
  cap must clear the tallest content or the last items clip silently.** The open rule was a fixed
  `max-height:420px` on all 87 pages; measured content was 419px (Home/Tools/Pricing + the flat
  Blog/News/Hardware Discover sub-list = 8 links), i.e. one pixel from clipping the last Discover
  option, and item heights vary page to page (290-419px) with font/line-height. Changed sitewide
  to `max-height:80vh;overflow-y:auto` (2026-08-02) so it can never clip and scrolls if it ever
  exceeds the viewport. This lives in each page's own `<style>` (the `#crMobileMenu.open{...}`
  rule), *outside* the `CR_MOBILE` sweep markers, so it's edited by its own one-off replace, not
  `_mobile_sweep.py`.

**The backend origin is `window.CR_API_BASE`, never a literal host.** An inline `<head>` script
in all 96 pages resolves it once per page: `location.origin` normally, `<protocol>//<host>:8000`
when the hostname is localhost/127.0.0.1/[::1] (dev serves the static pages on their own port),
and `http://127.0.0.1:8000` for `file://`. Every API call reads it  as `window.CR_API_BASE +
'/api/...'`, as `` `${window.CR_API_BASE}/api/...` ``, or via the page's own
`var API_BASE = window.CR_API_BASE`. Hardcoding a host again re-breaks every API call on the
real domain (that was the state of all 96 pages until the go-live sweep).

### Auth: bearer tokens, not sessions
`accounts.AuthToken` is the single site-wide auth mechanism (one token per login/device).
`accounts.middleware.TokenAuthMiddleware` resolves `Authorization: Bearer <token>` into
`request.user` for every app  this is why `request.user.is_authenticated` / `is_staff` /
`is_superuser` checks work identically everywhere. Invariant: `User.username == User.email`;
anything that creates a user another way must preserve this or login silently fails. Frontend
pages store the token as `localStorage.coreripperToken` + `coreripperUser` (cached JSON from
`/api/accounts/me/`) after login/signup. Admin = `is_staff OR is_superuser`; paid access is a
completely orthogonal concept (`Subscription`) and never implies admin. **Signup now requires
email verification**: `signup_view` creates the user but issues no token and no trial  it emails
a 6-digit code (same OTP shape as password reset, `accounts.EmailVerificationToken`);
`verify-email/` marks `Profile.email_verified`, starts the 3-day pro trial, and issues the token;
`login_view` returns `403 email_unverified` until then. Pre-existing users are grandfathered
verified by a data migration.

**Tokens expire + Remember-Me refresh (session-hardening pass, 2026-07-25).** Every new
AuthToken gets `expires_at = now + AUTH_TOKEN_LIFETIME_HOURS` (8h default; middleware rejects
expired keys; pre-existing tokens were backfilled with a 60-day deadline, and a null expiry
means "immortal legacy row"). Ticking "Remember me on this device" on login.html adds an
`accounts.RefreshToken`: SHA-256 hash only in the DB, single-use, 60-day sliding lifetime
(`REFRESH_TOKEN_LIFETIME_DAYS`), CASCADE-tied to its AuthToken so revoking a session on
settings.html also kills resurrection. `POST /api/accounts/refresh/` rotates BOTH tokens but
keeps the same AuthToken *row* (stable Active Sessions list  only its bearer `key` changes);
`POST /api/accounts/logout/` deletes the session server-side, works off the refresh token alone
when the access token already expired, and always returns 200. Client-side this is owned by a
swept `CoreRipperAuth` head snippet in all 96 pages (sits right after the CR_API_BASE resolver 
edit via sweep script, never per page): stores `coreripperRefreshToken`/`coreripperTokenExpiresAt`
beside the token, silently renews inside the last 90 min, reloads the page when it restores a
fully-lapsed session, and exposes `CoreRipperAuth.store(data)` / `.logout()`. Every explicit
logout call site was sweep-rewired to `.logout()`; 401-cleanup sites (ending in `return null;`
or a login.html redirect) deliberately still clear only the token so the keeper can resurrect an
expired-but-not-revoked session. Two deliberate non-features: a replayed (already-used) refresh
token gets a plain 401, **not** a chain-revoke  two tabs racing the same single-use token is far
likelier than a real replay, and the snippet only discards a dead refresh token if another tab
hasn't already rotated it; and `change-password`'s replacement token ships with no refresh token
(compromise signal  long-lived credentials must be re-earned by a fresh Remember-Me login).
`accounts/tests.py` is no longer a stub: 13 session-lifecycle tests, same offline-SQLite runner
as credits/payments.

**Browser-close + idle session policy (2026-07-25).** Bearer tokens live in `localStorage`, which
by itself outlives a browser restart  reopening the browser landed you back in the previous
account. The same swept `CoreRipperAuth` snippet now owns two client-side end-of-session rules on
top of the server's AuthToken expiry (which is unchanged, and is still the only real gate):
- **No Remember-Me → the session dies with the browser.** Each tab writes a per-tab
  `sessionStorage.coreripperTabAlive` marker; every live tab stamps a shared
  `localStorage.coreripperHeartbeat` every 5s. A page load with **no** tab marker means a tab that
  hasn't run the keeper yet  which is *either* a reopened browser *or* just a second tab  so the
  heartbeat is what disambiguates: only if it's older than `TAB_GRACE_MS` did every tab really go
  away, and only then is the session revoked. Don't shrink that grace to a few seconds: background
  tabs get their timers throttled to roughly one tick a minute, so a short grace would log out a
  user who merely opened a second tab. A session **with** a refresh token skips the check entirely
   surviving the restart is exactly what the checkbox promises.
- **30-minute idle timeout** (`IDLE_LIMIT_MS`), warned at 2 minutes (`IDLE_WARN_MS`) by a modal the
  snippet builds on demand. `coreripperLastActivity` lives in localStorage so **every tab shares
  one clock** and they all time out together. Two things that look like bugs but aren't: a page
  load counts as activity (this is what stops a remembered session from idling out on the hours the
  browser spent closed  the heartbeat is liveness only and deliberately never counts as activity);
  and while the warning is up, activity listeners are suspended via the `warned` flag, so a stray
  mousemove can't silently dismiss it  the user must click "Stay signed in". Activity writes are
  throttled to one per 10s.
Both paths end at `endSession(reason)`, which revokes server-side, sets `coreripperSessionEnded`
(so other open tabs follow themselves out on their next tick) and redirects to `login.html?reason=`.
`LOGIN_URL` is **baked per page by the sweep script** from the file's own directory depth  root
pages get `login.html`, the six subdirs get `../login.html`  since a `<head>` snippet can't infer
the site root from `location.pathname`. login.html renders the reason as a neutral (not error)
notice in its existing `#loginError` banner and strips the query param via `history.replaceState`.

### The network-tool dispatcher pattern
`GET /api/toolbox/?tool=<key>&target=<x>` → `network_tools/views.py::network_toolbox_view`, a
single big `if/elif` over the `tool` key that delegates to `run_tool_internal()` (a plain-dict
version of the same logic, reused by Celery monitors and the Security Grade composite scan).
**The frontend's `tool=` string must exactly match the backend `elif tool == "..."` string** 
this has broken things multiple times. Any tool-picker UI should read `tool_key` off the
`core.Tool` registry, never hardcode a second list.

**`network_tools` is otherwise a models-less dispatcher-only app  the Scam Detector is the one
deliberate exception (2026-08-04).** Its regex rules and shortener-domain list live in DB models
(`ScamRule`, `ScamShortener`) instead of hardcoded Python, read through `scam_detector.py`'s own
5-min cache with the original hardcoded list kept as an in-process fallback if the DB is ever
unreachable. A weekly Celery Beat task (`network_tools.tasks.update_scam_patterns`) asks the free
AI model for new rules based on emerging scam patterns and writes them straight in (`source="ai"`),
logged per-run in `ScamUpdateLog`; a second weekly task (`fetch_breach_alerts`) mirrors HIBP's
public breach list into `BreachAlert` so the Password Breach Checker page can show recent-breach
context (the actual per-password check already lived client-side against HIBP's live k-anonymity
API and needed no change). Admin CRUD for rules/shorteners is `network_tools/admin_views.py`
(`@superuser_required`, same decorator source as every other admin-only view  it lives in
`accounts.decorators`, not `accounts.middleware`, despite the name suggesting otherwise).

### Access tiers (Guest / Free / paid)
`core.Tool.tier` (`local`/`api`) + `tool_key` drive tool gating. `accounts/permissions.py`
(`get_access_tier`, `get_tool_tier`) and `accounts/trial.py` (guest 3-op trial, IP-keyed;
free-tier daily quota) implement it. AI tools are gated via `@premium_required` plus, for the
free Groq/Gemini models, `core/quota.py`'s `$`-spend ceiling (`check_user_quota` per-user,
`check_global_budget` site-wide)  a spend cap, not a call-count cap.

**Locked tool cards (frontend) vs. redacted responses (backend) are two different mechanisms
for two different situations.** `ai_tools.html`'s premium tool cards stay fully visible for SEO
(A7 of the monetization plan) and only intercept the click into an upgrade modal when
`!user.is_premium`  the real gate is still `@premium_required` on the destination tool's own
endpoint, so the frontend lock is presentation only. Security Grade is different: it's a
free/guest-accessible tool where only the *depth* of the response is gated, so
`network_toolbox_view` itself strips `result["findings"]` down to just `grade`/`score`/`locked:
true` for non-premium `access_tier` before the JSON ever reaches the browser  a determined user
reading the network tab still can't see the report body. Don't reach for the CSS-blur pattern
where the real fix is a server-side redaction, and vice versa.

`accounts.Subscription` was reworked from a Free/Premium boolean into four paid tiers
(`plan`: free|lite|standard|pro; legacy `"premium"` maps to pro) with an explicit lifecycle:
`status` (active|trialing|cancelled|expired), `current_period_start/end`, `cancel_at_period_end`,
`renewal_state` (not_due|awaiting_payment|grace). **`is_premium` is now a back-compat shim**
(`status in (active,trialing) and plan != "free"`) so every existing gate kept working unchanged;
it lazy-expires **trials only**  paid expiry runs through the `credits` beat pipeline because of
the 3-day grace window, so never expect a lazy read to lapse a paid sub. `expires_at` is kept and
dual-written with `current_period_end` during the transition. `activate_subscription(user, days,
tier)` (aliased `activate_premium` for old call sites) stacks the period and refreshes the tier's
monthly credit grant.

### Plan-tier entitlements (`accounts/entitlements.py`)  what each tier actually gets
`is_premium` answers "has any paid tier", which is **not** the same question as "is entitled to
this specific feature". Until this module existed, every gate in the codebase was that binary
(`@premium_required`, `get_access_tier` → guest|free|premium), so a $0.99 Lite subscriber got
byte-identical service to a $3.00 Pro subscriber  the monthly credit grant was the only
tier-aware entitlement, silently contradicting pricing.html's compare-plans matrix.
`ENTITLEMENTS` is now the single source of truth, one row per plan mirroring that table:
- `get_plan(user)` reads **through `is_premium`**, so an expired/cancelled sub (or a lazily
  expired trial) returns `"free"` rather than a stale paid plan string. Never read
  `subscription.plan` directly to make an access decision.
- `@requires_plan("standard")` mirrors `@premium_required`'s contract exactly (401 logged-out /
  402 under-entitled / same `upgrade_url`) plus `required_plan`+`current_plan`, so existing
  frontend error handling keeps working. `@premium_required` is still correct wherever the real
  rule is "any paid tier"  Lite is the lowest, e.g. Workbench/dashboard, Generate Fix.
- `redact_security_grade(result, depth)` grades the report body by severity
  (teaser → basic=alerts → detailed=+warnings → advanced=everything) and reports
  `findings_hidden` honestly instead of implying the report is complete.
- `entitlements_json()` rides on `/api/accounts/me/` and `/api/accounts/billing/` so frontend
  pages render caps from the server rather than hardcoding per-plan numbers page by page.
Currently wired: Website Monitoring is Standard+ (`@requires_plan("standard")` on all four
`monitors/views.py` endpoints) with a per-tier active-monitor cap (Standard 3 / Pro 10);
Security Grade depth; the AI-Crawler Checker's per-plan cap.

Four pricing-page rows are deliberately **not** modelled because nothing can enforce them yet
(documented in the module docstring): "Email Deliverability Wizard" (no such tool exists  the
shipped spf/dmarc/dkim checks are free local tools), "Priority processing" (no job queue),
"Ad-free" (no ad script exists anywhere yet), "Early access" (no preview mechanism). Don't
invent a gate for those  either fix the marketing copy or build the feature.

Per-tool periodic caps (currently only the AI-Crawler Checker: 3/week Free, 30/mo Lite, 100/mo
Standard, 20/hr Pro fair-use) use `accounts/trial.py`'s `check_and_increment_tool_quota`, the
same Redis-cache counter pattern as the guest trial and free daily quota  the period bucket is
embedded in the cache key, so a stale entry can never be read in the next period.

### The credit engine (`credits` app)
Claude token consumption is metered as **credits** (1 credit = 250 tokens; `TOKENS_PER_CREDIT`,
`MIN_CREDIT_CHARGE`, `TIER_MONTHLY_CREDITS`, `MAX_OUTPUT_TOKENS` all in `settings.py`). Groq and
Gemini are always free; only Claude touches the wallet. **All AI now flows through one entry
point**, `credits/services.py::run_ai(user, operation, system, user_msg, model)`: the free path
delegates to `core.llm.get_completion` (unchanged cache + Groq→Gemini fallback); the Claude path
does estimate → pre-check balance (zero balance raises `InsufficientCredits`, surfaced as a
`402` with a pack CTA  the API is never called) → `core.llm.claude_complete` (Anthropic Messages
API via plain `requests`, `thinking:disabled` for predictable cost, prompt-cached system block,
no fallback/no response-cache) → charge actual tokens via `CreditWallet.charge_actual` (clamps at
zero, never negative) → ledger + `AIUsageRecord` in one transaction. `news_draft` passes
`user=None`, which forces a free model. `_run_completion` (core/dashboard views) runs the `$`-quota
check for free models only. **When adding an AI tool, route it through `run_ai`, add its key to
`MAX_OUTPUT_TOKENS`, and let the wallet gate it  don't call `get_completion`/`claude_complete`
directly.**

**The Claude path itself has a second, independent gate: the `claude_ai` feature flag (2026-07-30),
seeded OFF because the Anthropic API account isn't funded yet.** Unlike every other `FeatureFlag`
(which fail *open* on a missing row and only gate a URL prefix via `core.middleware`'s
`PREFIX_FLAGS`), `claude_ai` fails *closed* (`FLAG_DEFAULTS = {"claude_ai": False}`) and isn't a
prefix at all  it gates a *model choice*, not an endpoint, since the three AI-tool endpoints and
the Workbench must keep serving Groq/Gemini while Claude is off. `credits.services.claude_enabled()`
(backed by `core.middleware.flag_enabled()`) is checked inside `run_ai`'s Claude branch *before* the
wallet, so a zero-balance user gets `ClaudeUnavailable` ("still being worked on"), not a
misleading "buy credits" pitch; `resolve_model()` also silently downgrades a *stale saved*
`preferred_model="claude"` to groq (an *explicit* per-request `model="claude"` is left alone so the
caller gets an honest error). The same flag gates `PATCH /api/accounts/profile/`
(`preferred_model=claude` rejected while off) and `payments` credit-pack checkout (packs only buy
Claude, so selling one while it's off would be selling nothing  subscriptions are unaffected).
An unauthenticated `GET /api/features/` exposes only this one flag (`PUBLIC_FLAGS`) so static pages
can greytext the Sonnet-5 option instead of offering a click that only 503s; the swept model
switcher on `dashboard.html` and the three ai-tools pages reads it before first render. Flipping
the switch in the Engine Room's Feature Switches tab (self-heals into that generic list, no
separate admin UI needed) is the *entire* go-live step once credits are funded  no deploy, no code
change.

**User-facing display names differ from the internal routing values (2026-07-29).** Every backend
field and internal identifier stays `groq`/`gemini`/`claude` unchanged (`Profile.preferred_model`,
`AIUsageRecord.model`, the `provider` field `run_ai` returns, `data-model="..."` attributes)  only
the frontend's rendered text was rebranded: the free tier displays as **"Livia"**, the paid tier as
**"Sonnet-5"**. The old three-way Groq/Gemini Flash/Claude picker on the three ai-tools pages
(`feedback_tutor.html`/`quiz_generator.html`/`coding_helper.html`) and `dashboard.html`'s Workbench
is now two options only  the Gemini button was dropped from the UI (not from the backend) because
`core.llm.get_completion` already silently falls back Groq→Gemini regardless of which one a user
"selects", so a separate Gemini button never did anything different from Groq; selecting it still
submits `preferred_model: "groq"`. Don't reintroduce a visible Gemini option without first checking
whether `get_completion` still ignores the preference.

Wallet invariants: `CreditWallet` holds `subscription_balance` (resets each cycle) + a cached
`pack_balance`; per-purchase truth lives in `PackCreditLot` (packs expire **12 months** after
purchase  `PACK_CREDIT_LIFETIME_DAYS`, a deliberate override of the monetization doc's "never
expire"). `CreditLedger` is append-only (a `save()` on an existing row raises); **every wallet
mutation writes its ledger row(s) in the same transaction under a row lock**, so
`manage.py reconcile_credit_wallets [--fix]` can rebuild wallets from the ledger and must always
report zero drift. Five daily `credits/tasks.py` beat jobs (registered by data migration, 02:00–
02:40 UTC) run the lifecycle: `expire_trials`, `request_renewals`, `refresh_subscription_credits`,
`expire_unrenewed` (grace then expiry, pack credits always survive), `expire_pack_credits`.

**Frontend credit UI** (Phase 2 of the monetization plan, built on top of the Phase 1 engine
above): a shared `window.CoreRipperCredits` JS module (`init()`/`loadHistory()`, reading only
`GET /api/credits/wallet/` + `/history/`  it never writes) backs the header credit-meter chip
(normal/low-`<25`/zero states, subscription-vs-pack breakdown, inline usage history), copied via
the same sweep-script pattern into every page carrying the nav auth dropdown. The three
Claude-gated tool pages (`ai-tools/feedback_tutor.html`, `quiz_generator.html`,
`coding_helper.html`) each carry a Groq/Gemini/Claude model switcher that persists the choice via
`PATCH /api/accounts/profile/` (`{"preferred_model": ...}`, validated against
`Profile.MODEL_CHOICES`) and reads back `user.profile.preferred_model` from `/api/accounts/me/` 
`resolve_model()` in `credits/services.py` is what actually applies that preference server-side.
Zero-balance + Claude selected disables the submit button with a "Get 250 for $0.99" inline CTA
rather than letting the call round-trip into a 402.

`dashboard.html`'s Workbench (2026-07-25) carries a two-option variant of the same switcher
(`renderModelSwitcher()`, in the AI Assistant panel header)  Groq (default, free) / Claude
(premium, spends credits), same `PATCH /api/accounts/profile/` persistence and `/me` read-back.
It's a single saved preference, not per-feature: Generate Fix (`dashboard/fix/`) and Project
Report (`dashboard/projects/<id>/report/`) both go through `core.views._run_completion` exactly
like the Assistant does, and all three already accept an optional `model` request field that
falls back to `Profile.preferred_model` server-side (`credits.services.resolve_model`) when
omitted  so flipping the one Workbench switch governs all three without any extra plumbing on
the other two call sites. No hard submit-block on zero balance here (unlike the ai-tools pages)
 the existing 402/503 error paths already surface `res.data.message` inline (in the assistant
chat thread, or a toast for Fix/Report), so the friendly message just reaches the user through
each feature's own existing error handling.

### The Workbench's client-state model (`dashboard.html`)
The Workbench is the one page with substantial state that has **no server-side row**: the unsaved
results stream, in-flight/awaiting-save batches, the tool selection, the target field, and the
assistant thread. Until 2026-07-25 all of it lived only in the page's `state` object, so leaving
the page silently destroyed it. It is now snapshotted to `localStorage` under
`coreripperWorkbench:<PERSIST_VERSION>:<user id>`  debounced at the end of every `render()`,
flushed on `pagehide`/`visibilitychange`, and restored inside `init()` **before the first real
render** so the page paints into the saved workspace rather than flashing an empty one. Things
that are load-bearing, not incidental:
- **Keyed on the account id and only restored after `/api/accounts/me/` succeeds**, so two
  accounts sharing a browser can never see each other's work. Bump `PERSIST_VERSION` to discard
  an older shape instead of writing a migration.
- **`nextId` is advanced past every restored card/batch id on restore**, or newly created cards
  collide with restored ones and the `state.stream.find(...)` lookups hit the wrong row.
- **A batch tool left `running` is restored as `failed`**, not `running`  its request died with
  the old page, so a spinner would never resolve.
- Quota-safe by design: the stream is capped (`PERSIST_MAX_CARDS`) and a failed write retries
  without the heavy `raw` result blobs rather than losing the light state too. Snapshots older
  than `PERSIST_MAX_AGE_MS`, and other users' snapshots, are pruned on load.

**The header chip is server-sourced, not a session tally.** It reads today's `AIUsageRecord` rows
from `GET /api/credits/history/` (`loadAiUsage()`), because `run_ai` writes one row per AI call
for free *and* paid models alike  so the count survives a reload. It was a bare in-memory
`sessionCredits++` counter that reset to zero on every page load, which read to users as "my
credits were refunded". `recordAiCall(res.data)` only bumps it optimistically for immediate
feedback; the server is authoritative on the next load. The history endpoint caps at 50 rows, so
a day that fills the cap renders `50+` rather than under-reporting.

**The AI Assistant is a floating window, not a drawer.** It was a fixed full-height right-edge
panel that permanently covered the results stream and the monitoring rail. It's now dragged by
its title bar, resized from the corner, and rolled up to just its title bar, with geometry in
`state.assistantWin` (persisted with everything else). `clampAssistantWin()` runs on every
render *and* on `window.resize`  a stored position from a larger viewport would otherwise put
the title bar off-screen, and the title bar is the only way to move the window back. Below 640px
the stored geometry is ignored entirely and CSS pins it as a bottom sheet with drag disabled.

### WhatsApp alerting (`monitors` app)
Monitor alerts can go out over WhatsApp in addition to email, but delivery depends on an external
process this repo doesn't control: `~/Documents/project-Octavian/whatsapp_bot.js`, a separate
Node/`whatsapp-web.js` process holding a live WhatsApp Web session, exposing a localhost-only
`POST /send` (added to that file specifically for this feature). Because that process can be down,
unlinked, or simply not deployed on a given host, the whole subsystem is built around one rule:
**never claim a delivery that didn't happen.**
- `monitors/whatsapp.py` is the single place that talks to the bot, reading `WHATSAPP_BOT_URL`
  (settings.py, default `http://127.0.0.1:3001`  the earlier hardcoded literal in tasks.py was
  wrong for anything but this box). `probe_status()` distinguishes "bot process down" (connection
  error) from "bot up but WhatsApp session not linked" (`503`) from "ready" (`400`, since posting
  an empty body reaches payload validation only once `clientReady` is true)  no message is sent
  by the probe itself, cached ~60s via `GET /api/monitors/whatsapp/status/`.
- The dashboard's add-monitor form (`dashboard.html`) gates the "WhatsApp me" checkbox on that
  probe and shows the real reason inline when it's off, plus a "Send test message" button
  (`POST /api/monitors/whatsapp/test/`, rate-limited 5/hr/user like `payments/views.py`'s charge
  brake) that sends one real message synchronously so a user can confirm the channel works before
  trusting it with an outage alert. The checkbox is disabled only while *unticked and unavailable*
   an already-ticked box must stay clickable even if the channel goes down after the fact, or the
  user can never turn it back off.
- `monitors/tasks.py::send_whatsapp_alert` writes the real outcome to `AlertLog.whatsapp_error`
  (migration `0004`) on every failure instead of only logging it, and the dashboard's alert history
  renders "WhatsApp delivered" / "WhatsApp not delivered  \<reason\>" per alert 
  `whatsapp_attempted` is derived from that row's own `sent_whatsapp`/`whatsapp_error`, not the
  monitor's current `alert_whatsapp` flag, so toggling the channel off later doesn't retroactively
  relabel history.
- Getting the bot itself running on a fresh box needs four independent things, none of them a
  code fix inside this repo: `node_modules` (the bot file's `require`s resolve from its own
  directory, so the deps living in `project-Octavian/backend/node_modules` need a symlink at the
  bot's own level, not a reinstall), a real Chrome/Chromium `executablePath` (`CHROME_PATH` env or
  the `google-chrome-stable` fallback  the file's original `chromium-browser` path doesn't exist
  on this box), avoiding the stale June copy at `/home/project-Octavian` (no `/send` route),  and a
  live QR scan (WhatsApp  Settings  Linked devices) since nothing can automate linking a session.
  It's started by hand, same as Celery worker/beat  no systemd unit exists for it either.

### Feature flags (real kill switches)
`core.FeatureFlag` + `core.middleware.FeatureFlagMiddleware` map `/api/...` path prefixes to a
flag key; a disabled flag returns a real `503 feature_disabled`. Superusers always bypass their
own kill switches (so a feature stays testable while switched off for everyone else), and
admin/auth endpoints are deliberately never mapped so a superuser can't lock themselves out.
Flag state is cached ~5s and invalidated on toggle. `claude_ai` is the one exception to this
whole shape  it gates a model choice rather than a path prefix, fails closed instead of open,
and is partly public (`GET /api/features/`); see "The credit engine" above for the full mechanics.

**The flag cache is a latency optimisation, not a hard dependency (fixed 2026-07-30).**
`_load_flags()` used to call `cache.get()`/`cache.set()` unguarded; since this middleware runs on
*every* `/api/` request, a Redis outage propagated into a 500 on the entire API  not just flagged
endpoints, everything, because the middleware sits ahead of the view. A real production outage hit
exactly this (Redis down → every endpoint 500d, read by the user as "the whole site is broken").
`_load_flags()` now wraps the cache read/write in `try/except` and falls back to reading
`FeatureFlag` straight from the DB on any cache error, logging a warning rather than raising.
`FLAG_DEFAULTS` (i.e. `claude_ai` failing closed) still applies on that fallback path, so a cache
outage can never accidentally turn Claude spending on. This is the pattern to follow anywhere else
a cache is used as a speed-up: a cache backend being down should degrade the one feature it backs,
never take down request handling that doesn't strictly need it.

### Cookie consent
The site sets exactly one first-party cookie itself: `cr_consent` (JSON-encoded, versioned,
12-month expiry), written by a `window.CoreRipperConsent` JS module swept into all ~94 frontend
pages the same way as the credit meter (anchored on the universal `<body>`/`</head>` tags, not
the nav-dropdown pattern, since the banner must show for guests too). Everything else  login,
subscription/tier state  is a bearer token in `localStorage`, never a cookie, so there's no
`{% if %}` template-tag gating anywhere (this is a static-HTML site with no server-rendered
frontend templates); ad/analytics scripts, once any exist, must check
`CoreRipperConsent.has('advertising'|'analytics')` in JS before inserting themselves into the
DOM. No ad or analytics script exists yet, so today the module only records the user's choice.
`cookie-policy.html` documents every cookie by name/purpose/lifetime and must be kept current if
a new one is ever added. Django's own `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` are tied to
`not DEBUG` (settings.py) rather than hardcoded `True`  hardcoding it would silently break
admin login on the plain-HTTP dev server, since browsers drop `Secure` cookies over non-HTTPS.

### Content-moderation apps follow one shared shape
`news` and `hardware` (and to a lesser extent `blog`) each have their own parallel  not
shared/generic-FK'd  set of models: an `*Article`/`*Draft` model with `status`
(pending/published/rejected) and a `publish()`/`reject()` method that stamps `published_at`
once and logs a timeline entry, plus `*ArticleSource` and `*ArticleUpdate` child models (real
sources + a real "Knowledge Timeline"/"What's New" feed). This is a deliberate pattern
duplicated per app (not a shared abstract base) so one app's migrations never touch another's
live data  mirror the existing shape (e.g. `news/models.py`) when extending or adding a
similar content type rather than inventing a new one.

**`news.NewsDraft` has a fourth status, `archived`** (2026-07-29, see "In-flight work" below for
the full weekly-wrap-up feature this supports): `archive()` mirrors `publish()`'s "stamp once,
log a timeline entry" shape, setting `archived_at` and logging an `ArticleUpdate(kind="archived")`.
**Archiving is not deleting**  an archived row's own detail page (`news_detail_view`) keeps
serving it (`status__in=["published", "archived"]`), only the main feed/related-articles queries
(hardcoded to `status="published"`) stop surfacing it. This exists specifically so a scheduled
content-pruning job never tanks SEO by 404ing previously-indexed article URLs; if you add a
similar "keep the list fresh" mechanism to `hardware`/`blog`, archive, don't delete.

**Approval happens in the Engine Room (`frontend/admin.html`), not Django `/admin/`.** Both
`news` and `hardware` have a superuser-only moderation tab there (Pending/Published/Rejected
filter, per-card Approve & Publish / Reject / + Log Update), each driven by that app's
`api/<app>/admin/articles/` GET + `/<id>/` PATCH-status + `/<id>/updates/` POST endpoints
(`<app>/admin_views.py`, gated by `@superuser_required`). The two tabs are near-identical JS;
when mirroring News' tab for a new content type, note the per-app JSON differs — `hardware`
articles have **no `trending_score`** and no top-level `source_url`/`source_name` (source is in a
`sources[]` array; use `sources.find(s => s.is_primary)`). Give each tab's status-filter buttons
a **distinct CSS class** (e.g. `hw-filter-btn` vs `news-filter-btn`): the filter click-handlers
do a global `querySelectorAll('.<class>').forEach(remove 'active')`, so a shared class lets one
tab's filter clobber another's active state. `blog` still uses a different (full-editor) admin
panel, not this moderation shape.

**Moderation cards show the resolved image and let an admin override it (2026-07-30).** Both
tabs render the same `image` field the public feed already serves (`resolved_article_image()`,
see "The Intelligent content engine" below) as a thumbnail + credit line, with a "Change picture"
button. That button opens a shared picker (`openImagePicker(app, category, onSelect)` in
`admin.html`) backed by a new read-only `GET /api/core/admin/category-images/?app=&category=`
(`core/image_admin_views.py`, `staff_required` since blog's editor needs it too, not just
news/hardware's superuser tabs) that lists the real Commons pool (`core.CategoryImage`) for that
category, plus an "Upload your own" option that reuses blog's existing generic
`POST /api/blog/admin/upload-image/` endpoint (it's plain file storage, not blog-specific logic).
Picking an image PATCHes a new `api/<app>/admin/.../<id>/image/` endpoint
(`admin_news_image_view`/`admin_hardware_article_image_view`), which writes straight into the
row's own `IntelImageMixin` fields via `apply_image_result()` — the same slot the AI image
pipeline uses, so `resolved_article_image()` picks up a manual choice with no other code change.
Deliberately no lock: a later auto-editor pass can still replace a manual pick. Blog needed no new
endpoint — its cover image is a plain `cover_image_url` field already saved by the existing
post-edit `PUT`, so the editor's picker just writes the chosen URL into that field; an empty pool
for a category (blog has none today, `CategoryImage.APP_CHOICES` only lists news/hardware) is an
honest "no pool photos yet, upload instead" message, not a crash.

### Hardware Hub: multi-provider spec sync + AI Knowledge (`hardware` app)
Phase 1 of the "explain hardware in plain English" vision (full spec: months of work; this is
the foundation). **The device-vs-device comparison engine that used to sit alongside this was
removed 2026-07-29** (see "In-flight work" below)  don't resurrect `hardware/comparison.py`,
`HardwareComparisonVerdict`, `compare.html`, or the per-type spec list/detail endpoints
(`/api/hardware/cpus/` etc.) without checking that note first; `TRACKED_SPEC_FIELDS` in
`hardware/spec_fields.py` (née `COMPARISON_SPECS`) is the one piece of that code that survived,
since `hardware/ai_knowledge.py` still needs it for spec-hash tracking. `CPU`/`GPU`/`Laptop`/
`MobileSoC` are populated two ways, and both can coexist on the same row:
- **Provider sync** (`manage.py sync_hardware_specs`, primary path): `hardware/providers/manager.py::sync_type()`
  calls every *live* provider's `fetch()`, merges records per device, and for each field picks
  the value from the highest-priority live provider (`field_priority.py`'s `(type_key, field) →
  [provider_keys]` table). **Only `wikidata` is live today**  GSMArena/Notebookcheck/PassMark
  have no public API and are declared-but-deferred in that same table, exactly like
  VideoCardz/IGN in `providers/sources.py`; don't scrape them in to "finish" the table, add a
  real provider class instead. A synced row's `external_id` is set (e.g. a Wikidata QID); a
  hand-curated row's is `None`  sync matches on `external_id` first, then `name`+`manufacturer`,
  so a manual row is never duplicated once a provider also knows about it. Wikidata's real-world
  coverage skews toward older/historical CPUs/GPUs, not exhaustive current-gen SKUs (verified: a
  post-2019 release-date filter returns zero rows for CPU/GPU) — `manage.py seed_hardware_specs`
  is the practical source for current, buying-guide-relevant devices, not a stopgap.
  **Phone/tablet GPUs never belong in the `GPU` table.** Wikidata models Adreno/Mali/PowerVR/
  Apple-GPU/Xclipse as *subclasses* of "graphics processing unit" (Q183484), so the GPU SPARQL
  query's `wdt:P31/wdt:P279*` traversal pulls them in alongside real discrete cards — which is
  wrong: a user can't meaningfully compare an Adreno against a GeForce. `wikidata_provider.py`
  filters them out by name prefix (`_is_mobile_gpu` / `_MOBILE_GPU_NAME_PREFIXES`), not by
  manufacturer (Wikidata's manufacturer label for these is unreliable — one came back "TSMC").
  Mobile GPUs live only as the plain-text `MobileSoC.gpu` field (e.g. "Adreno 750" on the
  Snapdragon 8 Gen 3 row), never as a standalone spec row. If you add a second spec provider,
  apply the same exclusion to its GPU output.
- Every field change a sync pass makes is logged to `HardwareSpecChange` (old/new value, source
  url) and attributed per-field in `HardwareFieldSource` (which provider supplied it, and when)
   this is what would let a second provider's "Display" beat Wikidata's without guessing later.
  **Curated fields are never provider-written**: `performance_score`/`value_score`/
  `efficiency_score`/`portability_score` (0-100, nullable) are CoreRipper's own scoring, set by
  an admin/seed data, and `sync_type()` skips them entirely.
- **Images**: `HardwareDeviceImage` (per-device, multiple `image_type`s: main/gallery/front/
  back/.../logo, deduped by a sha256 of the URL) is additive to the older, still-live
  `core.CategoryImage` (per-*category* pool)  `hardware/device_images.py::get_device_images()`
  falls back to the category pool only when a device has zero rows of its own. No
  GSMArena/manufacturer-image scraping; only Wikimedia Commons hotlinks with real credit/license.
- **AI Knowledge** (`hardware/ai_knowledge.py`): `HardwareAIProfile` is structured, not prose 
  `best_for`/`strengths`/`trade_offs` tag lists plus `expected_lifespan_years`/
  `recommended_ram_gb`/`recommended_ssd_gb` and a short `verdict_text`. Generated via
  `run_ai(user=None, operation="hardware_knowledge", ...)` (free-path only, same pattern as
  `news_draft`), and **only regenerated when `source_spec_hash` (a hash of the tracked spec
  fields) changes**  never on a timer, never on a no-op sync. `status` (draft/reviewed/
  published, defaults to published) lets an admin hide/edit one without a public moderation
  queue; this is a per-device profile (no pairwise "how do these two compare" question exists
  anymore  see the comparison-removal note above).
- Beat cadence (migration `hardware/migrations/0004`): mobile SoCs daily, laptops/GPUs weekly,
  CPUs monthly, all via one shared `hardware.tasks.sync_hardware_spec_type(type_key)` task 
  same hand-started-worker/beat caveat as the rest of the project (see Commands above).
- **Not built yet** (explicit follow-ons, not gaps to "fix"): glossary, buying-guide wizard,
  laptop finder, upgrade advisor, business-laptop refurb DB, per-type catalog/detail pages, a
  second live spec provider, a formula-based auto-scorer. Device-vs-device comparison was
  actually built and then deliberately removed (2026-07-29)  see "In-flight work" below before
  rebuilding it.

### Content ingestion: provider-based, honesty-first
`news` and `hardware` both ingest from real RSS/API sources via a small provider abstraction
(`hardware/providers/base.py`'s `HardwareSourceProvider`, `hardware/providers/rss_provider.py`'s
generic `RSSFeedProvider` reused across every wired-in publication). **Never fabricate an
ingestion source or its output**  an unverified or inaccessible source is left commented-out
and documented (see `hardware/providers/sources.py`'s own docstring for two real examples:
IGN's feed is reachable but too low-relevance for hardware, VideoCardz is blocked by Cloudflare)
rather than faked. Everything ingested lands as `status="pending"`; nothing is public until a
human reviews and publishes it  that gate is never skipped, including in test/demo scripts.
Five sources are wired live (`ALL_SOURCES`): Tom's Hardware, TechPowerUp, GSMArena, PC Gamer,
Rock Paper Shotgun (added 2026-08-04 as a second gaming source  PC Gamer's RSS `<summary>` is
a stylistic one-liner, not real article text, so RPS carries the weight for Gaming-category
article quality). `RSSFeedProvider` drops any entry whose excerpt is under `MIN_EXCERPT_CHARS`
(50) characters  a source-quality gate, not a truncation  and runs `html.unescape()` on the
stripped summary before storing it.

`hardware/providers/` holds a **second, parallel provider abstraction** for structured spec
data (not articles) — `spec_base.py`'s `HardwareSpecProvider`, `wikidata_provider.py`,
`field_priority.py`, `manager.py`. Don't confuse the two: `base.py`/`sources.py`/`registry.py`
feed `HardwareArticle` via `tasks.py::aggregate_hardware_content`; `spec_base.py`/
`wikidata_provider.py`/`manager.py` feed `CPU`/`GPU`/`Laptop`/`MobileSoC` via
`tasks.py::sync_hardware_spec_type`. Same honesty-first rule applies to both  see "Hardware Hub"
below for the spec-provider side.

### Scheduled tasks
Celery Beat schedules are registered via Django **data migrations** creating
`django_celery_beat.CrontabSchedule` + `PeriodicTask` rows (e.g.
`news/migrations/0002_register_periodic_task.py`), not an actual crontab entry or
`settings.CELERY_BEAT_SCHEDULE` dict. A task is only wrapped in `@shared_task` and scheduled
once there's something real for it to do  an empty-registry task stays a plain callable so a
periodic run doesn't clutter the beat log forever ingesting nothing.

### LLM usage
`core/llm.py` holds the wire-level provider calls: `get_completion()` (provider-agnostic, primary
Groq + fallback Gemini, prompt cache) for the free models, and `claude_complete()` for the paid
Anthropic path  both raise a catchable `LLMNotConfigured` / `LLMRequestFailed` rather than
crashing when unconfigured. **Call sites do not call these directly**  they go through
`credits.services.run_ai` (see "The credit engine" above), which owns model routing and the credit
metering. `core/llm.py` owns provider HTTP; `credits` owns orchestration/metering.

### The Intelligent content engine (`core/intel/`)
Two capabilities built on a **dedicated Gemini key** (`INTEL_gen_news_gemini`), kept entirely
separate from `core.llm`/`credits.run_ai`: this is internal editorial work and must never touch
the customer credit wallet or the customer-facing AI budget.
- **Image pipeline** (`gemini.py` → `image_search.py` → `pipeline.py`): analyse an article into
  structured metadata (manufacturer/product/device_type/targeted queries/avoid-keywords/
  confidence) → build queries → retrieve candidates → heuristic score + confidence gate → pick,
  or return None so the row keeps its per-category pool fallback. Storage is an **abstract
  `IntelImageMixin`** (`models_mixin.py`) mixed into `NewsDraft`, `HardwareArticle`, blog `Post`
  (own migration per app  never a shared table). Serve-time resolution goes through
  `core.intel.resolved_article_image(obj, app, category)` (views prefer the stored intel image,
  else the legacy pool). The returned image dict is the **same shape** as the old
  `get_article_image`, so no frontend change was needed  news/hardware/blog cards render the
  accurate image + credit unchanged. `hardware/device_images.py::ensure_device_image`/
  `get_device_images` (lazy, one-time per device, cached miss marker) is unused since the
  2026-07-29 comparison-feature removal took its only caller with it  don't wire it back up
  without confirming there's a real per-device page for it to serve again.
- **Auto-editor** (`auto_editor.py::run_auto_edit(kind)`): scheduled pass over **published** rows
  that re-fetches the source, **hash-gates** on it (`intel_source_hash`; unchanged source ⇒ cheap
  no-op), regenerates summary/body via `run_ai(user=None)` (free model), refreshes the image + SEO
  description + source URL, and logs a "What's New" `ArticleUpdate`. Changes are **auto-applied to
  live rows and logged**  a deliberate, recorded exception to human-moderation-on-first-publish
  (the user chose this). Blog is the conservative case: body is rewritten **only when
  `Post.auto_managed=True`** (new field, default False, so hand-written seed posts keep their
  prose); otherwise image + SEO only, and no timeline entry (blog has no `ArticleUpdate` model).
  Celery tasks `auto_edit_{news,hardware,blog}` are beat-registered by data migrations, but **no
  longer all daily** since the 2026-07-29 news wrap-up pass (see "In-flight work" below):
  `auto_edit_news` stays daily at 03:00 UTC, `auto_edit_blog` is now **weekly, Monday 03:40 UTC**
  (one day after news' Sunday wrap-up), `auto_edit_hardware` is now **monthly, 1st-of-month 03:20
  UTC** (same hand-started-worker/beat caveat as everything else). Backfill:
  `manage.py backfill_intel_images [--type news|hardware|blog|all] [--limit N] [--force]`.
- **Gemini model gotcha:** this key only serves `gemini-flash-latest`  `gemini-1.5-flash`/
  `2.5-flash` both 404 ("no longer available to new users"). Current flash models spend part of
  the output budget on hidden reasoning and the OpenAI-compat layer **rejects** the
  thinking-disable params (`reasoning_effort`/`extra_body` → 400), so the fix is headroom
  (`max_tokens: 1200`)  too small a cap returns empty content (`finish_reason=length`), not an
  error.
- **Google image search is built but dormant:** the `GoogleImageProvider` (Custom Search JSON API,
  `searchType=image`) needs a Programmable Search Engine id in `GOOGLE_CSE_ID` **on top of** the
  key; with no `cx` it reports unconfigured and the pipeline **auto-falls-back to Wikimedia
  Commons** (honest, CC-licensed, credited). Paste the `cx` into `.env` to switch web image search
  on  no code change. All intel env vars are in `settings.py` + `.env.example`
  (`INTEL_GEMINI_MODEL`, `GOOGLE_CSE_ID`, `INTEL_IMAGE_CONFIDENCE_THRESHOLD`=0.60,
  `INTEL_AUTOEDIT_MIN_AGE_DAYS`/`_MAX_PER_RUN`).

### Payments: Lenco gateway + dual-currency + admin pricing
The payments subsystem is **fully swappable**: `PAYMENT_PROVIDER=stub|lenco|lipila` (env).
Stub is production-grade for testing; Lenco is the live gateway; Lipila is a placeholder.
- **Server-side amounts only.** Client sends `price_id` **or** `pack_id` (exactly one, never
  both); server resolves the amount via the `PlanPrice`/`CreditPackPrice` model. Closes the
  client-controlled-amount hole completely.
- **Two products, one checkout.** `PlanPrice` = recurring subscription; `CreditPackPrice` =
  one-time Claude-credit pack (seeded **active** by `payments/migrations/0006`, since those five
  prices were already advertised publicly). Both carry `display_amount_usd`, so `fx.charge_amount`
  and the whole momo/card/verify/webhook path are shared verbatim  the split is only at
  settlement: `settle_payment` calls `wallet.grant_pack()` (12-month lot, pack-specific receipt)
  for a pack instead of `activate_subscription`, and a `Payment` snapshots `credits_amount` the
  same way it snapshots `amount`. A pack purchase must never touch the subscription, and is
  excluded from `has_active_paid_subscription` so buying credits on a trial can't plan-lock the
  Engine Room. Pack prices are Django-admin-only for now (no Engine Room tab yet).
- **Admin pricing model.** You (the superuser) enter **USD only** in the Engine Room "Pricing"
  tab: label, `display_amount_usd`, period_days. ZMW is computed live via `payments/fx.py`.
- **Dual-currency rates:** `payments/fx.py::get_usd_to_zmw()` hits free keyless market-rate APIs
  (open.er-api.com, frankfurter.app, overridable via `FX_API_URL`), caches an hour, falls back
  to stored `FxRate` rows in the DB, then `FX_FALLBACK_USD_ZMW` env value. Every fetch updates
  the DB so rate snapshots are always available offline; UI shows "today's rate" / "last known
  rate" / "fallback rate" accordingly.
- **Zambian vs international.** Mobile money (Airtel/MTN) charges in ZMW at the live rate only.
  Card method (debit/credit) offers a two-way choice to the customer: "K{zmw} ZMW (Zambian
  cards)" or "${usd} USD (international cards)"  but server enforces the whitelist; client
  choice is always passed and validated. Phone validation is bilateral (JS regex + server regex
  for Zambian numbers: `^(?:\+?260|0)?(9[567]|7[567])\d{7}$`). Zamtel removed per user decision.
- **Settlement is idempotent.** `accounts/subscription_utils.py::settle_payment()` uses atomic
  conditional UPDATE (`pending→paid` filter) so duplicate webhooks or concurrent polls can never
  double-extend a subscription. On success it resolves the tier from `payment.price.plan` and calls
  `activate_subscription(user, period_days, tier)` (which also refreshes that tier's monthly credit
  grant) + `send_payment_receipt(payment)` (email via Gmail SMTP or console backend).
- **Admin plan-lock for paid subscribers.** Users with at least one settled `Payment` get
  `paid_subscriber: true`; superuser cannot change their plan in the Engine Room (409 error)
  until the subscription expires. The lock lifts automatically when `Subscription.is_premium`
  flips false.
- **Webhook resilience without signature docs.** On `POST /api/payments/webhook/lenco/<secret>/`,
  the reference is extracted defensively, then **re-verified via server-side Lenco API call**
  before any settlement. This sidesteps webhook-signature uncertainty. Secret is validated via
  `hmac.compare_digest`; 404 if unset. Unknown refs always 200 (no retry storms).
- **Lenco wiring:** all gateway knowledge is top-of-file constants in `payments/lenco.py`.
  **These were verified 2026-07-29** against the live Lenco API docs (lenco-api.readme.io) and
  two working client libraries (alexasomba/lenco-node, kapansa/lenco-payment-gateway): base URL
  (`https://api.lenco.co/access/v2`), all three paths (`/collections/mobile-money`,
  `/collections/mobile-money/submit-otp`, `/collections/status/{reference}`), operator slugs,
  and the STATUS_MAP vocabulary all match. The verification also **corrected four things in the
  create-momo payload** that had been guessed offline: `PHONE_FORMAT` is now `"international"`
  (MSISDN `2609XXXXXXXX`, not `09...`), the body sends a numeric `amount` (schema declares
  `double`, not a string) and a `country: "zm"` field, and no longer sends a `currency` field
  (not part of Lenco's mobile-money schema — the `Payment` row still snapshots currency, only the
  outbound call changed). Key is read **lazily** from `LENCO_API_KEY` env → blank key = clean 503
  `gateway_not_configured`, server boots fine. Go-live is only: paste the key, set
  `PAYMENT_PROVIDER=lenco`, restart. See the module docstring for a full first-live checklist;
  it still recommends re-confirming on the first real charge in case the API has moved.
- **Rate snapshots, not recomputation.** Every Payment snapshots `amount` + `currency` at charge
  time, never recomputed later. History and receipts are frozen, immune to rate movements.
- **Tests:** `backend/payments/tests.py` runs offline on SQLite (see note below). Rate logic is
  deterministic via `FxTestMixin` (patches live fetch, installs a stored DB rate). 33 tests:
  pricing endpoint hides inactive rows, create-charge rejects client amounts, momo forces ZMW,
  card-USD snapshots exactly USD, rate limits trip on 6th call, settlement is idempotent, admin
  CRUD is superuser-only, plan-lock blocks PATCH with 409, unlock on expiry, plus the
  LencoAdapterOffline suite (`format_phone` normalizes to international MSISDN, unconfigured key
  → 503).

### Production deployment (VPS)
Live at `coreripper.site`, a Contabo VPS (`deploy` user, 4 cores/8GB, plenty of headroom  a slow
site there is not the box being undersized, see the request path below first), app code at
`/srv/coreripper/backend`. Full path a request takes: **Cloudflare (proxy, not Tunnel  no
`cloudflared` process) → nginx (TLS termination, `ssl_certificate`/`ssl_certificate_key` at
`/etc/ssl/cloudflare/`, a Cloudflare Origin cert, not Let's Encrypt) → gunicorn over a Unix
socket → Django**. Static/media are nginx `alias`es straight to `staticfiles/`/`media/`, not
served by gunicorn.
- **Gunicorn is a systemd service (`coreripper-backend.service`), not a hand-started process.**
  It binds `unix:/srv/coreripper/backend/gunicorn.sock`  nginx's `proxy_pass` is hardcoded to that
  exact socket path (see its `location /api/` / `/admin/` blocks), so binding gunicorn to a TCP
  port instead (e.g. `127.0.0.1:8000`, the natural first instinct) leaves nginx unable to find it
  at all: `connect() to unix:/srv/coreripper/backend/gunicorn.sock failed (2: No such file or
  directory)` in `/var/log/nginx/error.log`, surfaced to visitors as a bare Cloudflare-level `502`
  (a distinctive plain-text 16-byte "error code: 502" body, not nginx's own styled HTML 502 page 
  that shape means Cloudflare couldn't even reach nginx/gunicorn, not that gunicorn itself errored).
  `Type=simple` in the unit, not `Type=notify`  plain gunicorn never sends the systemd readiness
  signal that `notify` waits for, so `notify` would eventually time out treating a perfectly healthy
  process as failed. `Restart=always` + `WantedBy=multi-user.target` are load-bearing: this is what
  makes the service survive a crash or a reboot without a human re-running `manage.py runserver` in
  a terminal tab that dies the moment that SSH session closes (see the 2026-07-30 incident below).
- **`CONN_MAX_AGE`/`CONN_HEALTH_CHECKS` are set on `DATABASES["default"]`** (60s, added
  2026-07-30)  without them Django opens a fresh TCP+auth handshake to Postgres on literally every
  request, and this frontend fires many small parallel API calls per page load, so that overhead
  compounds into real, sitewide "everything feels slow" latency rather than one slow endpoint.
- **Redis backs `CACHES`, Celery's broker/backend, and `FeatureFlagMiddleware`** (see "Feature
  flags" above for the outage-fallback behavior). It's a real systemd unit here too
  (`redis-server`), same as local dev.
- A `chown -R deploy:deploy` run at some point (exact origin unclear) touched files well outside
  `/srv/coreripper` and broke two unrelated system services in the same incident:
  `/etc/postgresql/<ver>/main` (Postgres's `pg_ctlcluster` refuses to start when the config dir's
  owner isn't `root` or the data dir's owner  fix: `chown -R postgres:postgres` on that path) and
  `/etc/ssl/private/ssl-cert-snakeoil.key` + its parent dir (Postgres's default SSL cert, needs to
  stay `root:ssl-cert` mode 640/710  broke with `could not access private key file: Permission
  denied` at Postgres startup). If a `chown` mistake breaks one of these, check the other two as
  well rather than assuming a single fix closes it out; also check the wider tree with
  `find /etc/postgresql /etc/ssl /var/lib/postgresql -not -user postgres -not -user root ...`.

### Images
`core.CategoryImage` stores a small pool of real, CC-licensed Wikimedia Commons photos per
`(app, category)` pair (fetched via `core/commons_images.py`, populated by
`manage.py fetch_category_images`). `core/category_images.py::get_article_image()`
deterministically picks one photo per article (hashed on article id) so a given article always
shows the same photo. Returns `None` on an empty pool  frontend renders an icon fallback, never
a fabricated image, and any real photo shown carries required CC-attribution.

## Known gotchas (already bitten this project more than once)

- **A blank env var is not an absent one  it overrides the code's default.** Most vars are read
  as `os.environ.get("X", "default")`, which returns `""` for a key that's present-but-empty, so
  `X=` in `.env` silently replaces the default with the empty string. Some then crash on parse
  (`int("")`, `Decimal("")` for `FREE_DAILY_OP_LIMIT`, `NEWS_FEED_*`, `PREMIUM_MONTHLY_CAP_USD`,
  `GLOBAL_DAILY_BUDGET_USD`) and some quietly flip behavior (`DJANGO_DEBUG=` is not `"1"`, so it
  turns DEBUG *off*; `ANTHROPIC_BASE_URL=` blanks the API host). Vars that are safe to leave blank
  are read with `or` (`LENCO_*`, `DJANGO_SECRET_KEY`) or treat blank as meaningful (API keys).
  That's why every var with a real default is shipped **commented-out** in `.env`/`.env.example`
   don't "tidy" those into blank assignments.
- **`is_premium` no longer lapses a paid sub on `expires_at`.** It's a shim over `status`; only
  *trials* lazy-expire on read. To lapse a paid subscription in a test/shell you must set
  `status="expired"` (and `plan="free"`)  that's what `expire_unrenewed` does. Setting only
  `expires_at` in the past does nothing (this broke `payments/tests.py::test_admin_plan_lock`).
- **Every bearer-token-authed POST view needs `@csrf_exempt`, or real browser calls 403.**
  Django's CSRF middleware still runs even though auth here is a bearer token, not a session
  cookie  with no session, there's no CSRF cookie to match, so any POST view lacking the
  decorator throws a `403` CSRF page instead of reaching the view (this bit `core/views.py`'s
  three AI-tool endpoints once already; the fix mirrors `dashboard/views.py`'s existing
  docstring rationale). Verify with the Django test `Client` (pass `SERVER_NAME="127.0.0.1"` so
  `ALLOWED_HOSTS` under `DEBUG` accepts it) or the real browser flow  never bare curl, which
  can't distinguish a CSRF 403 from a real one.
- **Nested `<a>` tags break card grids.** A clickable card that itself needs a secondary link
  inside it (e.g. a photo-credit pill) must use a `<span>` with a click handler
  (`event.stopPropagation()` + `window.open(...)`), never an `<a>` nested inside the card's own
  `<a>`  browsers auto-close the outer anchor, silently corrupting the whole list.
- **Browser caching, not code, is often "the bug."** If a verified change "isn't showing up," use
  `_nocache_server.py` for the frontend dev server (plain `http.server` sends no cache headers
  and browsers will serve stale HTML) and hard-refresh before assuming the code is wrong.
- **`preview_click` can race a page-reloading action.** If a click "doesn't work" in a
  browser-preview check, verify the underlying JS directly (`.click()`/`dispatchEvent` via
  `preview_eval`) before concluding it's a real bug. Related: `preview_screenshot` has timed out
  repeatedly on these pages (the always-running logo/pulse animations seem to keep the compositor
  from settling) while `preview_eval`/`preview_inspect` on the same page respond fine  a
  screenshot timeout is not evidence the page is broken, and `preview_inspect` is the better
  check for geometry and computed styles anyway. Note its `boundingBox` is reported in the
  preview's own scaled pixels, so it won't match the element's `style.left`/`top`  compare
  against `style`/`getComputedStyle`, not the box, when verifying exact positioning.
- **On a page whose `render()` replaces `#app.innerHTML` wholesale, a drag/resize gesture must
  not call `render()`.** Rebuilding the innerHTML mid-gesture destroys the node under the cursor
  and the drag dies on the first `pointermove`. The pattern (see `beginAssistantGesture()` in
  `dashboard.html`) is: mutate the element's `style` directly on each move, write the value into
  `state`, and only let the next ordinary `render()` pick it up  never re-render per move. The
  same wholesale-replacement is why an `<input>` in such a page loses focus on every render and
  has to be refocused by hand after any async action that re-renders (`state._refocusAssistant`).
- **A `pagehide`/`visibilitychange` save will silently overwrite a hand-edited localStorage key.**
  On any page that persists state on unload, editing its storage key from the devtools/`preview_eval`
  and then reloading does nothing  the reload fires the unload handler first, which writes the
  live in-memory state back over your edit. To reset such state, drive the page's own UI, or clear
  the key from a context that isn't about to unload that page.
- Setting a `<textarea>`'s `.value` directly wipes its native undo/redo stack  mutate via
  `document.execCommand('insertText', false, text)` after setting the selection range instead.
- A confirmation-modal countdown (or any live state) must live in a dedicated inner `<span>`,
  never a `<button>`'s own `textContent`  reassigning it wholesale deletes any child elements.
- Any file-write feature must land **outside** `/home/clive/Documents/Core` (e.g.
  `~/coreripper-media/`)  VS Code Live Server watches the whole repo by default, and a write
  inside it mid-edit triggers a live-reload that can wipe an open editor.
- **FX rate snapshots are forever.** When a payment is created, `amount` and `currency` are
  snapshotted on the Payment row  they never move, even if the real USD→ZMW rate swings wildly
  later. This is by design: receipts, history, and settlement amounts are immutable. The frontend
  always shows rate metadata honestly ("today's rate", "last known rate", "fallback rate") so
  customers see what they're getting. A new charge always uses today's rate; old payments are
  frozen at their creation moment.
- **A dropdown/popover next to a scrollable or `overflow:hidden` card gets clipped, not just
  overlapped.** Any card-style container (`.s-card`, right-rail panels, etc.) commonly sets
  `overflow:hidden` or `overflow-y:auto`, and a plain `position:absolute` child dropdown gets
  cut off at that ancestor's edge even with a high `z-index`. Fix: render the dropdown as a
  top-level element outside the clipping ancestor (a static sibling in the page body, not
  generated inside a per-render `innerHTML` string), give it `position:fixed`, and position it
  in JS via the trigger's `getBoundingClientRect()` on open (plus reposition on scroll/resize).
  Two follow-on traps once it's detached: outside-click handlers must check
  `!trigger.contains(e.target) && !dropdown.contains(e.target)` (the dropdown is no longer a
  DOM descendant of the trigger), and delegated click handlers scoped to a container like `#app`
  will never fire for clicks inside a dropdown that now lives outside that container  bind a
  dedicated listener on the dropdown itself instead. The site's mobile nav menu (`#crMobileMenu`)
  is itself an `overflow:hidden` container (needed for its slide-down open/close animation), so a
  real `.cr-dd-menu`-style popover placed inside it gets clipped the same way  that's why grouped
  nav items (the Blog/News/Hardware "Discover" entry, last in the desktop `.cr-nav-links` row)
  render as a real dropdown on desktop but as a flat, labeled sub-list under `#crMobileMenu`
  instead of a nested popover.
- **The `.cr-dd-menu`/`.cr-dd-btn`/`.cr-nav-dropdown`/`.cr-dd-item`/`.cr-dd-email`/`.cr-dd-divider`
  rules are page-local CSS, not guaranteed to exist just because the markup uses those classes.**
  Because every page's `<style>` block is copied independently (no shared bundle), it's possible
  for a page to carry the dropdown *markup* (account menu, Discover menu) without ever having
  copied in the *rules* that give it a collapsed default state (`max-height:0; opacity:0;
  pointer-events:none`) — the dropdown then renders permanently expanded inline instead of
  hidden-until-clicked, with no console error to flag it. Found on 73 pages (verified via
  `grep -rlE 'class="[^"]*cr-dd-menu' vs grep -rlE '\.cr-dd-menu\s*\{'` finding markup-without-rule)
  and fixed by inserting the canonical block (copied from `dev_tools.html`) into each; if a new
  page ever shows an always-open dropdown, check for this exact gap before assuming it's a JS bug.
- **The global close-on-outside-tap handler must know every dropdown type's wrapper+button
  classes, or opening that dropdown immediately closes it (2026-08-02).** A single swept
  `document.addEventListener('click', ...)` (added 2026-07-31, inside the `CR_MOBILE` markers on
  all 97 pages) closes any open `.cr-dd-menu.open` when a click lands outside it. The subtlety:
  a dropdown's own trigger button is *outside* the menu element, so the handler re-checks the
  click against a hardcoded list of `(wrapper, button)` selector pairs
  (`open.closest('.cr-nav-dropdown, .wb-user-menu-wrap, .cr-credit-wrap, .cr-nav-content-dd')` →
  `wrap.querySelector('.cr-dd-btn, .wb-user-btn, .cr-credit-chip, .cr-nav-content-btn')`) and
  bails if the button contains the target. If a dropdown's wrapper/button classes are **not** in
  those two lists, the button click is treated as "outside", so the same click that the button's
  own `onclick` used to open the menu bubbles up and this handler closes it — the menu never
  stays open, with no error. This is exactly what hid the **Discover** dropdown on all 96
  non-homepage pages until fixed: its `.cr-nav-content-dd`/`.cr-nav-content-btn` classes were
  missing from the lists (the homepage's Discover is a different `ts-discover` widget the handler
  doesn't match at all, so it kept working, which is the tell). When adding a new site-wide
  dropdown type, add its wrapper+button classes to **both** the click and the `keydown`/Escape
  handler. Verify by *real click* (`btn.click()` or a browser click), never by force-adding
  `.open` in a `preview_eval` — force-adding bypasses the exact handler that causes this bug.
- **Every inline SVG `<defs>` gradient/filter needs a page-unique ID suffix.** The animated
  hexagon logo mark (nav, footer, auth pages, etc.) defines `<linearGradient id="coreGradient-...">`
  per instance  reused IDs (e.g. two copies both called `coreGradient`) silently collide when
  they land in the same DOM, with the second instance rendering the first one's gradient. Always
  suffix by placement (`-nav`, `-footer`, `-auth`, `-wb`) when copying the logo markup into a new
  page or a second location on the same page.
- **`core/category_images.py`'s pool cache is in-process and never invalidated.** `_pool(app,
  category)` caches a `CategoryImage` queryset in a module-level dict keyed only by
  `(app, category)`, for the life of the Django process. Editing `CategoryImage` rows directly
  (deleting/re-running `fetch_category_images`) has **no effect on already-running
  `manage.py runserver`/gunicorn workers** until they restart  if a just-fixed image "isn't
  showing up" after a DB-level fix, restart the backend process before concluding the fix didn't
  work (bit us fixing the mobile_socs/gaming_laptops/desktop_pcs/monitors/motherboards image bugs
  below).
- **Wikimedia Commons full-text search has no sense of domain  a plausible-sounding search term
  can match the wrong meaning of a word entirely.** `manage.py fetch_category_images`'s
  `HARDWARE_SEARCH_TERMS` hit this repeatedly (2026-07-29): `"mobile phone chip"` matched banana
  chips, a chip-and-pin card terminal, and a "fish 'n' chips" pub sign; `"desktop computer tower"`
  matched an actual stone tower building (Broadway Tower); `"gaming laptop computer"` matched a
  desktop-tower build log; `"computer monitor display"` matched a cat's reflection and, on a
  wider retry, a church and a camera. The fix each time was narrowing to camera/product vocabulary
  that has no common non-tech meaning (`"semiconductor silicon die"`, `"ATX"`, `"widescreen"`),
  verified by downloading and actually viewing the resulting photos  never trust a Commons
  search term is right just because it reads sensibly in English.
- **No emoji anywhere on the site  use real assets or inline SVG instead.** Country flags use
  `<img src="https://flagcdn.com/w40/{iso}.png">` in a circular wrapper (see the phone-number
  chip on settings.html/dashboard.html/billing.html), never `🇿🇲`-style flag emoji. Status/badge
  icons (✓, ✕, ⚠, ✨, etc.) are small inline `<svg viewBox="0 0 24 24" stroke="currentColor">`
  snippets sized to sit inline with text, not emoji characters. This applies site-wide, not just
  to new features  if you touch a page with a leftover emoji, replace it in the same pattern.
- **The 2026-07-29 em-dash sweep deleted the `—` character instead of replacing it with `-`**,
  leaving a bare double space in visible copy wherever an em dash used to sit (found on the
  ai-tools pages 2026-07-30; not yet swept site-wide  grep
  `grep -rnE '[a-z0-9,)"]  [a-z]' --include=*.html frontend/` to find the rest, excluding JS
  comments and the six Discover-exempt pages). If you're editing a page and a sentence reads
  oddly with two spaces and no visible punctuation between clauses, this is why  fix it to `-`
  in place rather than assuming it's pre-existing copy.
- **`nerdamer`'s single-letter variable regex bites the same way it bit `math_solver.html`**: a
  naive `\b[a-zA-Z]\b` never matches a letter directly touching a digit (`2x`, `3y`), since `\b`
  requires a word-boundary transition and `2`/`x` are both `\w`. Any future client-side algebra
  code that "detects the variable" from a coefficient-prefixed expression needs a lookaround
  (`(?<![a-zA-Z])x(?![a-zA-Z])`), not `\b`, or it silently defaults to the wrong symbol with no
  error. Related: nerdamer's `roots()` returns nonsense (`[i,-i]` for `-1`, `[0,0]` for `0`)
  when the variable has already cancelled out of the equation  check for a variable-free
  zero-form and special-case "no solution" / "identity" before ever calling `roots()`.
- **Keyword classification by bare substring (`kw in text`) matches the wrong word, not just the
  wrong boundary.** `news/services.py::classify_category` used to check `"ide" in text`, `"ai" in
  text`, `" sql" in text`  which also matched "guide"/"provider", "chain"/"captain", and
  "postgresql", silently mis-filing articles into the wrong category with no error (found
  2026-08-04 when "Devtools must be open source" got tagged Linux because `"open source"` sat in
  that category's list, a licence description with no connection to the OS). Every keyword is now
  compiled as `\bkeyword\b` (`_compile_keywords`) and text is normalized first (`_normalise`, so
  `A.I.`/`open-source`/`HTTP/3` all tokenize consistently). Same lesson as the nerdamer entry
  above, different codebase layer  don't reach for `in` on unbounded text for classification.
- **A client-facing error message must never name the backend stack.** 33 pages (`news.html`,
  `blog.html`, `hardware.html`, all 29 `networking/*.html` tool pages, `net_tools.html`) had a
  load/connection-failure banner reading "Make sure the Django API is running" or "Connection
  failed: could not reach the Django API" verbatim in production. Genericized to
  "Couldn't load ... right now, please try again" (the networking pages kept the appended
  `error.message`, since in practice that's just an HTTP status/generic fetch failure, not
  internal detail). When writing any user-visible error copy, grep for the framework/library name
  before shipping it  it's an easy thing to leave in from local-dev debugging.
- **Customer-facing transactional emails link to the bare domain `www.coreripper.site`, not a
  deep page path (2026-08-02).** Every outbound email to a real user (welcome, weekly digest,
  newsletter, news wrap-up, monitor alert, renewal reminder in `accounts/views.py`,
  `accounts/tasks.py`, `monitors/tasks.py`, `credits/tasks.py`, `news/services.py`) used to build
  links from `settings.FRONTEND_URL` as `{site}/dashboard.html`, `{site}/settings.html`,
  `{site}/news/post.html?id=`, etc. Per the user's decision these were all replaced with a single
  literal `www.coreripper.site` (no path, no query) to eliminate any chance of a 404 from a moved
  or renamed static page on the VPS. When adding a new customer email, do the same  point at
  `www.coreripper.site` and describe the destination in prose ("from your Billing page"), rather
  than composing a `FRONTEND_URL` deep link. The **admin/internal** news-digest email
  (`news/services.py`, staff-only) is the deliberate exception: it still links to the working
  Django `/admin/news/newsdraft/<id>/change/` moderation page via `settings.SITE_URL`.
- **Google Sign-In's client ID is duplicated in three independent places that must all agree**:
  `backend/.env`'s `GOOGLE_CLIENT_ID` (used server-side to verify the ID token) and a **hardcoded**
  JS constant in both `frontend/login.html` and `frontend/signup.html` (used client-side to
  initialize `google.accounts.id`, since the Google Identity Services button has no way to read a
  server-side env var). Rotating the OAuth client in Google Cloud Console and updating only the
  `.env` value leaves the frontend still authenticating against the *old* client  which still
  won't have the current domain in its Authorized JavaScript origins, so the failure looks
  identical to a fresh unconfigured-origin error. Grep both frontend files for the client ID
  literal whenever the Google Cloud credential changes.
- **Django's own default logging silently swallows every production 500.** With `DEBUG=False` and
  no custom `LOGGING` dict, Django's built-in config only reports `django.request` errors via
  `mail_admins()`  which is a silent no-op whenever `ADMINS` is empty (the out-of-the-box state
  here). A real unhandled exception in production therefore left **zero trace** in gunicorn's own
  `--error-logfile`, because that only captures stderr and nothing in the default config writes
  request errors to stderr. Fixed by adding a `LOGGING` dict in `settings.py` that routes
  `django.request` (and everything else) to a console `StreamHandler`, which gunicorn's
  `--error-logfile` does capture. Don't assume "the error log is empty" means "nothing broke" on
  any Django deployment without first confirming a `LOGGING` config actually exists.

## In-flight work: VPS/go-live readiness pass (paused 2026-07-24)

Goal set by the user: *"once CoreRipper is deployed on a VPS, Lenco will provide an API key —
I want everything to work once I paste the API key"*, plus *"make sure the right service(s) is
provided depending on the plan"*. The tree is **consistent and green** (68 tests pass, live
endpoints 200) — the items below are simply not started, not half-applied.

**Done in this pass** (all verified): credit-pack checkout end-to-end (see the payments section
above); `accounts/entitlements.py` + its wiring into monitors / Security Grade / AI-Crawler;
`DJANGO_*` deployment settings made env-driven; a real bug fixed in `payments/lenco.py` where a
card charge with no `LENCO_PUBLIC_KEY` left a dangling `pending` Payment row (the momo path
already handled this; the card path didn't).

**Also done (2026-07-24 session, all verified):**
1. **`.env` / `.env.example` placeholders.** `.env.example` is now the annotated master list of
   every var the code actually reads (grep-verified against the tree), organised by subsystem,
   with a 6-step go-live checklist at the top and the blank-vs-absent gotcha above documented
   inline. `.env` mirrors it, keeping the existing local values byte-identical — verified by
   diffing loaded settings before/after. Go-live is now a `.env` edit only.
2. **Frontend API base is origin-aware.** Sweep script replaced all 161 hardcoded
   `http://127.0.0.1:8000` literals across all 96 pages with `window.CR_API_BASE` (see the
   Frontend section). Verified: 556 inline script blocks in all 96 pages pass `node --check`;
   the resolver is defined exactly once per file, inside `<head>`, before every use; and in a
   real browser on a page served from port 34265 it resolved to `http://localhost:8000` and
   drove live `GET /api/payments/pricing/` (real ZMW prices rendered) and
   `GET /api/toolbox/?tool=http_status` (200 OK, result rendered) with zero console errors.
3. **`CORS_ALLOW_ALL_ORIGINS` is derived, not hardcoded** — `DEBUG and not CORS_ALLOWED_ORIGINS`,
   with the whitelist from `DJANGO_CORS_ALLOWED_ORIGINS`. Verified that a DEBUG=0 config turns
   allow-all off whether or not a whitelist is set, and that local behavior is unchanged.

**Also done (2026-07-25 session, all verified):** the session-hardening pass  AuthToken
expiry + Remember-Me rotating refresh tokens + server-side logout + the swept `CoreRipperAuth`
keeper snippet in all 96 pages (see the Auth section above for the full mechanics). The user's
source spec was a cookie-based architecture doc; the deliberate decision was a hybrid: keep
bearer-token auth, adopt only the expiry/refresh/rotation/logout security wins, keep
preferences out of cookies. Verified: 68 backend tests green, 652 inline script blocks pass
`node --check`, and the full login→expire→silent-restore→logout loop exercised in a real
browser against the live backend.

**Also done (2026-07-25, later session, all verified):** the Workbench client-state pass  the
`localStorage` snapshot, the server-sourced AI-usage chip, and the floating/draggable Assistant
window (all three described under "The Workbench's client-state model" above), plus the
Assistant's missing in-flight affordances (typing indicator, disabled input while a request is
open, focus restore, auto-scroll, clear-conversation, network-failure bubble). This was
`dashboard.html` only  no backend change, no sweep script, no other page touched. Verified in a
real browser against the live backend on a real premium account: a real Groq assistant call and a
real `http_status` batch both survived a reload, and the chip still read correctly after the
local snapshot was deleted (proving it reads the server, not the cache).

**Also done (2026-07-28 session, all verified):** homepage redesign (`index.html` rebuilt against
a design handoff: terminal-typewriter hero badge, 10-tool showcase slideshow, five-pillar feature
grid — Website Monitoring and Workbench deliberately merged into one "Premium Workspace"
card/section since they're both premium-gated, not because they share a minimum tier (see below),
grouped global search, live stats band kept in place of the handoff's static trust-strip copy) —
plus a **site-wide nav sweep**: the existing per-page "Content" dropdown (Blog/News/Hardware,
present on 87 of 96 pages) was renamed to "Discover" and moved from mid-row to the end of the
desktop link row (after Pricing), via a regex-based Python sweep script rather than hand-editing
each page, consistent with the "no shared bundle → sweep script" convention above. Two real bugs
were caught and fixed in the process, not introduced by intent: (1) the sweep's first pass had an
off-by-one regex group index that corrupted the Pricing link's `class` attribute on 77 subpages
into e.g. `class="nav-link../ font-medium"` — caught by a post-sweep grep before calling it done,
fixed with a targeted follow-up regex; (2) the page-local-CSS gotcha above (73 pages had dropdown
markup but no dropdown CSS, entirely pre-existing and unrelated to the sweep, surfaced only
because the Discover rename made the always-expanded state visible in a screenshot).
Access-matrix accuracy pass (prompted by re-verifying the merged Premium Workspace copy against
`accounts/entitlements.py`): the Workbench is Lite+ but Website Monitoring is **Standard+**, not
Lite+ — the homepage's pricing cards, FAQ answer, and Premium Workspace copy previously
(incorrectly, inherited from the design handoff) implied both were available starting at Lite;
now corrected everywhere on the page, and the "Start your free trial" CTA was wired to check
`is_premium` from `/api/accounts/me/` so a logged-in user is routed to the Workbench or Pricing
instead of back to `signup.html`. Verified: all 96 pages pass `node --check` on every inline
script; live-browser spot checks of the new Discover dropdown (open/close, correct relative hrefs)
on a root page, a page where the dropdown item is self-referential (`blog.html`'s own "Blog" entry
carries `active`), and a two-levels-deep page (`networking/traceroute.html`).

**Also done (2026-07-29 session, all verified):** settings.html + billing.html account-pages
pass — these two were the last pages still showing pre-tier-rework/pre-credit-engine UI (item 2
below, now partially closed for these two pages specifically; monitors.html-equivalent 402
handling is still open, see below).
- **Account dropdown added to settings.html's header.** It previously had a bare avatar with no
  click handler and no logout button anywhere on the page (billing.html/support.html had the same
  gap). Now reuses the site's existing `cr-dd-menu`/`cr-dd-btn`/`cr-nav-dropdown` pattern (see the
  gotcha above) verbatim from `dev_tools.html`, giving Workbench/Billing/Support/Admin-Panel links
  + a working `CoreRipperAuth.logout()` call.
- **Plan name display fixed on both pages.** Both were checking `sub.plan === 'premium'` (the
  legacy pre-tier-rework value), so every Lite/Standard/Pro subscriber displayed as "Free". Now
  reads `entitlements.plan` (already normalized by `get_plan()`) through a shared client-side
  `PLAN_LABELS` map. While trialing, the name shows just **"Trial"** (not e.g. "Pro" next to a
  "TRIAL" badge)  the tier the trial grants isn't what the user actually has, and showing both
  read as two competing labels.
- **`billing_view` (`accounts/views.py`) now returns a `credits` block**
  (`subscription_balance`/`pack_balance`/`total_balance`/`monthly_grant`, the last resolved from
  `settings.TIER_MONTHLY_CREDITS` via `get_plan()`) so both pages can render a real Claude-credit
  meter. It replaces a stale "AI budget used this month  $X / $4.20" bar that was showing
  `core.quota.PREMIUM_MONTHLY_CAP_USD`  an **internal free-model margin guardrail**, not a
  number any customer bought. The new meter's number is **`total_balance`, not just
  `subscription_balance`**  a bought boost/recharge (`PackCreditLot`) genuinely raises how much
  Claude the user can use right now, so it must count, not just appear as a footnote. It can
  legitimately read over 100% of the monthly grant once a boost stacks on an untouched grant; the
  bar fill is capped visually while the number itself stays honest.
- **billing.html's "Plans" grid reworked from a stale Free/Premium/Enterprise 3-card layout to
  the real Free/Lite/Standard/Pro tiers** ("Enterprise" didn't exist anywhere in
  `entitlements.py` or `pricing.html`  it was invented). Prices come live from the same
  `/api/payments/pricing/` call the picker below already used (no new endpoint); "current plan"
  now highlights the user's real tier instead of a binary premium/not; each non-current lower
  tier's button pre-selects that tier in the payment picker and scrolls to it
  (`chooseUpgradePlan()`) rather than leaving the visitor to find the right option themselves.
- Along the way, a real (unrelated) bug was caught on settings.html: the "Back to Site" link used
  Tailwind utility classes (`w-4 h-4`, `flex items-center gap-2`, etc.) on a page that never loads
  the Tailwind CDN  see the new gotcha below.

**New gotcha this session:** **a Tailwind utility class on a page with no Tailwind CDN is a
silent no-op, not an error**  worst case is an SVG with no explicit `width`/`height` (relying on
`w-4 h-4` to size it) falling back to the browser's default replaced-element size (300×150px),
which renders as a giant icon with no console warning. `dev_tools.html`/`ai_tools.html`/etc. load
Tailwind; `settings.html`/`billing.html`/`support.html`/`dashboard.html` do not  copying markup
between the two groups needs inline styles + explicit SVG dimensions, not Tailwind classes.

**Also done (2026-07-29, later session, all verified):** a security-disclosure pass plus three
site-wide sweeps.
- **Security audit**: confirmed `DJANGO_DEBUG` is correctly env-gated (on for local dev, with the
  go-live checklist in `.env.example` already covering turning it off  not a code defect) and
  genericized the one real leak found, the Google-login endpoint's `invalid_token` error, which
  was echoing the raw `ValueError` from `google.oauth2.id_token.verify_oauth2_token` back to the
  client (`accounts/views.py`); every other JSON error response site-wide was already generic.
- **AI engine rebrand to Livia/Sonnet-5**  see "The credit engine" section above for the full
  detail; this also collapsed the ai-tools model switcher from three options to two.
- **Em dash banned outside Discover.** Site-wide copy no longer uses `—`/`&mdash;` (swapped for a
  plain `-`)  except on the Discover pages (`blog.html`, `blog/post.html`, `hardware.html`,
  `hardware/article.html`, `news.html`, `news/post.html`), which are exempt by deliberate
  decision, articles and all. (`hardware/compare.html` was on this list until it was deleted
  2026-07-29  see "In-flight work" below.)
- **Hex-load default loading indicator**  see the Frontend section above. Rolled out to `net_tools.html`
  and ~31 network/dev-tool pages, replacing the old plain `.spinner` CSS ring everywhere it appeared.
- **Space Grotesk is now the default font**  see the Brand tokens note in the Frontend section above.

**Also done (2026-07-29, hardware-comparison-removal session, all verified):** three unrelated
pieces of work in one session.
1. **News weekly wrap-up + archive** (`news/tasks.py::news_weekly_wrapup`, new, weekly Sunday
   03:50 UTC): summarizes every currently-published `NewsDraft` into one AI-generated prose
   wrap-up (`operation="news_wrapup"`, free-model-only via `run_ai(user=None, ...)`), emails it to
   every `NotificationPreference.product_updates=True` subscriber with real per-article links,
   then calls `.archive()` on each article (see the Content-moderation-apps section above)  never
   deletes them, specifically to avoid tanking SEO on already-indexed article URLs. New
   `GET /api/news/archive/` + `news.html?view=archive` keep archived articles internally linked
   and crawlable rather than orphaned. `auto_edit_blog` was moved to weekly (Monday, one day after
   the Sunday wrap-up) and `auto_edit_hardware` to monthly (1st-of-month), both per explicit user
   request; `auto_edit_news` itself stays daily. Verified: full archive/detail/feed cycle exercised
   against the live DB with a real article (archived, confirmed excluded from feed + still 200 on
   its own detail endpoint, then reverted), migrations applied cleanly.
2. **Five hardware `CategoryImage` search terms were quietly wrong** (found via a user bug report
   on the comparison page, before it was removed): `mobile_socs`, `desktop_pcs`, `gaming_laptops`,
   `monitors`, `motherboards` all had at least one photo that matched the wrong meaning of a
   keyword (see the new gotcha above for specifics). All five were refetched with corrected terms
   and the results verified by actually downloading and viewing each photo, not just trusting the
   filename. `seed_hardware_specs.py` also gained 16 more real, current-gen devices (Snapdragon 8
   Elite, Dimensity 9400, Exynos 2200/1380, Tensor G3, Kirin 9000s, Apple A16 Bionic, MacBook
   Air 15/Pro 16, Surface Laptop 6, Galaxy Book4 Pro, two more HP laptops, XPS 13 Plus, Yoga 9i,
   Vivobook Pro 15)  Wikidata sync alone was too historical-skewed to have these (documented
   gotcha above), and the comparison-page autocomplete surfaced the gap.
3. **The hardware device-vs-device comparison feature was removed entirely**, per explicit user
   decision ("just remove the hardware comparison feature, just focus on the news and hardware
   page")  not a bug fix, a scope cut. Deleted: `frontend/hardware/compare.html`,
   `backend/hardware/comparison.py`, the `HardwareComparisonVerdict` model (+ migration to drop
   the table), `compare_view` + its URL, the 8 per-type spec list/detail views + URLs (they existed
   only to feed the comparison page's autocomplete/side-panels  confirmed nothing else called
   them), `related_content.py`'s `comparison_link` plumbing, and the now-orphaned
   `seo.py::build_product_jsonld`. `COMPARISON_SPECS` survived, renamed `TRACKED_SPEC_FIELDS` and
   relocated to a new `hardware/spec_fields.py`, since `ai_knowledge.py` still needs it for
   spec-hash tracking  that's the one thing in this list that must not be re-deleted. Every
   frontend link into `compare.html` (hardware.html's CTA, article.html's "Compare this" link,
   index.html's 4 homepage chips + footer link + search-index entry) was removed too. Verified:
   Django system check clean, migrations applied, all edited HTML passes `node --check`, and
   `hardware.html`/`hardware/article.html`/`news.html` all confirmed to load with zero console
   errors and no dangling references in a real browser.

**Still to do, highest-value first:**
1. **No tests for `accounts/entitlements.py`** — `accounts/tests.py` now covers the
   session/refresh lifecycle (2026-07-25) but nothing entitlements-related. The tier matrix
   deserves real coverage (plan resolution through an expired sub, the 402 shape,
   Security-Grade depth redaction, monitor caps, crawler quota rollover).
2. **Frontend still doesn't fully reflect the new tier rules** — settings.html/billing.html were
   fixed 2026-07-29 (above), but the dashboard.html monitors UI still doesn't read the 402
   `required_plan` shape or `findings_hidden`/`depth` from Security Grade. A Lite user will still
   hit an unexplained 402 on the monitors UI until that page is wired too.
3. Engine Room CRUD tab for `CreditPackPrice` (Django admin covers it meanwhile).

**Audit conclusions on the Lenco path itself** (no code changes needed): provider swap, lazy key
loading, server-side amounts, idempotent settlement, webhook re-verification, FX snapshots and
the `payments` feature flag are all correctly wired; the three active `PlanPrice` rows map to
lite/standard/pro correctly and the legacy `premium` rows are inactive. The `payments/lenco.py`
constants were verified against the live API docs + two reference client libraries on 2026-07-29
(see the corrected create-momo payload in the Lenco-wiring bullet above), so the remaining go-live
steps are just the runtime checklist at the top of that file: paste the key, set
`PAYMENT_PROVIDER=lenco`, restart, then run the real-charge / webhook / card tests to re-confirm
on live infrastructure.

**Also done (2026-07-30 session, all verified):** an audit-and-polish pass over the 10
`frontend/ai-tools/*.html` pages, exercised live in a real browser against the local backend
(free-model path is configured via `LLM_API_KEY`/`LLM_FALLBACK_API_KEY`  don't confuse these
with the unset `GROQ_API_KEY`/`GEMINI_API_KEY` names, which don't exist in this codebase;
`ANTHROPIC_API_KEY` is genuinely unset locally, so the Claude path was verified via
`LLMNotConfigured` → 503 instead of a real call). Two real wrong-answer bugs fixed in
`math_solver.html` (see the new gotcha above for the root cause): a cancelled-out equation like
`x + 1 = x + 2` reported fabricated complex roots instead of "no solution", and
`detectVariable`'s `\b` regex never matched a coefficient-attached letter so every equation
solved for a hardcoded `x` regardless of its real variable  `2y + 6 = 0` displayed "Solving for
x" and got away with it only because `x` happened to be the majority case in prior testing.
Output was also reformatted from raw CAS syntax (`-5*x+x^2+6`, `(3*x+4)*x`) to sorted,
superscripted, spaced polynomial form. `citation_formatter.html` and `paraphrase_checker.html`'s
quick-cite both had an unconditional `${title}.` that double-punctuated any title already ending
in `?`/`!` (an `endSentence()` helper already existed in citation_formatter.html and simply
wasn't applied to the title field). `lecture_transcript.html` had no speech-to-text backend but
was advertised on `ai_tools.html` as a working **Free** tool, with the "not connected yet" notice
only appearing after a file was already picked; added a `.badge-soon` style, corrected both the
hub card and the tool page's hero copy, and made the notice visible on page load instead of
click-triggered. `readability_analyzer.html` had a singular/plural grammar bug ("1 sentence(s)
are longer"). Grammar checker, PDF summarizer, and the three server-backed tools
(feedback-tutor/quiz-generator/coding-helper) were exercised with edge cases and found correct as-
is  no changes made there. A separate spawned session is handling the site-wide em-dash-sweep
double-space cleanup (see the new gotcha above); it was scoped out of this session to keep the
diff to the AI tools only.

**Also done (2026-07-30, later session, all verified):** the `claude_ai` kill switch (full
mechanics under "The credit engine" and "Feature flags" above)  the user has no funded Anthropic
credits yet, so Sonnet-5 needed to ship fully wired but genuinely inert: every backend call site
that can reach the Claude API now checks the flag first (`run_ai`, `profile_view`'s
`preferred_model=claude` PATCH, `payments`' credit-pack checkout), and every frontend surface that
offers the model now reads `GET /api/features/` and renders it as disabled with "still being
worked on" instead of a click that only 503s: `net_tools.html`'s dead "Get API Access" CTA (a
separate, unrelated "coming soon"  no public API has ever existed), `pricing.html`'s credit-pack
grid, `billing.html`'s pack checkout tab, the three `ai-tools/*.html` model switchers (swept  all
three carry byte-identical switcher code), and `dashboard.html`'s Workbench switcher. Verified
live in a real browser end-to-end (not just unit tests): clicking the disabled Sonnet-5 option on
all four gated pages is confirmed inert both client-side and server-side (`preferred_model` never
changes), the Workbench case survives a full page reload with zero console errors, and the Engine
Room's Feature Switches tab correctly self-heals a "Sonnet-5 AI" row with no dedicated admin UI
needed. One gotcha hit while minting verification sessions: injecting a bearer token via
`preview_eval` without also stamping `coreripperHeartbeat`/`coreripperLastActivity`/
`sessionStorage.coreripperTabAlive` gets it silently wiped on the very next page load by the
session-hardening keeper's browser-close detection (a fresh preview tab has no prior heartbeat to
prove continuity, so it reads as "the browser was closed")  worth remembering for any future
verification session that injects tokens this way rather than driving the real login form. Go-live
is unchanged from the existing Lenco pattern: flip the flag in the Engine Room, no deploy needed.

**Also done (2026-07-30, later session, all verified):** admin moderation cards can now show and
change an article's picture — see "Moderation cards show the resolved image..." under the
Content-moderation-apps section above for the full mechanics (new `core/image_admin_views.py`
pool-listing endpoint, new per-app `.../<id>/image/` PATCH endpoints on news/hardware, blog's
editor reusing its existing upload endpoint + post-save path). Verified live against the real
database on a real pending Hardware draft: picking a pool photo updated the card immediately and
persisted to `HardwareArticle.intel_image_url`/`intel_image_credit`/`intel_image_provider`; the
News tab renders images the same way; the blog editor correctly showed "no pool photos yet" for a
category with no `CategoryImage` rows and still accepted a manual URL with a live preview. All 96
pages still pass the inline-script syntax check; test data was reverted after checking.

**Also done (2026-07-30, mobile-responsiveness + search/theme audit session, all verified):**
site-wide mobile pass plus two targeted bug fixes, no feature/animation removed anywhere (see the
new Frontend-section note above for the sweep script itself).
- Verified every search input site-wide is correctly wired (the three tool-hub pages' live
  filtering, `blog.html`'s backend-driven search, the homepage command-palette, and both
  country-dial-code pickers)  no orphaned/dead search boxes found. `news.html`/`hardware.html`
  have no search box at all (unlike `blog.html`), which is a real gap but a follow-on feature
  request, not a bug.
- Fixed the dark/light theme toggle on `news.html` and `hardware.html`: the checkbox and its
  `change` listener existed on both pages but only synced a cookie, never actually added/removed
  `body.light-mode`  `blog.html` had the real toggle logic in a second, separate listener that the
  other two never got when the feature was swept across pages. Fixed by adding the missing
  `document.body.classList.toggle('light-mode', this.checked)` line to both.
- The mobile sweep itself (all 97 pages, idempotent, re-runnable) plus a footer-specific follow-up
  fix (see the new Frontend-section gotcha above).

**Also done (2026-07-30, production incident response, all verified):** the first real day of live
traffic on the VPS surfaced a chain of unrelated infrastructure problems, found and fixed one at a
time by reading the actual server logs rather than guessing  the "Production deployment (VPS)"
architecture section above is a permanent record of the resulting topology, not just this
incident's timeline. In order:
1. Google Sign-In `origin_mismatch` (a new OAuth client had the right Authorized JavaScript
   origins, but the frontend's hardcoded client ID literal still pointed at the old one  see the
   new gotcha above).
2. Postgres refusing connections (`Connection refused` on 5432)  root cause was `pg_ctlcluster`
   refusing to start because a stray `chown -R deploy` had touched `/etc/postgresql/18/main`'s
   ownership; a second, related permission break on `/etc/ssl/private/ssl-cert-snakeoil.key` (also
   swept up by the same chown) then blocked Postgres's SSL cert read even after the first fix.
3. Signup 500ing once the DB was back  root cause was the site running gunicorn hand-started via
   `manage.py runserver` in an SSH tab that had since closed; replaced with the systemd service
   described above, which also meant fixing an nginx→gunicorn Unix-socket mismatch along the way
   (nginx expected a socket, the temporary gunicorn was bound to a TCP port).
4. **Django's default logging was silently swallowing the actual 500 traceback** (new `LOGGING`
   gotcha above)  without it, `error.log` showed nothing useful for the app-level bug, only
   infra-level connection errors.
5. Once logging worked, the real remaining 500 was `redis.exceptions.ConnectionError` from
   `FeatureFlagMiddleware`  Redis was down, and this middleware ran (and failed) on *every*
   `/api/` request, taking the entire API down over what should have been one degraded feature.
   Fixed per the new "Feature flags" cache-fallback note above.
6. Whole-site slowness after the above was fixed traced to `CONN_MAX_AGE` never having been set
   (new bullet under "Production deployment" above)  confirmed via a `curl -w` timing breakdown
   showing DNS/connect/TLS all fast but a 20s+ time-to-first-byte, which is a server-side hang, not
   a network one.
`EMAIL_TIMEOUT` (10s, env-overridable) was also added to `settings.py` along the way: Django's SMTP
backend has no timeout by default, so a blocked/unreachable outbound mail port  a real risk on a
fresh VPS until the provider allows 465/587  would otherwise hang a request indefinitely rather
than failing fast; this didn't end up being the actual cause of any symptom above; it's a bounded
version of a real class of risk none of the above investigation ruled out ahead of time.
