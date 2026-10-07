# Major changes and updates in this fork.

## Billing / Stripe hardening & invoicing

- New **"Pay by Invoice"** billing method (`ENABLE_INVOICE_BILLING`, due-days,
  notes) plus a **Pending Invoices** admin screen with mark-as-paid.
- Extensive webhook hardening: idempotency, race/lock-contention fixes, scoping
  webhooks to the member's own subscription, unique `stripe_customer_id`.
- `ENABLE_NEW_SUBSCRIPTIONS` kill-switch; payment-plan **descriptions**, "year"
  interval, and interval-casing fixes.
- **Invoice renewals**: renewal payments are recorded and confirmed by email,
  renewal invoices can be marked paid in Pending Invoices, and overdue invoices
  trigger a member reminder (existing installs must add the
  `customer.subscription.updated` webhook event). Untracked-subscription and
  locked-member payments alert an admin; billing emails reworded.

## Membership signup & lifecycle rework

- New derived `signupStage` field on `/api/profile/`; frontend screens
  (`MembershipStatusCard`, `MembershipPlan`, dashboard) all collapse onto it.
- Backend consolidated: `Profile.complete_signup()` / `complete_cancel()` replace
  the old `MakeMember` path.
- New **Terms & Conditions** step and **privacy-policy consent** checkbox in signup
  (`SIGNUP_REQUIRE_PRIVACY_CONSENT`, `TERMS_ACCEPTANCE_CARDS`, `terms_accepted_at`).
- `FORCE_SIGNUP_COMPLETION` redirects unfinished members; new admin **Signup
  Progress** and **Signup Preview** screens.

## Admin ManageMember overhaul

- The monolithic `ManageMember.vue` (~1,700 lines) split into per-tab components:
  **Access / Billing / Logs / Profile** tabs.
- "Three orthogonal buttons" model for member state; standalone **state-lock**
  control (`state_locked`), **Toggle Access** (`admin_disabled_access`), **Cancel
  Membership** endpoint, and an "ensure Stripe customer" tool.
- `state_locked` now freezes state outright, admin overrides included, until
  an explicit unlock. Any non-active member can be locked, including a pending
  invoice signup. "Make Member" is disabled while a member is locked.

## CAPTCHA (Cloudflare Turnstile)

- Register, login, `/api/token/obtain/` and password-reset requests are gated
  behind Turnstile (`ENABLE_CAPTCHA`, `CAPTCHA_SITE_KEY`, `CAPTCHA_SECRET_KEY`,
  `CAPTCHA_ALLOWED_HOSTNAMES`). No-op when off or unconfigured; fails closed
  when on. The SSO login path is gated too.
- New `services/captcha.py` verify helper with a short timeout and optional
  hostname binding; reusable `CaptchaWidget.vue` with retry on script-load
  failure.
- Login and token endpoints are now throttled (`MM_THROTTLE_LOGIN`,
  `MM_THROTTLE_TOKEN_OBTAIN`) and members see a rate-limit message. Operator
  docs cover setup and setting `MM_NUM_PROXIES` correctly.

## Django 5.2 LTS upgrade

- **Django 3.2 → 5.2 LTS**, by way of 4.2, with the libraries that follow it:
  Django REST framework 3.18, Channels 4 with daphne 4.2 and channels_redis 4.3,
  django-constance 4.3, django-import-export 4.4, django-oidc-provider 0.9, and
  newer celery-beat, celery-results, cors-headers, prometheus, pwned-passwords,
  simplejwt and api-key releases. django-csp (never configured),
  django-picklefield and pytz are removed.
- **Settings storage**: constance 4 keeps the Django-admin settings in a new
  table and as JSON instead of pickle. The migrations copy every saved value,
  delete empty ones so they fall back to their defaults, and import the old
  `HOME_PAGE_CARDS` into Dashboard Cards in whichever order they run. The
  project's own constance backend, a workaround for a constance bug, is gone.
- **Databases**: Django 5.2 needs PostgreSQL 14, MySQL 8.0.11 or MariaDB 10.5.
  UUID columns stay `char(32)` on MySQL and MariaDB (`Char32UUIDField`), so
  existing rows keep matching; migrations convert the native `uuid` columns a
  fresh MariaDB 10.7+ install would get.
- **CSRF Origin check**: since Django 4, every change sent with a session has
  to come from the portal's own address, so a reverse proxy must forward `Host`
  and `X-Forwarded-Proto`. The container's nginx forwards non-standard ports and
  drops `:443` and `:80`. The frontend dev server's origins are trusted in
  development only.
- **New `docs/UPGRADING.md`**: backing up, keeping the previous image and going
  back, plus a check for each change that can affect an existing install: the
  required `MM_SECRET_KEY` and `MM_ALLOWED_HOSTS`, OIDC signing keys, lowercase
  Redis TLS options, database versions, proxy headers and Cloudflare.
- **Tests**: websocket tests for door, interlock and memberbucks devices (also
  on channels_redis), OIDC sign-in, CSRF origins, member import and export, and
  a migration test that upgrades a database shaped like v3.8.0.

## Test suites & CI

- **Backend pytest suite** (`memberportal/pytest.ini`, `requirements-dev.txt`,
  shared fixtures/factories) covering the signup/cancel state machines,
  `can_signup`, `state_locked`, the Stripe webhook, pending invoices and CAPTCHA.
  CI runs it on SQLite and Postgres.
- **Frontend vitest** setup with a PR workflow.

# Smaller edits

- **Phone numbers → E.164**: client-side validation/formatting via
  `libphonenumber-js`, stored as E.164, parsed against a configurable
  `PROFILE_DEFAULT_PHONE_REGION`, plus a `backfill_phone_e164` management command.
- **Account/auth hardening**: unique `screen_name` constraint, case-insensitive
  email, atomic user writes, throttling on Register/ResetPassword, atomic
  verify-email token, `ENABLE_REGISTRATION` kill-switch.
- **Configurability**: new toggles to hide/disable features — recent-swipes page,
  last-seen page, report-issue card, member email/basic-detail editing, optional
  screen name, member-entered access cards.
- **UX polish**: responsive dashboard/quick-card grids, mobile-friendly metrics
  charts, profile form switched from auto-save to explicit submit, per-route
  `allowedStates` route guards.
- **Fuzzy admin member search**: accent/case/punctuation-insensitive,
  typo-tolerant, any word order, also matches member id and phone. Adds a clear
  button and Ctrl/Cmd+F shortcut; the members list now defaults to all states.
- **Skip Signup** on the plan page now asks for confirmation, stating that the
  person will not be a member.
- **Route guard fix**: a failed profile fetch now redirects instead of hanging
  navigation.
- **i18n & infra**: expanded Swedish (sv-SE) and en-AU translations; Docker image
  builds retargeted to the fork; Docker base image moved off EOL bullseye to
  trixie, and development standardised on Python 3.12.
