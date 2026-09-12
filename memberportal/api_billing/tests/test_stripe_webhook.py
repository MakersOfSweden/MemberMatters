"""StripeWebhook — transport invariants and the signup-payment paths.

This file pins behaviour that is already correct, so that the renewal fix
landing on top of it has something to break against. The endpoint is publicly
reachable and unauthenticated by design, so the gate tests below are load
bearing rather than incidental.

Two conventions worth knowing before adding cases:

* Every side effect in the webhook is deferred with transaction.on_commit, and
  under plain `django_db` the surrounding atomic block is rolled back, so those
  callbacks never fire. Any test asserting on `outbox` or on activation must
  run the request inside django_capture_on_commit_callbacks(execute=True) —
  otherwise it passes vacuously.
* `invoice_schema` parametrizes over Stripe's two payload shapes. Anything that
  reads the invoice's subscription id should use it, so a future API-version
  bump can't quietly break one shape.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from api_billing.models import ProcessedStripeEvent
from api_billing.webhook_handlers import HANDLERS, UnrecognisedInvoiceSchema
from profile.models import UserEventLog
from tests.factories import ProfileFactory

from .conftest import (
    CUSTOMER_ID,
    SUBSCRIPTION_ID,
    PaymentPlanFactory,
    build_event,
    build_invoice,
)

pytestmark = pytest.mark.django_db


# Signup requirements all off, so tests about the webhook aren't also tests of
# can_signup(). Cases that care turn the relevant ones back on.
NO_REQUIREMENTS = {
    "TERMS_ACCEPTANCE_CARDS": "[]",
    "ENABLE_STRIPE_MEMBERSHIP_PAYMENTS": True,
    "MOODLE_INDUCTION_ENABLED": False,
    "CANVAS_INDUCTION_ENABLED": False,
    "REQUIRE_ACCESS_CARD": False,
}


def only(**overrides):
    return pytest.mark.override_config(**{**NO_REQUIREMENTS, **overrides})


def subjects(outbox):
    return [message["Subject"] for message in outbox]


def logged(profile):
    """Descriptions from the member's audit trail, which is the sink an
    operator actually reads when reconciling a payment."""
    return [
        entry.description for entry in UserEventLog.objects.filter(user=profile.user)
    ]


class TestGates:
    @pytest.mark.override_config(STRIPE_WEBHOOK_SECRET="")
    def test_an_unconfigured_secret_fails_closed(
        self, post_webhook, stripe_event, subscribed_member
    ):
        # Signature verification is the only authentication this endpoint has.
        # Without a secret it must refuse rather than trust the payload.
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        response = post_webhook()

        assert response.status_code == 503
        subscribed_member.refresh_from_db()
        assert subscribed_member.state == "noob"
        assert not ProcessedStripeEvent.objects.exists()

    def test_a_bad_signature_is_rejected_without_inviting_retries(
        self, post_webhook, stripe_event, subscribed_member
    ):
        # Deliberately 200: a non-2xx makes Stripe redeliver a forged or
        # corrupt payload for ~3 days.
        stripe_event(exc=ValueError("bad signature"))

        response = post_webhook()

        assert response.status_code == 200
        assert response.data == {"error": "Error validating Stripe signature."}
        assert not ProcessedStripeEvent.objects.exists()

    def test_an_event_without_a_customer_is_ignored(self, post_webhook, stripe_event):
        stripe_event(
            event=build_event("invoice.paid", {"id": "in_1", "status": "paid"})
        )

        assert post_webhook().status_code == 200
        assert not ProcessedStripeEvent.objects.exists()

    def test_an_unknown_customer_is_ignored(self, post_webhook, stripe_event, db):
        stripe_event(
            event=build_event("invoice.paid", build_invoice(customer="cus_nobody"))
        )

        assert post_webhook().status_code == 200
        assert not ProcessedStripeEvent.objects.exists()

    def test_an_unhandled_event_type_is_dropped_before_the_dedup_row(
        self, post_webhook, stripe_event, subscribed_member
    ):
        stripe_event(
            event=build_event(
                "charge.succeeded", {"id": "ch_1", "customer": CUSTOMER_ID}
            )
        )

        assert post_webhook().status_code == 200
        assert not ProcessedStripeEvent.objects.exists()


class TestScoping:
    def test_an_invoice_for_another_subscription_leaves_no_dedup_row(
        self, post_webhook, stripe_event, subscribed_member, invoice_schema
    ):
        # The dedup row must be written only after scoping, so that an event
        # rejected in error can be fixed and redelivered. If the row were
        # written first, the redelivery would be silently swallowed.
        stripe_event(
            event=build_event(
                "invoice.paid",
                build_invoice(invoice_schema, subscription="sub_somethingelse"),
            )
        )

        assert post_webhook().status_code == 200
        subscribed_member.refresh_from_db()
        assert subscribed_member.subscription_status == "pending"
        assert not ProcessedStripeEvent.objects.exists()

    def test_a_subscription_delete_for_another_subscription_is_ignored(
        self, post_webhook, stripe_event, subscribed_member
    ):
        stripe_event(
            event=build_event(
                "customer.subscription.deleted",
                {"id": "sub_somethingelse", "customer": CUSTOMER_ID},
            )
        )

        assert post_webhook().status_code == 200
        subscribed_member.refresh_from_db()
        assert subscribed_member.stripe_subscription_id == SUBSCRIPTION_ID
        assert subscribed_member.membership_plan is not None

    @only()
    def test_the_matching_subscription_is_in_scope(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        invoice_schema,
        django_capture_on_commit_callbacks,
    ):
        stripe_event(event=build_event("invoice.paid", build_invoice(invoice_schema)))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        subscribed_member.refresh_from_db()
        assert subscribed_member.subscription_status == "active"


class TestIdempotency:
    @only()
    def test_a_redelivered_event_takes_effect_once(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Stripe retries for ~3 days on timeout, so the same event id can
        # legitimately arrive several times.
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        for _ in range(2):
            with django_capture_on_commit_callbacks(execute=True):
                post_webhook()

        subscribed_member.refresh_from_db()
        assert subscribed_member.state == "active"
        assert subjects(outbox).count("Your payment was successful.") == 1
        assert ProcessedStripeEvent.objects.count() == 1

    @only()
    def test_a_distinct_event_id_is_processed_separately(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        django_capture_on_commit_callbacks,
    ):
        for event_id in ("evt_1", "evt_2"):
            stripe_event(
                event=build_event("invoice.paid", build_invoice(), event_id=event_id)
            )
            with django_capture_on_commit_callbacks(execute=True):
                post_webhook()

        assert ProcessedStripeEvent.objects.count() == 2

    @only()
    def test_an_event_with_no_id_is_processed_but_recorded_nowhere(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        django_capture_on_commit_callbacks,
    ):
        # The dedup insert sits behind `if event_id:`, so a falsy id skips
        # idempotency altogether while the handler still runs. Stripe always
        # sends an id, making this a defensive branch — pinned because
        # nothing else reaches it, and because the exposure below rests on it.
        stripe_event(event=build_event("invoice.paid", build_invoice(), event_id=""))

        with django_capture_on_commit_callbacks(execute=True):
            assert post_webhook().status_code == 200

        subscribed_member.refresh_from_db()
        assert subscribed_member.subscription_status == "active"
        assert not ProcessedStripeEvent.objects.exists()

    @only()
    def test_an_id_less_redelivery_repeats_member_facing_side_effects(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Characterising the gap, not endorsing it: with no dedup row to skip
        # on, every redelivery re-runs the handler. invoice.paid self-limits
        # (a second delivery finds state="active" and returns down the renewal
        # path, whose bookkeeping is idempotent and which emails nobody), but
        # invoice.payment_failed guards on nothing, so the member is emailed
        # once per delivery across Stripe's ~3 days of retries. Change this to
        # assert 1 if the guard is ever tightened.
        stripe_event(
            event=build_event(
                "invoice.payment_failed", build_invoice(status="open"), event_id=""
            )
        )

        for _ in range(3):
            with django_capture_on_commit_callbacks(execute=True):
                post_webhook()

        assert subjects(outbox).count("Your membership payment failed") == 3
        assert not ProcessedStripeEvent.objects.exists()


class TestInvoicePaidActivates:
    @only()
    def test_a_paid_invoice_activates_a_member_who_meets_every_requirement(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        subscribed_member.refresh_from_db()
        assert subscribed_member.state == "active"
        assert subscribed_member.subscription_status == "active"
        assert subscribed_member.subscription_first_created is not None

        assert "Your payment was successful." in subjects(outbox)

    @only()
    def test_the_payment_email_precedes_the_welcome_email(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        member_mail = [
            m["Subject"] for m in outbox if m["To"] == subscribed_member.user.email
        ]
        assert member_mail[0] == "Your payment was successful."
        # activate() sends at least one further member-facing email.
        assert len(member_mail) > 1

    @only(MOODLE_INDUCTION_ENABLED=True)
    def test_an_unmet_requirement_records_payment_without_granting_access(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        subscribed_member.refresh_from_db()
        assert subscribed_member.subscription_status == "active"
        assert subscribed_member.state == "noob"
        assert "Your payment was received — additional steps needed" in subjects(outbox)
        # A noob part-way through signup is the ordinary case, not something
        # to page an admin about. Only a non-noob reaching here is unexpected.
        assert "Action Required: Verify returning member" not in subjects(outbox)

    @only(MOODLE_INDUCTION_ENABLED=True)
    def test_a_returning_member_who_cannot_signup_escalates_to_an_admin(
        self,
        post_webhook,
        stripe_event,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # state != "noob" means a human should decide whether to re-enable
        # access, rather than the webhook doing it silently.

        profile = ProfileFactory(
            inactive=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        profile.refresh_from_db()
        assert profile.state == "inactive"
        assert "Action Required: Verify returning member" in subjects(outbox)


class TestStateLockHold:
    @only()
    def test_a_locked_member_is_held_and_the_admin_is_told(
        self,
        post_webhook,
        stripe_event,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # A state_locked member paying must not self-unlock, however the
        # payment arrived (late delivery, or an admin marking an old invoice
        # paid in Stripe).

        profile = ProfileFactory(
            state_locked=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        profile.refresh_from_db()
        assert profile.state == "noob"
        assert profile.subscription_status == "inactive"
        assert profile.state_locked is True
        assert any("had an invoice paid" in subject for subject in subjects(outbox))


class TestSubscriptionDeleted:
    @only()
    def test_deletion_clears_the_subscription_and_deactivates(
        self,
        post_webhook,
        stripe_event,
        stripe_api,
        outbox,
        django_capture_on_commit_callbacks,
    ):

        profile = ProfileFactory(
            active=True,
            subscription_active=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        stripe_event(
            event=build_event(
                "customer.subscription.deleted",
                {"id": SUBSCRIPTION_ID, "customer": CUSTOMER_ID},
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        profile.refresh_from_db()
        assert profile.membership_plan is None
        assert profile.stripe_subscription_id is None
        assert profile.subscription_status == "inactive"
        assert profile.state == "inactive"
        assert "Invoice.list" in stripe_api.names()

    @only()
    def test_open_invoices_are_voided_on_deletion(
        self,
        post_webhook,
        stripe_event,
        stripe_api,
        django_capture_on_commit_callbacks,
    ):
        # Stripe does not auto-void on cancel, so a member would otherwise keep
        # seeing a payable invoice for a membership that no longer exists.

        class _Invoice:
            def __init__(self, id):
                self.id = id

        stripe_api.open_invoices = [_Invoice("in_open1"), _Invoice("in_open2")]
        ProfileFactory(
            active=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        stripe_event(
            event=build_event(
                "customer.subscription.deleted",
                {"id": SUBSCRIPTION_ID, "customer": CUSTOMER_ID},
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        voided = [
            args[0]
            for name, args, _ in stripe_api.calls
            if name == "Invoice.void_invoice"
        ]
        assert voided == ["in_open1", "in_open2"]

    @only()
    def test_a_failure_to_list_invoices_still_commits_the_state_change(
        self,
        post_webhook,
        stripe_event,
        stripe_api,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # The DB writes happen inside the transaction; the Stripe cleanup is an
        # on_commit best effort. A Stripe outage must not roll back the cancel.
        import stripe as stripe_lib

        stripe_api.raise_on["Invoice.list"] = stripe_lib.error.APIConnectionError(
            "down"
        )
        profile = ProfileFactory(
            active=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        stripe_event(
            event=build_event(
                "customer.subscription.deleted",
                {"id": SUBSCRIPTION_ID, "customer": CUSTOMER_ID},
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        profile.refresh_from_db()
        assert profile.subscription_status == "inactive"
        assert any("audit cancelled Stripe" in subject for subject in subjects(outbox))

    @only()
    def test_one_failed_void_does_not_abandon_the_rest(
        self,
        post_webhook,
        stripe_event,
        stripe_api,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Each void is individually wrapped, so a single stubborn invoice
        # cannot leave the remainder payable in the customer's Stripe portal.
        import stripe as stripe_lib

        class _Invoice:
            def __init__(self, id):
                self.id = id

        stripe_api.open_invoices = [_Invoice("in_bad"), _Invoice("in_good")]
        stripe_api.raise_on["Invoice.void_invoice"] = [
            stripe_lib.error.InvalidRequestError("nope", param=None),
            None,
        ]
        ProfileFactory(
            active=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        stripe_event(
            event=build_event(
                "customer.subscription.deleted",
                {"id": SUBSCRIPTION_ID, "customer": CUSTOMER_ID},
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        attempted = [
            args[0]
            for name, args, _ in stripe_api.calls
            if name == "Invoice.void_invoice"
        ]
        assert attempted == ["in_bad", "in_good"]
        assert any("void Stripe invoice in_bad" in s for s in subjects(outbox))

    @only()
    def test_the_admin_is_told_before_the_member_loses_access(
        self,
        post_webhook,
        stripe_event,
        stripe_api,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # The admin notice is registered ahead of complete_cancel so it lands
        # before the access-disabled mail deactivate() sends. Same ordering
        # guarantee as the paid path, which is tested above.
        profile = ProfileFactory(
            active=True,
            subscription_active=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        full_name = profile.get_full_name()
        stripe_event(
            event=build_event(
                "customer.subscription.deleted",
                {"id": SUBSCRIPTION_ID, "customer": CUSTOMER_ID},
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        sent = subjects(outbox)
        admin_notice = f"The membership for {full_name} was just cancelled"
        assert admin_notice in sent
        member_mail = [i for i, m in enumerate(outbox) if m["To"] == profile.user.email]
        assert member_mail, "deactivate() should have emailed the member"
        assert sent.index(admin_notice) < member_mail[0]

    @only()
    def test_a_failing_deactivation_cannot_escape_a_committed_request(
        self,
        post_webhook,
        stripe_event,
        stripe_api,
        outbox,
        monkeypatch,
        django_capture_on_commit_callbacks,
    ):
        # Mirror of the paid path: complete_cancel is registered last, so the
        # voiding and admin notice below have already run when it raises. The
        # wrap is about containment, not sibling protection — see
        # test_a_failing_activation_cannot_escape_a_committed_request.
        class _Invoice:
            def __init__(self, id):
                self.id = id

        def _explode(self, *args, **kwargs):
            raise RuntimeError("deactivation failed")

        monkeypatch.setattr(
            "profile.models.Profile.complete_cancel", _explode, raising=True
        )
        stripe_api.open_invoices = [_Invoice("in_open1")]
        profile = ProfileFactory(
            active=True,
            subscription_active=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        full_name = profile.get_full_name()
        stripe_event(
            event=build_event(
                "customer.subscription.deleted",
                {"id": SUBSCRIPTION_ID, "customer": CUSTOMER_ID},
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            assert post_webhook().status_code == 200

        profile.refresh_from_db()
        assert profile.subscription_status == "inactive"
        # Self-guard: deactivation really was prevented.
        assert profile.state == "active"
        assert "in_open1" in [
            args[0]
            for name, args, _ in stripe_api.calls
            if name == "Invoice.void_invoice"
        ]
        assert f"The membership for {full_name} was just cancelled" in subjects(outbox)


class TestRenewal:
    """Payments from members who are already active.

    Distinct from signup: there is nothing to activate, so what matters is
    that the payment is recorded and the member is left undisturbed.
    """

    @pytest.fixture
    def renewing_member(self, db):
        """An established member, mid-subscription, on manual renewal."""
        return ProfileFactory(
            active=True,
            subscription_active=True,
            billing_method="invoice",
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
            subscription_first_created=timezone.now() - timedelta(days=365),
        )

    @only()
    def test_a_renewal_payment_is_recorded_and_the_member_left_alone(
        self,
        post_webhook,
        stripe_event,
        renewing_member,
        outbox,
        monkeypatch,
        django_capture_on_commit_callbacks,
    ):
        signups = []
        monkeypatch.setattr(
            "profile.models.Profile.complete_signup",
            lambda self, *a, **kw: signups.append(self),
            raising=True,
        )
        first_created = renewing_member.subscription_first_created
        stripe_event(
            event=build_event(
                "invoice.paid", build_invoice(billing_reason="subscription_cycle")
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            assert post_webhook().status_code == 200

        renewing_member.refresh_from_db()
        assert renewing_member.state == "active"
        assert renewing_member.subscription_status == "active"
        # Not re-stamped — this is an audit record of the FIRST ever payment.
        assert renewing_member.subscription_first_created == first_created
        # Renewals are silent: no welcome, no access-enabled, and not the
        # signup-only "check for another email" copy.
        assert outbox == []
        assert signups == []
        assert any(
            "Renewal payment recorded" in entry for entry in logged(renewing_member)
        )

    @only()
    def test_a_renewal_repairs_a_status_that_has_drifted(
        self,
        post_webhook,
        stripe_event,
        renewing_member,
        django_capture_on_commit_callbacks,
    ):
        # A payment is unambiguous evidence the subscription is live, whatever
        # left the status saying otherwise.
        renewing_member.subscription_status = "pending"
        renewing_member.save(update_fields=["subscription_status"])
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        renewing_member.refresh_from_db()
        assert renewing_member.subscription_status == "active"

    @only()
    def test_a_late_final_invoice_does_not_un_cancel_a_leaving_member(
        self,
        post_webhook,
        stripe_event,
        renewing_member,
        django_capture_on_commit_callbacks,
    ):
        # A member who cancelled at period end can still have their final
        # invoice settle afterwards. Re-asserting "active" here would drop the
        # "your membership ends on ..." notice and tell them they are staying.
        renewing_member.subscription_status = "cancelling"
        renewing_member.save(update_fields=["subscription_status"])
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        renewing_member.refresh_from_db()
        assert renewing_member.subscription_status == "cancelling"

    @only()
    def test_an_out_of_band_renewal_is_indistinguishable_from_a_stripe_one(
        self,
        post_webhook,
        stripe_event,
        renewing_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # How an admin records a bank transfer: stripe.Invoice.pay(
        # paid_out_of_band=True). It changes the invoice's status, not its
        # billing_reason, so the renewal path must treat it identically.
        stripe_event(
            event=build_event(
                "invoice.paid",
                build_invoice(
                    billing_reason="subscription_cycle", paid_out_of_band=True
                ),
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        renewing_member.refresh_from_db()
        assert renewing_member.subscription_status == "active"
        assert renewing_member.state == "active"
        assert outbox == []

    @only()
    def test_a_renewal_backfills_a_missing_first_payment_stamp(
        self,
        post_webhook,
        stripe_event,
        renewing_member,
        django_capture_on_commit_callbacks,
    ):
        # Members who predate the stamp have it null; the next payment is the
        # earliest date we can honestly record.
        renewing_member.subscription_first_created = None
        renewing_member.save(update_fields=["subscription_first_created"])
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        renewing_member.refresh_from_db()
        assert renewing_member.subscription_first_created is not None

    @only()
    def test_a_renewal_for_a_locked_member_is_still_held(
        self,
        post_webhook,
        stripe_event,
        outbox,
        monkeypatch,
        django_capture_on_commit_callbacks,
    ):
        # The lock outranks the renewal path: recording the payment must not
        # quietly restore a status an admin deliberately took away.
        signups = []
        monkeypatch.setattr(
            "profile.models.Profile.complete_signup",
            lambda self, *a, **kw: signups.append(self),
            raising=True,
        )
        profile = ProfileFactory(
            inactive=True,
            state_locked=True,
            billing_method="invoice",
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        profile.refresh_from_db()
        assert profile.state == "inactive"
        assert profile.subscription_status == "inactive"
        assert signups == []
        assert any("had an invoice paid" in subject for subject in subjects(outbox))


class TestCallbackIsolation:
    """The direction that genuinely protects siblings: the callbacks
    registered FIRST. An unwrapped raise there aborts Django's on_commit loop
    and everything registered after it never runs at all.
    """

    @only()
    def test_a_failing_receipt_email_does_not_block_activation(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        monkeypatch,
        django_capture_on_commit_callbacks,
    ):
        # The receipt email is registered before complete_signup. Without its
        # wrap, an SMTP blip means the member pays and is silently never
        # activated — precisely the trade the handler comments claim to make:
        # a missed receipt beats a paid member with no access.
        def _explode(self, *args, **kwargs):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(
            "profile.models.User.email_notification", _explode, raising=True
        )
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            assert post_webhook().status_code == 200

        subscribed_member.refresh_from_db()
        assert subscribed_member.state == "active"


class TestHandlerRegistry:
    def test_every_handler_type_is_understood_by_the_scope_classifier(self):
        # classify_event_scope special-cases customer.subscription.deleted and
        # treats everything else as an invoice event, scoping it by an invoice
        # subscription lookup. A handler registered for some other event shape
        # would be scoped out silently and never run. This assertion exists to
        # fail when HANDLERS grows, forcing a look at the classifier.
        assert set(HANDLERS) == {
            "invoice.paid",
            "invoice.payment_failed",
            "customer.subscription.deleted",
        }


class TestInvoicePaymentFailed:
    # The member-facing copy is rewritten in a later commit; what is pinned
    # here is that the handler runs at all, and that it is scoped.
    @only()
    def test_a_failed_payment_notifies_the_member(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        outbox,
        django_capture_on_commit_callbacks,
        invoice_schema,
    ):
        stripe_event(
            event=build_event(
                "invoice.payment_failed",
                build_invoice(invoice_schema, status="open"),
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert [m["To"] for m in outbox] == [subscribed_member.user.email]
        subscribed_member.refresh_from_db()
        assert subscribed_member.state == "noob"

    def test_a_failed_payment_for_another_subscription_is_ignored(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        stripe_event(
            event=build_event(
                "invoice.payment_failed",
                build_invoice(subscription="sub_somethingelse", status="open"),
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert outbox == []
        assert not ProcessedStripeEvent.objects.exists()


class TestUnrecognisedInvoiceSchema:
    """The alarm for a webhook endpoint whose API version we cannot read.

    Without this, a Stripe version bump that moves the subscription id again
    would drop every renewal while the endpoint keeps answering 200 — the
    silent failure this whole change exists to prevent.
    """

    def test_a_subscription_invoice_with_no_readable_id_raises_the_alarm(
        self, post_webhook, stripe_event, subscribed_member, monkeypatch, caplog
    ):
        captured = []
        monkeypatch.setattr(
            "api_billing.webhook_handlers.capture_exception", captured.append
        )
        stripe_event(
            event=build_event(
                "invoice.paid",
                build_invoice(subscription=None, billing_reason="subscription_cycle"),
            )
        )

        with caplog.at_level("ERROR", logger="billing"):
            assert post_webhook().status_code == 200

        assert len(captured) == 1
        assert isinstance(captured[0], UnrecognisedInvoiceSchema)
        assert "subscription_cycle" in str(captured[0])
        assert "in_test123" in str(captured[0])
        assert any("either payload schema" in r.message for r in caplog.records)
        # Still ignored, and still no dedup row — a redelivery after the
        # reader is fixed must be able to complete.
        assert not ProcessedStripeEvent.objects.exists()

    def test_a_one_off_invoice_with_no_subscription_stays_quiet(
        self, post_webhook, stripe_event, subscribed_member, monkeypatch, caplog
    ):
        # One-off charges legitimately have no subscription. Alarming on those
        # would bury the real signal.
        captured = []
        monkeypatch.setattr(
            "api_billing.webhook_handlers.capture_exception", captured.append
        )
        stripe_event(
            event=build_event(
                "invoice.paid",
                build_invoice(subscription=None, billing_reason="manual"),
            )
        )

        with caplog.at_level("ERROR", logger="billing"):
            assert post_webhook().status_code == 200

        assert captured == []
        assert caplog.records == []


class TestNonPaidInvoiceStatus:
    @only()
    def test_an_invoice_that_is_not_paid_activates_nobody(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # invoice.paid should always carry status "paid", but every branch
        # guards on it, so pin that a mislabelled payload cannot grant access.
        stripe_event(event=build_event("invoice.paid", build_invoice(status="open")))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        subscribed_member.refresh_from_db()
        assert subscribed_member.state == "noob"
        assert subscribed_member.subscription_status == "pending"
        assert subscribed_member.subscription_first_created is None
        assert outbox == []


class TestOnCommitDiscipline:
    @only()
    def test_side_effects_do_not_fire_without_a_commit(
        self, post_webhook, stripe_event, subscribed_member, outbox
    ):
        # A guard on the suite itself. Every assertion about emails or
        # activation depends on capturing on_commit callbacks; if that ever
        # stops being necessary, the tests above are no longer proving what
        # they claim and this one will fail.
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        post_webhook()

        subscribed_member.refresh_from_db()
        assert subscribed_member.subscription_status == "active"  # inside the txn
        assert subscribed_member.state == "noob"  # activation is deferred
        assert outbox == []

    @only()
    def test_a_failing_activation_cannot_escape_a_committed_request(
        self,
        post_webhook,
        stripe_event,
        subscribed_member,
        outbox,
        monkeypatch,
        django_capture_on_commit_callbacks,
    ):
        # complete_signup is the LAST callback registered, so its wrap protects
        # nothing downstream — the receipt has already been sent by the time it
        # runs. What the wrap buys is containment: an escaping exception would
        # 500 a request whose DB writes and dedup row are already committed, so
        # every one of Stripe's ~3 days of retries is then swallowed by the
        # idempotency check and none of them repair anything.
        def _explode(self, *args, **kwargs):
            raise RuntimeError("activation failed")

        monkeypatch.setattr(
            "profile.models.Profile.complete_signup", _explode, raising=True
        )
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            response = post_webhook()

        assert response.status_code == 200
        subscribed_member.refresh_from_db()
        # Self-guard: if the patch target ever drifts, activation would
        # succeed and this test would go green while proving nothing.
        assert subscribed_member.state == "noob"
        assert subscribed_member.subscription_status == "active"
        assert "Your payment was successful." in subjects(outbox)
