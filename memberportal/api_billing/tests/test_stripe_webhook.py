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

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.utils import timezone

from api_billing.models import ProcessedStripeEvent
from api_billing.stripe_utils import format_invoice_due_date
from api_billing.webhook_handlers import (
    HANDLERS,
    UnrecognisedInvoiceSchema,
    payment_failed_copy,
)
from profile.models import SignupTriggeredBy, UserEventLog
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
        #
        # A one-off invoice, because a *paid subscription* invoice on another
        # subscription is escalated rather than ignored — see
        # TestOrphanedPayment.
        stripe_event(
            event=build_event(
                "invoice.paid",
                build_invoice(
                    invoice_schema,
                    subscription="sub_somethingelse",
                    billing_reason="manual",
                ),
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
        # on, every redelivery re-runs the handler and re-sends whatever it
        # emails — a renewal receipt on the paid path, this warning here. The
        # dedup row is what normally prevents that, so the exposure only
        # exists for the falsy-id case above, which Stripe does not produce.
        # Change this to assert 1 if the guard is ever tightened.
        stripe_event(
            event=build_event(
                "invoice.payment_failed", build_invoice(status="open"), event_id=""
            )
        )

        for _ in range(3):
            with django_capture_on_commit_callbacks(execute=True):
                post_webhook()

        # Deliberately copy-agnostic: what is being pinned is the repetition,
        # not the wording, which varies by billing method.
        assert len(outbox) == 3
        assert len(set(subjects(outbox))) == 1
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

    @only()
    def test_a_card_signup_activated_in_the_request_is_not_told_it_renewed(
        self,
        post_webhook,
        stripe_event,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # PaymentPlanSignup activates a card member who already meets every
        # requirement before Stripe delivers invoice.paid for the first invoice.
        profile = ProfileFactory(
            subscription_active=True,
            billing_method="card",
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=SUBSCRIPTION_ID,
            membership_plan=PaymentPlanFactory(),
        )
        with django_capture_on_commit_callbacks(execute=True):
            profile.complete_signup(SignupTriggeredBy.SUBSCRIPTION_CREATED)
        assert profile.state == "active"
        signup_mail = len(outbox)

        stripe_event(
            event=build_event(
                "invoice.paid", build_invoice(billing_reason="subscription_create")
            )
        )
        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert subjects(outbox[signup_mail:]) == [
            "Your membership payment was received"
        ]

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
    def test_an_unpaid_signup_lapses_with_one_admin_notice(
        self,
        post_webhook,
        stripe_event,
        stripe_api,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Stripe's past-due rule deleting the subscription of a member whose
        # first invoice was never paid. The member's own "signup has lapsed"
        # email is registered by complete_cancel from inside an on_commit
        # callback that is already running, which Django 3.2's capture never
        # executes, so that email is pinned in profile/tests instead.
        profile = ProfileFactory(
            subscription_pending=True,
            billing_method="invoice",
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

        profile.refresh_from_db()
        assert profile.state == "noob"
        assert profile.subscription_status == "inactive"
        assert profile.stripe_subscription_id is None
        assert subjects(outbox) == [
            f"The membership or pending signup for {full_name} has ended"
        ]
        assert "turned off" not in outbox[0]["HtmlBody"]

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
        admin_notice = f"The membership or pending signup for {full_name} has ended"
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
        assert (
            f"The membership or pending signup for {full_name} has ended"
            in subjects(outbox)
        )


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
        # A renewal receipt, and nothing else: no welcome, no access-enabled,
        # and not the signup-only "check for another email" copy.
        assert subjects(outbox) == ["Your membership has been renewed"]
        assert signups == []
        assert any(
            "Payment recorded (billing_reason=subscription_cycle)" in entry
            for entry in logged(renewing_member)
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
    def test_a_leaving_members_final_invoice_does_not_promise_a_renewal(
        self,
        post_webhook,
        stripe_event,
        renewing_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Reachable for invoice-billed members especially: the renewal invoice
        # is issued days before it falls due, so it can settle after they have
        # cancelled. A receipt is still owed — one that says they are leaving.
        renewing_member.subscription_status = "cancelling"
        renewing_member.save(update_fields=["subscription_status"])
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert subjects(outbox) == ["Your final membership payment"]
        assert "continues as normal" not in outbox[0]["HtmlBody"]

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
        assert subjects(outbox) == ["Your membership has been renewed"]

    @only()
    def test_the_renewal_receipt_states_what_was_charged(
        self,
        post_webhook,
        stripe_event,
        renewing_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        stripe_event(
            event=build_event(
                "invoice.paid",
                build_invoice(amount_paid=5500, currency="aud"),
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert "55.00 AUD" in outbox[0]["HtmlBody"]

    @only()
    def test_a_renewal_receipt_survives_an_invoice_with_no_amount(
        self,
        post_webhook,
        stripe_event,
        renewing_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Sending something beats sending copy that reads "$None".
        stripe_event(event=build_event("invoice.paid", build_invoice()))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert subjects(outbox) == ["Your membership has been renewed"]
        assert "None" not in outbox[0]["HtmlBody"]

    @only()
    @pytest.mark.parametrize(
        "billing_reason",
        ["subscription_create", "subscription_update", "subscription_threshold"],
    )
    def test_an_off_cycle_payment_gets_a_receipt_not_a_renewal_notice(
        self,
        billing_reason,
        post_webhook,
        stripe_event,
        renewing_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        stripe_event(
            event=build_event(
                "invoice.paid",
                build_invoice(
                    billing_reason=billing_reason, amount_paid=5500, currency="aud"
                ),
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert subjects(outbox) == ["Your membership payment was received"]
        assert "55.00 AUD" in outbox[0]["HtmlBody"]
        assert "continues as normal" not in outbox[0]["HtmlBody"]

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
        # classify_event_scope scopes SUBSCRIPTION_EVENTS by the subscription's
        # own id and treats everything else as an invoice event, scoping it by
        # an invoice subscription lookup. A handler registered for some other
        # event shape would be scoped out silently and never run. This
        # assertion exists to fail when HANDLERS grows, forcing a look at the
        # classifier.
        assert set(HANDLERS) == {
            "invoice.paid",
            "invoice.payment_failed",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }


class TestOverdueReminder:
    """customer.subscription.updated moving an invoice-billed subscription to
    past_due, which Stripe sends when the invoice is still unpaid at its due
    date. No Stripe Automation is involved."""

    DUE = 1700000000  # 2023-11-14

    @pytest.fixture
    def overdue_invoice(self, stripe_api):
        stripe_api.invoices["in_overdue"] = {
            "id": "in_overdue",
            "status": "open",
            "amount_due": 5500,
            "currency": "aud",
            "due_date": self.DUE,
            "hosted_invoice_url": "https://invoice.stripe.com/i/overdue",
        }
        return stripe_api

    @staticmethod
    def invoice_member(**overrides):
        return ProfileFactory(
            **{
                "state": "active",
                "subscription_status": "active",
                "billing_method": "invoice",
                "stripe_customer_id": CUSTOMER_ID,
                "stripe_subscription_id": SUBSCRIPTION_ID,
                "membership_plan": PaymentPlanFactory(),
                **overrides,
            }
        )

    @staticmethod
    def went_past_due(previous_attributes=None, event_id="evt_past_due", **fields):
        subscription = {
            "id": SUBSCRIPTION_ID,
            "customer": CUSTOMER_ID,
            "status": "past_due",
            "collection_method": "send_invoice",
            "latest_invoice": "in_overdue",
            **fields,
        }
        return build_event(
            "customer.subscription.updated",
            subscription,
            event_id=event_id,
            previous_attributes=(
                {"status": "active"}
                if previous_attributes is None
                else previous_attributes
            ),
        )

    @only()
    @pytest.mark.parametrize(
        "state, subscription_status",
        [
            pytest.param("active", "active", id="renewal"),
            pytest.param("noob", "pending", id="signup"),
            pytest.param("active", "cancelling", id="final-renewal"),
        ],
    )
    def test_an_invoice_member_whose_invoice_goes_past_due_is_reminded(
        self,
        state,
        subscription_status,
        post_webhook,
        stripe_event,
        overdue_invoice,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        profile = self.invoice_member(
            state=state, subscription_status=subscription_status
        )
        stripe_event(event=self.went_past_due())

        with django_capture_on_commit_callbacks(execute=True):
            assert post_webhook().status_code == 200

        assert [(m["To"], m["Subject"]) for m in outbox] == [
            (profile.user.email, "Reminder: your membership invoice is overdue")
        ]
        profile.refresh_from_db()
        assert (profile.state, profile.subscription_status) == (
            state,
            subscription_status,
        )

    @only()
    def test_the_reminder_states_the_debt_and_allows_for_an_unrecorded_payment(
        self,
        post_webhook,
        stripe_event,
        overdue_invoice,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        self.invoice_member()
        stripe_event(event=self.went_past_due())

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        body = outbox[0]["HtmlBody"]
        assert "55.00 AUD" in body
        assert format_invoice_due_date({"due_date": self.DUE}) in body
        assert "https://invoice.stripe.com/i/overdue" in body
        assert "bank transfer" in body
        assert "may not have had time to register your payment" in body
        assert "If you have further questions, contact us." in body
        assert "more time" not in body

    @only()
    def test_a_card_subscription_going_past_due_is_left_to_the_failed_payment_emails(
        self,
        post_webhook,
        stripe_event,
        overdue_invoice,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        self.invoice_member(billing_method="card")
        stripe_event(event=self.went_past_due(collection_method="charge_automatically"))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert outbox == []
        assert "Invoice.retrieve" not in overdue_invoice.names()

    @only()
    @pytest.mark.parametrize(
        "status, previous_attributes",
        [
            pytest.param("past_due", {}, id="past-due-but-status-unchanged"),
            pytest.param("active", {"status": "past_due"}, id="paid-back-to-active"),
            pytest.param(
                "active", {"cancel_at_period_end": False}, id="cancel-scheduled"
            ),
        ],
    )
    def test_an_update_that_is_not_a_move_into_past_due_sends_nothing(
        self,
        status,
        previous_attributes,
        post_webhook,
        stripe_event,
        overdue_invoice,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        self.invoice_member()
        stripe_event(
            event=self.went_past_due(
                previous_attributes=previous_attributes, status=status
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert outbox == []

    @only()
    def test_an_invoice_settled_before_the_reminder_goes_out_is_not_chased(
        self,
        post_webhook,
        stripe_event,
        overdue_invoice,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        overdue_invoice.invoices["in_overdue"]["status"] = "paid"
        self.invoice_member()
        stripe_event(event=self.went_past_due())

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert outbox == []

    @only()
    def test_a_locked_member_is_not_chased(
        self,
        post_webhook,
        stripe_event,
        overdue_invoice,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        profile = self.invoice_member(
            state="noob", subscription_status="pending", state_locked=True
        )
        stripe_event(event=self.went_past_due())

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert outbox == []
        assert any("no reminder sent to a locked member" in e for e in logged(profile))

    @only()
    def test_a_stripe_outage_still_sends_a_plain_reminder(
        self,
        post_webhook,
        stripe_event,
        overdue_invoice,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        import stripe as stripe_lib

        overdue_invoice.raise_on["Invoice.retrieve"] = (
            stripe_lib.error.APIConnectionError("down")
        )
        self.invoice_member()
        stripe_event(event=self.went_past_due())

        with django_capture_on_commit_callbacks(execute=True):
            assert post_webhook().status_code == 200

        assert subjects(outbox) == ["Reminder: your membership invoice is overdue"]
        body = outbox[0]["HtmlBody"]
        assert "is past its due date" in body
        assert "None" not in body

    def test_an_update_for_another_subscription_is_ignored(
        self,
        post_webhook,
        stripe_event,
        overdue_invoice,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        self.invoice_member()
        stripe_event(event=self.went_past_due(id="sub_somethingelse"))

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert outbox == []
        assert not ProcessedStripeEvent.objects.exists()

    @only()
    def test_a_redelivered_update_reminds_once(
        self,
        post_webhook,
        stripe_event,
        overdue_invoice,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        self.invoice_member()
        stripe_event(event=self.went_past_due())

        for _ in range(2):
            with django_capture_on_commit_callbacks(execute=True):
                post_webhook()

        assert len(outbox) == 1


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


class TestPaymentFailedCopy:
    """Wording of the failed-payment email, per billing method.

    A manual-renewal member is never charged automatically, so "update your
    billing method, we'll try again a few times" describes a process that does
    not exist for them and omits the one thing they need: how to pay.
    """

    PAST = 1700000000  # 2023-11-14
    FUTURE = 4102444800  # 2100-01-01

    def card_member(self):
        return ProfileFactory.build(billing_method="card")

    def invoice_member(self):
        return ProfileFactory.build(billing_method="invoice")

    def test_a_card_member_with_retries_left_is_not_alarmed(self):
        subject, message = payment_failed_copy(
            self.card_member(),
            {
                "amount_due": 5500,
                "currency": "aud",
                "next_payment_attempt": self.FUTURE,
            },
        )

        assert subject == "Your membership payment failed"
        assert "try again automatically" in message
        assert "55.00 AUD" in message
        assert "cancelled" not in message

    def test_a_card_member_out_of_retries_is_told_it_is_the_last_attempt(self):
        subject, message = payment_failed_copy(
            self.card_member(),
            {"amount_due": 5500, "currency": "aud", "next_payment_attempt": None},
        )

        assert subject == "Action needed: your membership payment failed"
        assert "last automatic attempt" in message
        assert "may be cancelled" in message
        assert "If you have further questions, contact us." in message
        assert "more time" not in message

    def test_an_invoice_member_before_the_due_date_gets_a_link_not_a_warning(self):
        subject, message = payment_failed_copy(
            self.invoice_member(),
            {
                "amount_due": 5500,
                "currency": "aud",
                "due_date": self.FUTURE,
                "hosted_invoice_url": "https://invoice.stripe.com/i/test",
            },
        )

        assert subject == "Your membership invoice payment didn't go through"
        assert "didn't go through" in message
        assert "https://invoice.stripe.com/i/test" in message
        # The card-flavoured phrases describe machinery this member has none of.
        assert "billing method" not in message
        assert "try again" not in message

    def test_an_invoice_member_past_the_due_date_is_told_plainly(self):
        subject, message = payment_failed_copy(
            self.invoice_member(),
            {
                "amount_due": 5500,
                "currency": "aud",
                "due_date": self.PAST,
                "hosted_invoice_url": "https://invoice.stripe.com/i/test",
            },
        )

        assert subject == "Your membership invoice is overdue"
        assert "didn't go through" in message
        assert "was due on" in message
        assert "https://invoice.stripe.com/i/test" in message
        assert "If you have further questions, contact us." in message
        assert "more time" not in message
        assert "try again" not in message

    def test_the_amount_owed_wins_over_stripes_zero_amount_paid(self):
        # Stripe stamps amount_paid=0 (not null) on an unpaid invoice, so a
        # real payload carries both fields and the email must quote the debt.
        _, message = payment_failed_copy(
            self.invoice_member(),
            {"amount_paid": 0, "amount_due": 5500, "currency": "aud"},
        )

        assert "55.00 AUD" in message
        assert "0.00" not in message

    def test_an_invoice_with_no_hosted_url_still_reads_cleanly(self):
        # hosted_invoice_url is absent until Stripe finalizes the invoice.
        _, message = payment_failed_copy(
            self.invoice_member(), {"amount_due": 5500, "currency": "aud"}
        )

        assert "None" not in message
        assert "pay it here" not in message

    def test_the_due_date_is_rendered_in_the_site_timezone(self):
        # Unix seconds rendered naively show the wrong day east of UTC.
        _, message = payment_failed_copy(
            self.invoice_member(),
            {"amount_due": 5500, "currency": "aud", "due_date": self.PAST},
        )

        expected = format_invoice_due_date({"due_date": self.PAST})
        assert expected in message

    def test_now_is_injectable_so_the_boundary_is_testable(self):
        invoice = {"amount_due": 5500, "currency": "aud", "due_date": self.PAST}
        just_before = datetime.fromtimestamp(self.PAST - 60, tz=dt_timezone.utc)
        just_after = datetime.fromtimestamp(self.PAST + 60, tz=dt_timezone.utc)

        before_subject, _ = payment_failed_copy(
            self.invoice_member(), invoice, now=just_before
        )
        after_subject, _ = payment_failed_copy(
            self.invoice_member(), invoice, now=just_after
        )

        assert before_subject == "Your membership invoice payment didn't go through"
        assert after_subject == "Your membership invoice is overdue"


class TestOrphanedPayment:
    """A paid invoice against a subscription the portal does not track.

    Reachable whenever stripe_subscription_id has moved on: the member's late
    payment on a subscription Stripe already cancelled, or one they replaced
    by re-signing up. Nothing can be reinstated from here — the point is that
    the money is not lost silently.
    """

    @pytest.fixture
    def former_member(self, db):
        # customer.subscription.deleted nulls stripe_subscription_id, so a
        # payment arriving afterwards matches no subscription.
        return ProfileFactory(
            inactive=True,
            billing_method="invoice",
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id=None,
        )

    @only()
    def test_a_late_payment_alerts_an_admin_and_changes_nothing(
        self,
        post_webhook,
        stripe_event,
        former_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        stripe_event(
            event=build_event(
                "invoice.paid",
                build_invoice(
                    subscription="sub_gone",
                    amount_paid=5500,
                    currency="aud",
                    billing_reason="subscription_cycle",
                ),
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            assert post_webhook().status_code == 200

        former_member.refresh_from_db()
        assert former_member.state == "inactive"
        assert former_member.subscription_status == "inactive"
        assert former_member.stripe_subscription_id is None

        assert len(outbox) == 1
        assert "untracked payment" in outbox[0]["Subject"]
        body = outbox[0]["HtmlBody"]
        assert "55.00 AUD" in body
        assert "sub_gone" in body

    @only()
    def test_a_redelivery_produces_one_alert_not_one_per_delivery(
        self,
        post_webhook,
        stripe_event,
        former_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Unlike an out-of-scope event, this branch takes no state action, so
        # there is nothing to fix and redeliver — it consumes its event id.
        stripe_event(
            event=build_event("invoice.paid", build_invoice(subscription="sub_gone"))
        )

        for _ in range(3):
            with django_capture_on_commit_callbacks(execute=True):
                post_webhook()

        assert len(outbox) == 1
        assert ProcessedStripeEvent.objects.count() == 1

    @only()
    def test_a_one_off_charge_does_not_alert(
        self,
        post_webhook,
        stripe_event,
        former_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Admin one-offs and other non-subscription invoices are ordinary.
        # Alerting on them would bury the signal this exists to raise.
        stripe_event(
            event=build_event(
                "invoice.paid",
                build_invoice(subscription="sub_gone", billing_reason="manual"),
            )
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        assert outbox == []
        assert not ProcessedStripeEvent.objects.exists()

    @only()
    def test_a_payment_on_a_replaced_subscription_leaves_the_new_one_alone(
        self,
        post_webhook,
        stripe_event,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # The member re-signed up, so they have a live subscription; the stale
        # payment must not disturb it.
        profile = ProfileFactory(
            active=True,
            subscription_active=True,
            stripe_customer_id=CUSTOMER_ID,
            stripe_subscription_id="sub_new",
            membership_plan=PaymentPlanFactory(),
        )
        stripe_event(
            event=build_event("invoice.paid", build_invoice(subscription="sub_old"))
        )

        with django_capture_on_commit_callbacks(execute=True):
            post_webhook()

        profile.refresh_from_db()
        assert profile.stripe_subscription_id == "sub_new"
        assert profile.subscription_status == "active"
        assert len(outbox) == 1
        assert "untracked payment" in outbox[0]["Subject"]

    @only()
    def test_an_unpaid_invoice_on_an_untracked_subscription_is_ignored(
        self,
        post_webhook,
        stripe_event,
        former_member,
        outbox,
        django_capture_on_commit_callbacks,
    ):
        # Only money actually arriving is worth escalating.
        stripe_event(
            event=build_event(
                "invoice.payment_failed",
                build_invoice(subscription="sub_gone", status="open"),
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
