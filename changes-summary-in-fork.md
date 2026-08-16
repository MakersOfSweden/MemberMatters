# Major changes and updates in this fork.

## Billing / Stripe hardening & invoicing

- New **"Pay by Invoice"** billing method (`ENABLE_INVOICE_BILLING`, due-days,
  notes) plus a **Pending Invoices** admin screen with mark-as-paid.
- Extensive webhook hardening: idempotency, race/lock-contention fixes, scoping
  webhooks to the member's own subscription, unique `stripe_customer_id`.
- `ENABLE_NEW_SUBSCRIPTIONS` kill-switch; payment-plan **descriptions**, "year"
  interval, and interval-casing fixes.

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
- **i18n & infra**: expanded Swedish (sv-SE) and en-AU translations; Docker image
  builds retargeted to the fork.
